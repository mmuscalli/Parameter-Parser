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
from .common import Basis, Extracted

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
    basis: Basis = Field(default="stated", description="'stated' in the paper; 'derived' by arithmetic "
                                                       "from stated values; 'assumed' if not stated.")
    confidence: Literal["high", "medium", "low"] = "high"
    quote: str = Field(default="", description="Supporting snippet from the paper.")
    source: str = ""


class OtherParameter(BaseModel):
    """A condition or parameter the fixed fields don't cover (open-ended, so
    papers aren't limited to what PaperDataTemplate anticipated).

    Deliberately flat -- one text `value` rather than number/text/unit fields:
    every optional field multiplies the structured-output grammar, and adding
    three of them pushed the Methodology schema over the API's grammar size
    limit (400 "compiled grammar is too large"). Splitting value and unit is
    left to the review step."""
    name: str = Field(description="Short descriptive name, e.g. 'stirring rate', 'UV irradiation "
                                  "wavelength', 'mineral surface', 'reaction volume'.")
    value: str = Field(description="As stated, with its unit, e.g. '300 rpm', '254 nm', 'montmorillonite'.")
    set_label: Optional[str] = Field(default=None, description="Exact structure-plan set_label if it "
                                                               "applies to one set only; null if paper-wide.")
    quote: str
    source: str
    confidence: Literal["high", "medium", "low"]


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

    other_parameters: List[OtherParameter] = Field(
        default_factory=list,
        description="Any other experimental condition that could affect the outcome but isn't one "
                    "of the fields above. Empty if none.")

    @field_validator("per_set_overrides", mode="before")
    @classmethod
    def _accept_legacy_dict(cls, v):
        # runs/eder1994/build_manual_demo.py predates the list form and passes a dict
        if isinstance(v, dict):
            return [{"set_label": label, "field_name": f, "value": val}
                    for label, fields in v.items() for f, val in fields.items()]
        return v

    def overrides_for(self, set_label: str) -> Dict[str, float]:
        """Per-set values to write -- never assumed ones (those go to the review)."""
        return {o.field_name: o.value for o in self.per_set_overrides
                if o.set_label == set_label and o.basis != "assumed"}

    def override_details(self, set_label: str) -> Dict[str, "SetOverride"]:
        return {o.field_name: o for o in self.per_set_overrides
                if o.set_label == set_label and o.basis != "assumed"}
