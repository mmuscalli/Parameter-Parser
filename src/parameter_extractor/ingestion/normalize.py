"""
Deterministic clean-up of the chemistry step's output before rows are built:

  - species names matched onto the controlled vocabulary (names.py):
    "sodium chloride" -> NaCl, "diglycine" -> 2peptide_Gly, "Ca2+" -> Ca+2
  - every concentration recomputed from the value and unit AS PRINTED
    (units.py): a missing mM value is filled in when the unit is unambiguous,
    and if the model's own mM disagrees with the arithmetic, the recomputed
    value is used and the discrepancy flagged.

Each change is written into the entry's conversion_note, which ends up in the
value's provenance (hover text / observations.csv). Running it twice is
harmless.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List

from parameter_extractor.names import match_species
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.units import canonical_unit, convert

RELATIVE_TOLERANCE = 0.01


@dataclass
class NormalizationNote:
    kind: str          # "name_matched", "unit_filled", "unit_corrected"
    message: str
    quote: str = ""
    source: str = ""


def _append_note(entry, text: str) -> None:
    entry.conversion_note = f"{entry.conversion_note}; {text}" if entry.conversion_note else text


def normalize_chemistry(chemistry: ChemistryExtraction) -> List[NormalizationNote]:
    notes: List[NormalizationNote] = []
    for s in chemistry.solutes:
        matched = match_species(s.name)
        if matched and matched[0] != s.name:
            original, (canonical, how) = s.name, matched
            s.name = canonical
            _append_note(s, f"name matched: '{original}' -> {canonical} ({how})")
            notes.append(NormalizationNote("name_matched", f"'{original}' -> {canonical} ({how})",
                                           s.quote or "", s.source or ""))

        unit = canonical_unit(s.concentration_unit_raw) if s.concentration_unit_raw else None
        if s.concentration_value is None or unit is None:
            continue
        computed = convert(s.concentration_value, unit, "mM")
        if computed is None:                       # not a concentration unit (e.g. %, mass)
            continue
        computed = float(f"{computed:.10g}")
        printed = f"{s.concentration_value:g} {s.concentration_unit_raw}"
        if s.concentration_mM is None:
            s.concentration_mM = computed
            _append_note(s, f"mM computed by the pipeline from {printed}")
            notes.append(NormalizationNote("unit_filled", f"{s.name}: {printed} -> {computed:g} mM",
                                           s.quote or "", s.source or ""))
        elif abs(s.concentration_mM - computed) > RELATIVE_TOLERANCE * max(abs(computed), 1e-12):
            model_value = s.concentration_mM
            s.concentration_mM = computed
            _append_note(s, f"mM corrected by the pipeline: {printed} = {computed:g} mM "
                            f"(the model had {model_value:g} mM)")
            notes.append(NormalizationNote(
                "unit_corrected",
                f"{s.name}{' (set ' + repr(s.set_label) + ')' if s.set_label else ''}: printed as {printed}, "
                f"which is {computed:g} mM -- the extraction had {model_value:g} mM. The recomputed value "
                f"was used; please check.", s.quote or "", s.source or ""))
    return notes
