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

Molar ratios (derive_from_ratios): when a paper gives "3 : cytosine = 1:2"
instead of the cytosine concentration, the amounts in one mixture are in that
ratio, so C_cytosine = C_3 x 2/1 (both in the mixture). If the species'
solution volume is known, its stock concentration follows too (C_mix x
V_total / V_added). Where the paper also states the value, the ratio is used
as a check: a disagreement is flagged, the stated value kept.

Never guesses: a mixture value is only calculated when the species' own
solution and EVERY solution in that mixture have a volume that parses to a
volume unit. Otherwise nothing is added and a note says why. If the paper
itself gives the mixture concentration, that's used instead.
Running it twice is harmless (earlier derived entries are replaced).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from parameter_extractor.names import vocabulary
from parameter_extractor.schemas.chemistry import AddedSolution, ChemistryExtraction, MolarRatio, SoluteEntry
from parameter_extractor.units import convert, parse_quantity

SIGNIFICANT_FIGURES = 6        # enough that chained calculations land back on printed values
RATIO_TOLERANCE = 0.02       # relative difference above which a stated value and a ratio disagree


@dataclass
class MixingNote:
    kind: str           # "derived" (a value was calculated), "not_derived" (it couldn't be),
                        # "mismatch" (a stated value disagrees with the paper's ratio)
    message: str
    quote: str = ""
    source: str = ""
    species: str = ""   # "derived" notes: grouped into one flag per species (pipeline.grouped_mixing_flags)
    short: str = ""     # that note's part of the grouped flag: "<set>: <value> mM"


def _key(text: str) -> str:
    return " ".join(text.lower().split())


def _sig(value: float) -> float:
    return float(f"{value:.{SIGNIFICANT_FIGURES}g}")


def _volume_uL(text: str) -> Optional[float]:
    q = parse_quantity(text or "")
    return convert(q[0], q[1], "µL") if q else None


def solutions_for(chemistry: ChemistryExtraction, set_label: Optional[str],
                  sample_label: Optional[str] = None) -> List[AddedSolution]:
    """The solutions combined for one set (and sample): the paper-wide ones ('') with any set-specific
    entry of the same name taking their place, and a sample-specific one taking that one's."""
    by_name: Dict[str, AddedSolution] = {}
    for sol in chemistry.added_solutions:
        if not sol.set_label and not sol.sample_label:
            by_name.setdefault(_key(sol.solution), sol)
    for sol in chemistry.added_solutions:
        if set_label and sol.set_label == set_label and not sol.sample_label:
            by_name[_key(sol.solution)] = sol
    for sol in chemistry.added_solutions:
        if sample_label and sol.sample_label == sample_label and sol.set_label in ("", set_label):
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
    value = entry.mM_for_calculation * own_volume / total
    parts = " + ".join(f"{s.solution} {v:g} µL" for s, v in volumes)
    return value, (f"calculated by the pipeline from the stock concentration: {entry.mM_for_calculation:g} mM "
                   f"x {own_volume:g} µL / {total:g} µL total ({parts})")


def _missing_solutions(chemistry: ChemistryExtraction, set_label: Optional[str],
                       sample_label: Optional[str] = None) -> List[str]:
    """Solutions listed for some other set but not for this one: the total volume would be short.
    (kim2019 live run, 2026-10-26: the 20 µL nucleobase solution listed only for the 1:1 sets -- its
    concentration was stated for 1:1 -- made the 1:2 / 1:3 mixtures 13 µL instead of 33 µL.)"""
    present = {_key(s.solution) for s in solutions_for(chemistry, set_label, sample_label)}
    elsewhere = {}
    for sol in chemistry.added_solutions:
        other = (sol.set_label and sol.set_label != set_label) or (sol.sample_label and sol.sample_label != sample_label)
        if other and _key(sol.solution) not in present:
            elsewhere.setdefault(_key(sol.solution), sol.solution)
    return sorted(elsewhere.values())


def volumes_as_concentrations(chemistry: ChemistryExtraction) -> List[MixingNote]:
    """A starting 'concentration' given in a VOLUME unit for a species that also has a stock solution
    (kim2017 live run: ammonium formate '2.5 µL' per sample) is the volume of that stock added: moved to
    added_solutions for its set and sample, with a note."""
    stocks = {_key(s.name): s for s in chemistry.solutes
              if s.role == "initial" and s.concentration_basis == "stock" and s.stock_solution}
    kept, notes = [], []
    for s in chemistry.solutes:
        q = parse_quantity(f"{s.concentration_value} {s.concentration_unit_raw}") \
            if s.concentration_value is not None and s.concentration_unit_raw else None
        stock = stocks.get(_key(s.name))
        if (s.role == "initial" and s.concentration_basis == "mixture" and q and stock
                and convert(q[0], q[1], "µL") is not None):
            chemistry.added_solutions.append(AddedSolution(
                set_label=s.set_label or "", sample_label=s.sample_label or "", solution=stock.stock_solution,
                volume=f"{s.concentration_value:g} {s.concentration_unit_raw}", quote=s.quote, source=s.source))
            notes.append(MixingNote(
                "repaired", f"{s.name}: '{s.concentration_value:g} {s.concentration_unit_raw}' is a volume, not a "
                f"concentration -- recorded as the volume of '{stock.stock_solution}' added", s.quote, s.source,
                species=s.name, short=" / ".join(x for x in (s.set_label, s.sample_label) if x)
                + f": {s.concentration_value:g} {s.concentration_unit_raw}"))
        else:
            kept.append(s)
    chemistry.solutes = kept
    return notes


