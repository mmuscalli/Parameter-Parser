"""
Wet-dry cycling conditions, extracted per experiment set by the optional
wet_dry stage (run only when the structure plan has cycling sets).

Flat on purpose (no Optional fields -- see the structured-output grammar note
in CLAUDE.md): only values the paper states are listed; anything not stated
is simply absent.
"""
from __future__ import annotations
from typing import List, Literal

from pydantic import BaseModel, Field

from parameter_extractor.schemas.common import Basis

CycleParameterName = Literal[
    "cycle_duration_hr",                  # template column
    "wet_phase_temperature_C", "wet_phase_duration_hr", "wet_phase_relative_humidity_pct",
    "dry_phase_temperature_C", "dry_phase_duration_hr",
]


class CycleParameter(BaseModel):
    set_label: str = Field(description="Exact structure-plan set_label; '' if it applies to every cycling set.")
    parameter: CycleParameterName
    value: float = Field(description="In the parameter's unit: hours, degrees C, or % relative humidity.")
    basis: Basis = Field(default="stated", description="'stated' in the paper; 'derived' by arithmetic "
                                                       "from stated values; 'assumed' if not stated.")
    quote: str = Field(description="Copied word for word from the paper (for a table value: its row/column labels and the value exactly as printed). Never your own words -- explanations go in `note`.")
    source: str
    confidence: Literal["high", "medium", "low"]
    note: str = Field(default="", description="Your explanation, e.g. how a 'derived' value was calculated; "
                                              "'' if none.")


class WetDryConditions(BaseModel):
    parameters: List[CycleParameter] = Field(
        default_factory=list, description="Only values the paper states. Leave a parameter out if not given.")
    notes: str = Field(default="", description="Anything that didn't fit, e.g. phases that change between cycles.")
