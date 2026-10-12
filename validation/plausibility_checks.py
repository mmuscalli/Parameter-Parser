"""
Cheap, always-on sanity checks -- these don't require a gold-standard answer
key, just physical/chemical plausibility. Distinct from gold_standard_eval.py
(which DOES require a known-correct answer and is toggled off until that
exists). Returns a list of human-readable flags; never raises or silently
corrects a value.
"""
from __future__ import annotations
from typing import List
from schemas.row_schema import ExtractedRow


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

    return flags
