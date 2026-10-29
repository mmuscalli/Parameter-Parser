"""
Sealed batch experiments start at atmospheric pressure unless the paper says otherwise (Mickey,
2026-10-29): a Batch row whose vessel was sealed (the conditions step's `vessel_sealed`) and that has no
initial_pressure_bar gets 1 bar (1.01325 rounds to it at the dataset's precision), marked assumed in its
provenance and listed in ONE flag for the paper (most rows of an experiment meet the condition).

Not done (yet): sampled_pressure_bar at temperature -- Raoult's law from the solution's composition, the
volumes and the vapour pressure of water at the reaction temperature.
"""
from __future__ import annotations
from typing import List

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value
from parameter_extractor.schemas.row_schema import CellSource

ATMOSPHERIC_BAR = 1.0


def assume_atmospheric_start(rows, paper_wide_sealed: str = "") -> List[str]:
    """Fill initial_pressure_bar = 1 bar on sealed Batch rows without one; returns the flag message(s).
    `paper_wide_sealed`: the paper-wide answer, for rows that don't carry their own (digitized figures)."""
    filled = []
    for row in rows:
        values = row_to_template_dict(row)
        if (str(values.get("experiment_type") or "").lower() == "batch"
                and str(values.get("vessel_sealed") or paper_wide_sealed or "").lower() == "sealed"
                and values.get("initial_pressure_bar") in (None, "")):
            sealed = row.provenance.get("vessel_sealed")
            set_row_value(row, "initial_pressure_bar", ATMOSPHERIC_BAR, CellSource(
                origin="assumed: sealed batch experiment, atmospheric pressure at the start",
                quote=sealed.quote if sealed else "", source=sealed.source if sealed else "",
                confidence="low"))
            filled.append(row)
    if not filled:
        return []
    sets = sorted({r.set_id for r in filled})
    return [f"initial_pressure_bar: {len(filled)} row(s) in {len(sets)} set(s) are sealed batch experiments with no "
            f"starting pressure stated, so 1 bar (atmospheric) was assumed "
            f"(sets {', '.join(sets[:8])}{' ...' if len(sets) > 8 else ''}). Correct it if the paper gives the "
            f"pressure elsewhere, or if the vessel was evacuated or pressurised before sealing."]
