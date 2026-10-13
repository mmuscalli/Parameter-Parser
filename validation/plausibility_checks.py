"""
Cheap, always-on sanity checks -- these don't require a gold-standard answer
key, just physical/chemical plausibility. Distinct from gold_standard_eval.py
(which DOES require a known-correct answer and is toggled off until that
exists). Returns a list of human-readable flags; never raises or silently
corrects a value.
"""
from __future__ import annotations
from typing import List
from config import settings
from schemas.chemistry import ChemistryExtraction
from schemas.common import confidence_below
from schemas.methodology import Methodology
from schemas.row_schema import ExtractedRow

_METHOD_FIELDS = (
    "experiment_type", "solution_type", "vessel_material", "solvent_name", "analysis_method",
    "headspace_gas", "initial_pressure_bar", "initial_temperature_C", "sampled_temperature_C",
    "initial_pH",
)


def _drop_suffix(confidence) -> str:
    if confidence_below(confidence, settings.CONFIDENCE_DROP_BELOW):
        return f" -- left BLANK in the CSV (CONFIDENCE_DROP_BELOW={settings.CONFIDENCE_DROP_BELOW!r})"
    return ""


def check_row(row: ExtractedRow) -> List[str]:
    flags: List[str] = []

    if row.initial_temperature_C is not None and not (-20 <= row.initial_temperature_C <= 400):
        flags.append(f"initial_temperature_C={row.initial_temperature_C} is outside a plausible "
                      f"range for an aqueous-phase prebiotic experiment -- check extraction.")

    if row.sampled_temperature_C is not None and not (-20 <= row.sampled_temperature_C <= 400):
        flags.append(f"sampled_temperature_C={row.sampled_temperature_C} is outside a plausible range.")

    if row.initial_pressure_bar is not None and row.initial_pressure_bar < 0:
        flags.append("initial_pressure_bar is negative -- not physically possible.")

    for pct_field in ("sampled_2peptide_Gly_pct_yield", "sampled_3peptide_Gly_pct_yield"):
        val = getattr(row, pct_field)
        if val is not None and not (0 <= val <= 100):
            flags.append(f"{pct_field}={val} is outside 0-100%.")

    for name, conc in row.species_mM.items():
        if conc is not None and conc < 0:
            flags.append(f"{name}={conc} mM is negative -- not physically possible.")

    if row.duration_hr is not None and row.duration_hr < 0:
        flags.append("duration_hr is negative.")

    if row.extraction_confidence and confidence_below(row.extraction_confidence,
                                                      settings.CONFIDENCE_FLAG_BELOW):
        flags.append(f"lowest confidence among this row's measured values is "
                     f"'{row.extraction_confidence}' -- verify against the paper"
                     f"{_drop_suffix(row.extraction_confidence)}.")

    return flags


def check_extraction(methodology: Methodology, chemistry: ChemistryExtraction) -> List[str]:
    """Paper-level flags: problems with values that apply to many rows at once
    (paper-wide methodology, initial compositions), reported once here rather
    than repeated on every row they affect."""
    flags: List[str] = []

    for name in sorted(chemistry.ambiguous_paper_wide_species()):
        entries = [s for s in chemistry.solutes
                   if s.name == name and s.role == "initial" and s.set_label is None]
        for s in entries:
            flags.append(
                f"{name} = {s.concentration_value} {s.concentration_unit_raw} was extracted as "
                f"paper-wide (no set_label), but {name} is also given for specific sets -- most "
                f"likely a set-specific value missing its set_label. NOT applied to any row; "
                f"assign it to the right set by hand. Quote: {s.quote!r} ({s.source})."
            )

    for field in _METHOD_FIELDS:
        f = getattr(methodology, field)
        if f.value is not None and confidence_below(f.confidence, settings.CONFIDENCE_FLAG_BELOW):
            flags.append(f"methodology.{field} = {f.value!r} has confidence '{f.confidence}' "
                         f"(applies to every row){_drop_suffix(f.confidence)}. "
                         f"Quote: {f.quote!r} ({f.source}).")

    for s in chemistry.solutes:
        if s.role == "initial" and confidence_below(s.confidence, settings.CONFIDENCE_FLAG_BELOW):
            where = f"set {s.set_label!r}" if s.set_label else "every set"
            flags.append(f"initial {s.name} = {s.concentration_value} {s.concentration_unit_raw} "
                         f"({where}) has confidence '{s.confidence}'{_drop_suffix(s.confidence)}. "
                         f"Quote: {s.quote!r} ({s.source}).")

    return flags
