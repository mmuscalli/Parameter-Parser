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
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator
from .common import Extracted

ExperimentType = Literal["Batch", "Flowthrough"]  # POLO's ExperimentType enum
OverridableField = Literal[
    "initial_pressure_bar", "initial_temperature_C", "sampled_temperature_C", "initial_pH",
]


class SetOverride(BaseModel):
    """One per-set value. A list of these rather than a {set_label: {field: value}}
    dict because the API's structured outputs can't express free-form dict keys --
    a dict field comes back as an always-empty object."""
    set_label: str = Field(description="Exact set_label string from the structure plan.")
    field_name: OverridableField
    value: float


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

    per_set_overrides: List[SetOverride] = Field(
        default_factory=list,
        description="One entry per (set, field) for fields that vary by experiment set "
                    "rather than being constant across the whole paper, e.g. "
                    "{set_label: 'Na+ 3.33 mol dm-3, 81 C', field_name: 'initial_temperature_C', "
                    "value: 81.0}",
    )

    @field_validator("per_set_overrides", mode="before")
    @classmethod
    def _accept_legacy_dict(cls, v):
        # runs/eder1994/build_manual_demo.py predates the list form and passes a dict
        if isinstance(v, dict):
            return [{"set_label": label, "field_name": f, "value": val}
                    for label, fields in v.items() for f, val in fields.items()]
        return v

    def overrides_for(self, set_label: str) -> Dict[str, float]:
        return {o.field_name: o.value for o in self.per_set_overrides if o.set_label == set_label}
