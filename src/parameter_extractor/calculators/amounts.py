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
Notes use calculators/mixing.MixingNote, so they become derived_value / not_calculated /
conflicting_values flags, grouped per set.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from parameter_extractor.calculators.mixing import MixingNote, _sig
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.units import _UNITS, canonical_unit, convert

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
        if (s.set_label and not s.sample_label and s.concentration_value is not None and not s.derived
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
        if s.concentration_value is None or s.concentration_basis == "stock" or s.derived:
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
