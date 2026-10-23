"""
Results named without an amount, and concentrations from amounts (Mickey, 2026-10-23).

Chen2007 lists products as observed with no amount (Table 3: "FF, FA, AF ...") and
says "no product was detected" for some entries, and gives every reactant as an
amount ("carboxylic acid (3 mmol)") in a stated volume of water. So:
- a 'sampled' species the chemistry step marks `detection` 'detected' is written as
  the text "detected" (flatten_to_template._solute_value); 'not detected' becomes 0;
- an amount (mol / mmol / µmol / nmol) becomes mM = amount / reaction volume, with the
  volume from the experimental-conditions stage (solvent_volume_mL, per set or sample).
  The value is marked calculated (origin "calculated"), the amount and volume named in
  its provenance. Never guesses: no volume for that set (or differing volumes within it)
  -> nothing calculated, a note says why.
- a total shared by several species in a stated ratio ("1:1 ratio of each component,
  total 1 mmol" -> `mixture_totals`) is split into each species' value (split_totals),
  before the amount -> mM step, so the shares are converted too. A value the paper also
  states for that species is kept and checked against its share instead.
Notes use calculators/mixing.MixingNote, so they become derived_value / not_calculated /
conflicting_values flags, grouped per set.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from parameter_extractor.calculators.mixing import MixingNote, _sig
from parameter_extractor.calculators.mixing import RATIO_TOLERANCE, _key
from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
from parameter_extractor.units import _UNITS, canonical_unit, convert, parse_quantity

VOLUME_COLUMN = "solvent_volume_mL"
TOLERANCE = 0.01          # a model-calculated mM further off than this is replaced (and flagged)

# (set_label, sample_label) -> (volume in mL, where it came from); sample '' = the whole set
Volumes = Dict[Tuple[str, str], Tuple[float, str]]


def apply_detection(chemistry: ChemistryExtraction) -> List[MixingNote]:
    """'not detected' -> 0 (in the entry's own unit, and 0 mM unless it's a % yield);
    'detected' stays without a number. One note for each kind, listing the species."""
    zero, detected = [], []
    for s in chemistry.solutes:
        if s.role != "sampled" or s.concentration_value is not None or s.concentration_mM is not None:
            continue
        where = f"{s.name} ({s.sample_label or s.set_label or 'every set'})"
        if s.detection == "not detected":
            s.concentration_value = 0.0
            if "%" not in (s.concentration_unit_raw or ""):
                s.concentration_mM = 0.0
            s.conversion_note = "reported as not detected -> 0"
            zero.append(where)
        elif s.detection == "detected":
            s.conversion_note = "reported as detected, no amount given"
            detected.append(where)
    notes = []
    if zero:
        notes.append(MixingNote("derived", f"{len(zero)} result(s) the paper reports as not detected were "
                                           f"written as 0: {'; '.join(zero)[:600]}"))
    if detected:
        notes.append(MixingNote("derived", f"{len(detected)} result(s) the paper lists as detected without an "
                                           f"amount were written as 'detected': {'; '.join(detected)[:600]}"))
    return notes


def _own_value(s) -> bool:
    """A value to convert: stated, or a share of a stated total (not a mixing/ratio result)."""
    return not s.derived or s.calculated_from == "total"


def split_totals(chemistry: ChemistryExtraction, set_labels: List[str]) -> List[MixingNote]:
    """Each mixture total -> its species' shares (value x share / sum of shares), in the total's
    own unit; concentrations also in mM. Entries are added (or an empty one filled), marked
    calculated (calculated_from "total"); one note per total."""
    notes: List[MixingNote] = []
    for t in chemistry.mixture_totals:
        quantity = parse_quantity(t.total)
        parts = [p for p in t.parts if p.name.strip()]
        shares = sum(p.share for p in parts)
        names = ", ".join(f"{p.name} {p.share:g}" for p in parts)
        dimension = _UNITS.get(quantity[1], ("",))[0] if quantity else ""
        if not parts or shares <= 0 or any(p.share <= 0 for p in parts) or dimension not in ("amount",
                                                                                              "concentration"):
            why = ("the total isn't a single amount or concentration" if dimension not in ("amount", "concentration")
                   else "the shares aren't positive numbers")
            notes.append(MixingNote("not_derived", f"Total '{t.total}' for {names or 'no species'} not split -- "
                                                   f"{why}.", t.quote, t.source))
            continue
        value, unit = quantity
        targets = [(t.set_label, t.sample_label)] if t.set_label else [(label, t.sample_label) for label in set_labels]
        done = []
        for set_label, sample_label in targets:
            for p in parts:
                share = value * p.share / shares
                printed = f"{share:g} {unit}"
                how = (f"calculated: {p.share:g}/{shares:g} of the stated total {t.total} "
                       f"({', '.join(f'{q.name}' for q in parts)})")
                entry = next((s for s in chemistry.solutes if s.role == "initial" and s.concentration_basis == "mixture"
                              and _key(s.name) == _key(p.name) and (s.set_label or "") == set_label
                              and (s.sample_label or "") == sample_label), None)
                if entry is not None and entry.concentration_value is not None:
                    stated = convert(entry.concentration_value, canonical_unit(entry.concentration_unit_raw or "") or "",
                                     unit)
                    if stated is not None and abs(stated - share) > RATIO_TOLERANCE * share:
                        notes.append(MixingNote(
                            "mismatch", f"{p.name} ({sample_label or set_label or 'every set'}): the paper gives "
                            f"{entry.concentration_value:g} {entry.concentration_unit_raw}, but its share of the "
                            f"total {t.total} is {printed}. The stated value was kept; please check.",
                            t.quote, t.source))
                    continue
                if entry is None:
                    like = next((s for s in chemistry.solutes if _key(s.name) == _key(p.name)), None)
                    entry = SoluteEntry(name=p.name, phase=like.phase if like else "aq", role="initial",
                                        set_label=set_label or None, sample_label=sample_label or None,
                                        concentration_value=None, concentration_unit_raw=None,
                                        quote=t.quote, source=t.source, confidence="high")
                    chemistry.solutes.append(entry)
                entry.concentration_value, entry.concentration_unit_raw = _sig(share), unit
                entry.derived, entry.calculated_from = True, "total"
                entry.conversion_note = how
                if dimension == "concentration":
                    entry.exact_mM = convert(share, unit, "mM")
                    entry.concentration_mM = _sig(entry.exact_mM)
                done.append(f"{p.name} {printed}" + (f" ({sample_label})" if sample_label else ""))
        if done:
            notes.append(MixingNote("derived", f"Total {t.total} split in the ratio {names} "
                                               f"({t.set_label or 'every set'}): {'; '.join(done)[:600]}",
                                    t.quote, t.source))
    return notes


def _amount_mmol(value: float, unit_text: Optional[str]) -> Optional[float]:
    unit = canonical_unit(unit_text) if unit_text else None
    if unit is None or _UNITS.get(unit, ("",))[0] != "amount":
        return None
    return convert(value, unit, "mmol")


def _volume_for(volumes: Volumes, set_labels: List[str], set_label: Optional[str],
                sample_label: Optional[str]) -> Tuple[Optional[Tuple[float, str]], str]:
    """(volume, why not): a sample's own volume, else its set's; a set-wide entry needs one
    volume for the set; a paper-wide entry (set None) one volume across every set."""
    if set_label is None:
        found = {_volume_for(volumes, set_labels, label, None)[0] for label in set_labels}
        if len(found) == 1 and None not in found:
            return found.pop(), ""
        return None, "the reaction volume isn't the same in every set" if len(found) > 1 else \
            "no reaction volume (solvent_volume_mL) was found"
    if sample_label and (set_label, sample_label) in volumes:
        return volumes[(set_label, sample_label)], ""
    if (set_label, "") in volumes:
        return volumes[(set_label, "")], ""
    per_sample = {v for (label, smp), v in volumes.items() if label == set_label and smp}
    if len(per_sample) == 1:
        return per_sample.pop(), ""
    if sample_label and per_sample:
        return None, "no reaction volume (solvent_volume_mL) was found for that sample"
    return None, ("the set's samples have different reaction volumes" if per_sample else
                  "no reaction volume (solvent_volume_mL) was found for this set")


def _split_by_sample(chemistry: ChemistryExtraction, volumes: Volumes, samples: Dict[str, List[str]]) -> None:
    """A set-wide amount in a set whose samples have different volumes (Chen2007 Table 1: entries
    1-4 in 30 mL, 5-6 in 50 mL) becomes one entry per sample; a sample without a volume keeps the
    amount uncalculated (and noted)."""
    out = []
    for s in chemistry.solutes:
        labels = samples.get(s.set_label or "", [])
        if (s.set_label and not s.sample_label and s.concentration_value is not None and _own_value(s)
                and s.concentration_basis != "stock" and (s.set_label, "") not in volumes
                and _amount_mmol(s.concentration_value, s.concentration_unit_raw) is not None
                and len({volumes.get((s.set_label, smp), (None,))[0] for smp in labels}) > 1):
            out += [s.model_copy(update={"sample_label": smp}) for smp in labels]
        else:
            out.append(s)
    chemistry.solutes = out


def derive_from_amounts(chemistry: ChemistryExtraction, volumes: Volumes,
                        samples: Dict[str, List[str]]) -> List[MixingNote]:
    """Amounts -> mM in the reaction volume (see the module docstring). `samples`: each set's
    sample labels, in order."""
    set_labels = list(samples)
    _split_by_sample(chemistry, volumes, samples)
    done: Dict[str, List[str]] = {}
    missing: Dict[str, List[str]] = {}
    notes: List[MixingNote] = []
    for s in chemistry.solutes:
        if s.concentration_value is None or s.concentration_basis == "stock" or not _own_value(s):
            continue
        mmol = _amount_mmol(s.concentration_value, s.concentration_unit_raw)
        if mmol is None:
            continue
        where = s.sample_label or s.set_label or "every set"
        volume, why = _volume_for(volumes, set_labels, s.set_label, s.sample_label)
        if volume is None:
            missing.setdefault(why, []).append(f"{s.name} ({where})")
            continue
        mL, origin = volume
        exact = mmol / mL * 1000.0
        value = _sig(exact)
        printed = f"{s.concentration_value:g} {s.concentration_unit_raw}"
        if s.concentration_mM is not None and abs(s.concentration_mM - exact) > TOLERANCE * max(exact, 1e-12):
            notes.append(MixingNote("mismatch", f"{s.name} ({where}): {printed} in {mL:g} mL is {value:g} mM -- "
                                                f"the extraction had {s.concentration_mM:g} mM. The calculated "
                                                f"value was used; please check.", s.quote, s.source))
        s.concentration_mM, s.exact_mM = value, exact
        s.derived, s.calculated_from = True, "amount"
        how = f"calculated: {printed} in {mL:g} mL reaction volume ({origin})"
        s.conversion_note = f"{s.conversion_note}; {how}" if s.conversion_note else how
        done.setdefault(f"{s.set_label or 'every set'}", []).append(
            f"{s.name} {printed} / {mL:g} mL -> {value:g} mM" + (f" ({s.sample_label})" if s.sample_label else ""))
    for where, parts in done.items():
        notes.append(MixingNote("derived", f"mM calculated from amounts and the reaction volume, {where}: "
                                           f"{'; '.join(parts)[:600]}"))
    for why, names in missing.items():
        notes.append(MixingNote("not_derived", f"Amounts not converted to mM -- {why}: {'; '.join(names)[:600]}"))
    return notes
