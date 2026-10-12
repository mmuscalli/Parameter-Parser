"""Stage 3b: experimental methodology -- the fields POLO's variable mapping
marks as 'direct' (paper-stated, not derived): experiment_type, vessel
material, solvent, headspace gas, initial/sampled temperature and pressure,
plus analysis_method, which the mapping flags as a current ontology gap
(no_analogue_gap) -- still worth capturing in the database even though it
has nowhere to map to in POLO yet.

One Methodology record is shared across all of a paper's experiment sets
UNLESS a field genuinely varies by set (e.g. sampled_temperature_C sometimes
differs slightly per condition) -- see `per_set_overrides`.
"""
from __future__ import annotations
from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field
from .common import Extracted

ExperimentType = Literal["Batch", "Flowthrough"]  # POLO's ExperimentType enum


class Methodology(BaseModel):
    paper_id: str
    experiment_type: Extracted[ExperimentType]
    solution_type: Extracted[Literal["Wet", "Dry"]]
    vessel_material: Extracted[str]
    solvent_name: Extracted[str]
    analysis_method: Extracted[str] = Field(
        description="e.g. 'HPLC'. Not currently a POLO property (ontology gap) -- "
                    "capture it anyway; it's useful metadata and a candidate for a "
                    "future ontology extension."
    )
    headspace_gas: Extracted[Optional[str]]
    initial_pressure_bar: Extracted[Optional[float]]
    initial_temperature_C: Extracted[Optional[float]]
    sampled_temperature_C: Extracted[Optional[float]]
    initial_pH: Extracted[Optional[float]]

    per_set_overrides: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="set_label -> {field_name: value} for fields that vary by experiment "
                    "set rather than being constant across the whole paper, e.g. "
                    "{'Na+ 3.33 mol dm-3, 81 C': {'initial_temperature_C': 81.0}}",
    )