def derive_mixture_concentrations(chemistry: ChemistryExtraction, set_labels: List[str],
                                  samples_by_set: Optional[Dict[str, List[str]]] = None) -> List[MixingNote]:
    """Adds a derived mixture entry for each stock concentration that can be
    calculated. `set_labels`: the structure plan's sets, for a paper-wide stock
    value whose mixture differs by set."""
    chemistry.solutes = [s for s in chemistry.solutes if not s.derived or s.calculated_from]   # amounts.py's stay
    stated = {(s.set_label, s.sample_label, s.name) for s in chemistry.solutes
              if s.role == "initial" and s.concentration_basis == "mixture"}
    set_specific = any(sol.set_label for sol in chemistry.added_solutions)
    notes: List[MixingNote] = []
    for entry in [s for s in chemistry.solutes if s.role == "initial" and s.concentration_basis == "stock"]:
        if entry.concentration_mM is None:
            notes.append(MixingNote("not_derived", f"{entry.name}: stock concentration has no mM value, so the "
                                    f"mixture concentration wasn't calculated.", entry.quote, entry.source))
            continue
        # a paper-wide stock value gets one mixture value per set when the mixtures differ by set -- and
        # per sample when the volumes differ between a set's samples
        labels = [entry.set_label] if entry.set_label or not set_specific else list(set_labels)
        targets = []
        for label in labels:
            samples = (samples_by_set or {}).get(label, [])
            specific = {sol.sample_label for sol in chemistry.added_solutions
                        if sol.sample_label and sol.set_label in ("", label)}
            per_sample = [smp for smp in samples if smp in specific] if samples else sorted(specific)
            if entry.sample_label:
                targets.append((label, entry.sample_label))
            else:
                targets += [(label, smp) for smp in per_sample] or [(label, None)]
        for label, sample in targets:
            if (label, sample, entry.name) in stated or (None, sample, entry.name) in stated:
                continue                       # the paper gives the mixture value itself
            missing = _missing_solutions(chemistry, label, sample)
            if missing:
                value, how = None, (f"{', '.join(missing)} is listed for other sets but not for this one, so "
                                    f"the total volume isn't known")
            else:
                value, how = _mixture(entry, solutions_for(chemistry, label, sample))
            where = (f" (set '{label}'" + (f", sample '{sample}'" if sample else "") + ")") if label else ""
            if value is None:
                notes.append(MixingNote("not_derived", f"{entry.name}{where}: mixture concentration not "
                                        f"calculated -- {how}. Only the stock value is recorded.",
                                        entry.quote, entry.source))
                continue
            exact, value = value, _sig(value)
            derived = entry.model_copy(update=dict(
                set_label=label, sample_label=sample, concentration_basis="mixture", stock_solution="", concentration_value=value,
                concentration_unit_raw="mM", concentration_mM=value, conversion_note=how, derived=True,
                exact_mM=exact))
            chemistry.solutes.append(derived)
            notes.append(MixingNote("derived", f"{entry.name}{where}: {value:g} mM in the mixture -- {how}.",
                                    entry.quote, entry.source, species=entry.name,
                                    short=f"{label or 'every set'}" + (f" / {sample}" if sample else "")
                                    + f": {value:g} mM"))
    return notes


def _initial(chemistry: ChemistryExtraction, name: str, set_label: str, basis: str) -> Optional[SoluteEntry]:
    """The set-wide starting value of a species in a set (set-specific first, then paper-wide)."""
    found = [s for s in chemistry.solutes if s.role == "initial" and s.concentration_basis == basis
             and _key(s.name) == _key(name) and not s.sample_label and s.concentration_mM is not None
             and s.set_label in (set_label, None)]
    return min(found, key=lambda s: s.set_label is None) if found else None


def _ratio_text(r: MolarRatio) -> str:
    return f"{r.reference_species} : {r.species} = {r.reference_parts:g}:{r.species_parts:g}"


