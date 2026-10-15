"""
Mixture concentrations from stock solutions (C_mix = C_stock x V_added / V_total).

Papers often give the concentration of each solution BEFORE mixing, e.g.
kim2019: "ribose 1,2-cyclic phosphate (5 µL, 15 mM)", "nucleobases (20 µL,
3.75 mM)", "CaCl2 (8 µL, 15 mM)" -> one 33 µL mixture. The chemistry step
marks such values concentration_basis="stock" and lists every solution
combined (added_solutions); this module -- not the model -- does the
arithmetic, and adds the mixture value as a separate entry marked `derived`
(origin "calculated" in the provenance). The stock value is kept too, in its
own stock_<name>_aq_mM column (Mickey, 2026-10-15: include both).

Never guesses: a mixture value is only calculated when the species' own
solution and EVERY solution in that mixture have a volume that parses to a
volume unit. Otherwise nothing is added and a note says why. If the paper
itself gives the mixture concentration, that's used instead.
Running it twice is harmless (earlier derived entries are replaced).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from parameter_extractor.schemas.chemistry import AddedSolution, ChemistryExtraction, SoluteEntry
from parameter_extractor.units import convert, parse_quantity

SIGNIFICANT_FIGURES = 4


@dataclass
class MixingNote:
    kind: str           # "derived" (a mixture value was calculated) or "not_derived" (it couldn't be)
    message: str
    quote: str = ""
    source: str = ""


def _key(text: str) -> str:
    return " ".join(text.lower().split())


def _volume_uL(text: str) -> Optional[float]:
    q = parse_quantity(text or "")
    return convert(q[0], q[1], "µL") if q else None


def solutions_for(chemistry: ChemistryExtraction, set_label: Optional[str]) -> List[AddedSolution]:
    """The solutions combined for one set: the paper-wide ones ('') with any
    set-specific entry of the same name taking their place."""
    by_name: Dict[str, AddedSolution] = {}
    for sol in chemistry.added_solutions:
        if not sol.set_label:
            by_name.setdefault(_key(sol.solution), sol)
    for sol in chemistry.added_solutions:
        if set_label and sol.set_label == set_label:
            by_name[_key(sol.solution)] = sol
    return list(by_name.values())


def _mixture(entry: SoluteEntry, solutions: List[AddedSolution]) -> Tuple[Optional[float], str]:
    """(mixture mM, explanation) -- value None with the reason when it can't be calculated."""
    own = next((s for s in solutions if _key(s.solution) == _key(entry.stock_solution)), None)
    if own is None:
        return None, (f"the solution it was added in ('{entry.stock_solution}') isn't among the solutions "
                      f"listed for this mixture" if entry.stock_solution else
                      "the extraction didn't say which solution it was added in")
    volumes = [(s, _volume_uL(s.volume)) for s in solutions]
    unreadable = [f"'{s.solution}' ({s.volume or 'no volume'})" for s, v in volumes if v is None]
    if unreadable:
        return None, f"volume not readable for {', '.join(unreadable)}"
    total = sum(v for _, v in volumes)
    own_volume = next(v for s, v in volumes if s is own)
    if total <= 0:
        return None, "total volume is zero"
    value = float(f"{entry.concentration_mM * own_volume / total:.{SIGNIFICANT_FIGURES}g}")
    parts = " + ".join(f"{s.solution} {v:g} µL" for s, v in volumes)
    return value, (f"calculated by the pipeline from the stock concentration: {entry.concentration_mM:g} mM "
                   f"x {own_volume:g} µL / {total:g} µL total ({parts})")


def derive_mixture_concentrations(chemistry: ChemistryExtraction, set_labels: List[str]) -> List[MixingNote]:
    """Adds a derived mixture entry for each stock concentration that can be
    calculated. `set_labels`: the structure plan's sets, for a paper-wide stock
    value whose mixture differs by set."""
    chemistry.solutes = [s for s in chemistry.solutes if not s.derived]
    stated = {(s.set_label, s.sample_label, s.name) for s in chemistry.solutes
              if s.role == "initial" and s.concentration_basis == "mixture"}
    set_specific = any(sol.set_label for sol in chemistry.added_solutions)
    notes: List[MixingNote] = []
    for entry in [s for s in chemistry.solutes if s.role == "initial" and s.concentration_basis == "stock"]:
        if entry.concentration_mM is None:
            notes.append(MixingNote("not_derived", f"{entry.name}: stock concentration has no mM value, so the "
                                    f"mixture concentration wasn't calculated.", entry.quote, entry.source))
            continue
        # a paper-wide stock value gets one mixture value per set when the mixtures differ by set
        targets = [entry.set_label] if entry.set_label or not set_specific else list(set_labels)
        for label in targets:
            if (label, entry.sample_label, entry.name) in stated or (None, entry.sample_label, entry.name) in stated:
                continue                       # the paper gives the mixture value itself
            value, how = _mixture(entry, solutions_for(chemistry, label))
            where = f" (set '{label}')" if label else ""
            if value is None:
                notes.append(MixingNote("not_derived", f"{entry.name}{where}: mixture concentration not "
                                        f"calculated -- {how}. Only the stock value is recorded.",
                                        entry.quote, entry.source))
                continue
            derived = entry.model_copy(update=dict(
                set_label=label, concentration_basis="mixture", stock_solution="", concentration_value=value,
                concentration_unit_raw="mM", concentration_mM=value, conversion_note=how, derived=True))
            chemistry.solutes.append(derived)
            notes.append(MixingNote("derived", f"{entry.name}{where}: {value:g} mM in the mixture -- {how}.",
                                    entry.quote, entry.source))
    return notes
