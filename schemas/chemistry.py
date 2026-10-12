"""Stage 3c: chemical species and concentrations.

Deliberately modeled as a LIST of (name, concentration) pairs rather than one
field per compound. This mirrors how POLO's own variable mapping treats it:
every initial_<X>_aq_mM / sampled_<X>_aq_mM column in the wide template maps
to the SAME ontology pattern (status == 'pattern_direct' in
POLO_variable_mapping.csv) -- a repeated soluteName/soluteConcentration pair
on a LiquidPhase node, not 150 distinct ontology properties. Extracting into
that shape first, then mapping names onto the wide template's columns as a
separate flattening step, keeps the schema handed to the model small
regardless of how many species the full template happens to track.
"""
from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

Phase = Literal["aq", "gas", "solid"]
Role = Literal["initial", "sampled"]


class SoluteEntry(BaseModel):
    name: str = Field(description="Chemical species/compound name as it should appear in the "
                                   "database -- match the controlled vocabulary in "
                                   "schemas/template_vocab.json when the compound is already "
                                   "tracked there (e.g. 'NaCl', 'CuCl2', 'Gly').")
    in_controlled_vocab: bool = Field(
        description="Whether `name` matched an existing template_vocab.json entry. False "
                    "means this is a new species not yet a column -- flag for ontology/"
                    "template extension rather than silently coining a new column."
    )
    phase: Phase
    role: Role
    set_label: Optional[str] = Field(
        default=None,
        description="Which structure-plan set this value belongs to, or null if it's "
                    "constant across the whole paper (e.g. the fixed 0.5 mol dm-3 CuCl2 "
                    "background present in every condition in eder1994).",
    )
    concentration_value: Optional[float] = Field(description="Numeric value in the ORIGINAL reported unit.")
    concentration_unit_raw: Optional[str] = Field(description="Unit exactly as stated, e.g. 'mol dm-3'.")
    concentration_mM: Optional[float] = Field(
        default=None,
        description="Converted to mM. Leave null and flag in `conversion_note` if the "
                    "conversion requires an assumption (e.g. an unstated molecular weight) "
                    "rather than silently computing a possibly-wrong number.",
    )
    conversion_note: Optional[str] = None
    quote: str
    source: str
    confidence: Literal["high", "medium", "low"]


class ChemistryExtraction(BaseModel):
    paper_id: str
    solutes: List[SoluteEntry]
    unmapped_species: List[str] = Field(
        default_factory=list,
        description="Species names encountered that don't match the controlled vocabulary "
                    "-- surfaced for human review / ontology extension, never silently dropped.",
    )