def derive_from_ratios(chemistry: ChemistryExtraction, set_labels: List[str]) -> List[MixingNote]:
    """Run after derive_mixture_concentrations (it needs the known side's mixture
    value). For each ratio and set: if one side's mixture concentration is known and
    the other isn't, the other is calculated (either way round), plus its stock
    concentration where volumes allow; if both are known, the ratio checks them."""
    vocab = set(vocabulary())
    notes: List[MixingNote] = []
    for r in chemistry.molar_ratios:
        if r.species_parts <= 0 or r.reference_parts <= 0 or _key(r.species) == _key(r.reference_species):
            continue
        flipped = r.model_copy(update=dict(species=r.reference_species, reference_species=r.species,
                                           species_parts=r.reference_parts, reference_parts=r.species_parts))
        for label in ([r.set_label] if r.set_label else list(set_labels)):
            where = f" (set '{label}')" if label else ""
            ref = _initial(chemistry, r.reference_species, label, "mixture")
            other = _initial(chemistry, r.species, label, "mixture")
            if ref is not None and other is not None:
                expected = ref.mM_for_calculation * r.species_parts / r.reference_parts
                if abs(other.mM_for_calculation - expected) > RATIO_TOLERANCE * expected:
                    notes.append(MixingNote(
                        "mismatch", f"{r.species}{where}: {other.concentration_mM:g} mM in the mixture, but the "
                        f"paper's ratio {_ratio_text(r)} with {ref.name} at {ref.concentration_mM:g} mM gives "
                        f"{_sig(expected):g} mM. The values were kept as they are; please check.", r.quote, r.source))
            elif ref is not None:
                notes += _derive(chemistry, r, label, ref, where, vocab, r)
            elif other is not None:
                notes += _derive(chemistry, flipped, label, other, where, vocab, r)
            else:
                notes.append(MixingNote("not_derived", f"{_ratio_text(r)}{where}: no concentration of either "
                                        f"species in the mixture, so neither was calculated from the ratio.",
                                        r.quote, r.source))
    return notes


def _derive(chemistry, r: MolarRatio, label: str, ref: SoluteEntry, where: str, vocab, as_printed: MolarRatio):
    """r.species from r.reference_species (known: `ref`) in one set."""
    exact = ref.mM_for_calculation * r.species_parts / r.reference_parts
    value = _sig(exact)
    how = (f"calculated by the pipeline from the molar ratio {_ratio_text(as_printed)} and {ref.name} "
           f"{ref.concentration_mM:g} mM in the mixture: {ref.concentration_mM:g} x "
           f"{r.species_parts:g}/{r.reference_parts:g}")
    chemistry.solutes.append(SoluteEntry(
        name=r.species, in_controlled_vocab=r.species in vocab, phase=ref.phase, role="initial",
        set_label=label, concentration_value=value, concentration_unit_raw="mM", concentration_mM=value,
        conversion_note=how, quote=r.quote, source=r.source, confidence=ref.confidence, derived=True,
        exact_mM=exact))
    notes = [MixingNote("derived", f"{r.species}{where}: {value:g} mM in the mixture -- {how}.", r.quote, r.source)]
    return notes + _stock_from_mixture(chemistry, r, label, exact, where, as_printed)


def _stock_from_mixture(chemistry, r: MolarRatio, label: str, mixture_mM: float, where: str,
                        as_printed: MolarRatio) -> List[MixingNote]:
    """The stock concentration that gives `mixture_mM`, if the species' solution and
    every volume in the mixture are known (the solution is the one its stated
    stock values were in, in any set)."""
    if _initial(chemistry, r.species, label, "stock") is not None:
        return []
    solution = next((s.stock_solution for s in chemistry.solutes if s.concentration_basis == "stock"
                     and _key(s.name) == _key(r.species) and s.stock_solution), "")
    if not solution:
        return []
    if _missing_solutions(chemistry, label):
        return []                                   # the total volume isn't known for this set
    solutions = solutions_for(chemistry, label)
    volumes = {_key(s.solution): _volume_uL(s.volume) for s in solutions}
    own = volumes.get(_key(solution))
    if own is None or not own or any(v is None for v in volumes.values()):
        return []
    total = sum(volumes.values())
    exact = mixture_mM * total / own
    value = _sig(exact)
    template = next(s for s in chemistry.solutes if s.concentration_basis == "stock" and _key(s.name) == _key(r.species))
    how = (f"calculated by the pipeline: {_sig(mixture_mM):g} mM in the mixture (from the molar ratio "
           f"{_ratio_text(as_printed)}) x {total:g} µL total / {own:g} µL of {solution}")
    chemistry.solutes.append(template.model_copy(update=dict(
        set_label=label, sample_label=None, concentration_value=value, concentration_unit_raw="mM",
        concentration_mM=value, conversion_note=how, quote=r.quote, source=r.source, derived=True, exact_mM=exact)))
    return [MixingNote("derived", f"{r.species}{where}: {value:g} mM stock solution -- {how}.", r.quote, r.source)]
