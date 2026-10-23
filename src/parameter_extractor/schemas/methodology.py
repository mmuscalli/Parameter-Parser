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
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema
from .common import NOTE_DESC, QUOTE_DESC, SOURCE_DESC, Basis, Extracted

ExperimentType = Literal["Batch", "Flowthrough"]  # POLO's ExperimentType enum


def _required(names):
    def extra(schema: dict) -> None:
        schema["required"] = [n for n in names if n in schema.get("properties", {})]
    return extra
OverridableField = Literal[
    "initial_pressure_bar", "initial_temperature_C", "sampled_temperature_C", "initial_pH",
]


class SetOverride(BaseModel):
    """One per-set value. A list of these rather than a {set_label: {field: value}}
    dict because the API's structured outputs can't express free-form dict keys --
    a dict field comes back as an always-empty object."""
    model_config = ConfigDict(populate_by_name=True,
                              json_schema_extra=_required(["set", "f", "v", "q", "src", "c"]))
    set_label: str = Field(alias="set", description="Exact set_label string from the structure plan.")
    field_name: OverridableField = Field(alias="f")
    value: float = Field(alias="v")
    basis: Basis = Field(default="stated", alias="b", description="Leave out when stated; 'derived' by "
                                                                  "arithmetic from stated values; 'assumed' if "
                                                                  "not stated.")
    confidence: Literal["high", "medium", "low"] = Field(default="high", alias="c")
    quote: str = Field(default="", alias="q", description=QUOTE_DESC)
    source: str = Field(default="", alias="src", description=SOURCE_DESC)
    note: str = Field(default="", alias="n", description=NOTE_DESC)


class OtherParameter(BaseModel):
    """A condition or parameter the fixed fields don't cover (open-ended, so
    papers aren't limited to what PaperDataTemplate anticipated).

    Deliberately flat -- one text `value` rather than number/text/unit fields:
    every optional field multiplies the structured-output grammar, and adding
    three of them pushed the Methodology schema over the API's grammar size
    limit (400 "compiled grammar is too large"). Splitting value and unit is
    left to the review step."""
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(alias="nm", description="Short descriptive name, e.g. 'stirring rate', 'UV irradiation "
                                              "wavelength', 'mineral surface', 'reaction volume'.")
    value: str = Field(alias="v", description="As stated, with its unit, e.g. '300 rpm', '254 nm', "
                                              "'montmorillonite'.")
    set_label: Optional[str] = Field(default=None, alias="set", description="Exact structure-plan set_label if "
                                                                            "it applies to one set only; null if "
                                                                            "paper-wide.")
    quote: str = Field(alias="q", description=QUOTE_DESC)
    source: str = Field(alias="src", description=SOURCE_DESC)
    confidence: Literal["high", "medium", "low"] = Field(alias="c")


class Methodology(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    paper_id: SkipJsonSchema[str] = ""
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
            return [{"set_label": label, "field_name": f, "value": val}   # long names: populate_by_name
                    for label, fields in v.items() for f, val in fields.items()]
        return v

    def overrides_for(self, set_label: str) -> Dict[str, float]:
        """Per-set values to write -- never assumed ones (those go to the review)."""
        return {o.field_name: o.value for o in self.per_set_overrides
                if o.set_label == set_label and o.basis != "assumed"}

    def override_details(self, set_label: str) -> Dict[str, "SetOverride"]:
        return {o.field_name: o for o in self.per_set_overrides
                if o.set_label == set_label and o.basis != "assumed"}


def empty_methodology(paper_id: str) -> "Methodology":
    """Stand-in for a domain pack without the methodology stage: every field not reported."""
    fields = {name: {} for name, f in Methodology.model_fields.items()
              if f.is_required() and name != "paper_id"}
    return Methodology.model_validate({"paper_id": paper_id, **fields})
