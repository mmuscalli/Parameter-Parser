"""
Variables with no column yet ("new variables").

A value whose variable isn't in the known list -- a species with no template
column, a condition the methodology fields don't cover, a figure axis typed
in by hand -- is NOT written to the CSV (Mickey's rule: a new variable must be
accepted by the user first). It's kept here in full instead, so a later
review step can accept it (creating a column), merge it with a known variable
as a synonym, or ignore it. Saved per run as new_variables.json.
"""
from __future__ import annotations
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from parameter_extractor.schemas.common import QUOTE_DESC, SOURCE_DESC

from parameter_extractor.schemas.common import Confidence


class NewVariable(BaseModel):
    kind: Literal["species", "parameter", "figure_axis", "assumed_value"]   # assumed: not stated in the paper
    name: str                                   # as extracted, e.g. "Na2HPO4", "stirring rate"
    alias_name: str = ""                        # what the registry remembers it by (see registry.py)
    proposed_column: Optional[str] = None       # what its column would be called, if accepted
    role: Optional[str] = None                  # initial / sampled, for species
    value: Optional[float] = None
    value_text: Optional[str] = None            # non-numeric values, e.g. "montmorillonite"
    unit: Optional[str] = None
    set_label: Optional[str] = None             # None = paper-wide
    sample_label: Optional[str] = None
    quote: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[Confidence] = None
    origin: str                                 # "chemistry", "methodology", "Fig. 3", "search: <term>"
    row_ids: List[str] = Field(default_factory=list)   # rows (full_id) the value applies to
    pubchem_cid: int = 0                        # species identity, if PubChem knows the name
    pubchem_title: str = ""


# ---- targeted search for the user's "parameters to look for" ---------------
# Flat, no Optional fields: keeps the structured-output grammar small ("" = none).

class TermFinding(BaseModel):
    term: str = Field(description="The user's search term, verbatim.")
    found: bool = Field(description="False if the paper doesn't state this (then leave the rest empty).")
    name: str = Field(description="The parameter as the paper describes it, e.g. 'reaction volume'.")
    value: str = Field(description="As stated, with its unit, e.g. '1 cm3', '45 min'.")
    column: str = Field(description="Best matching column from the provided list, or '' if none fits.")
    set_label: str = Field(description="Exact structure-plan set_label if it applies to one set; '' if paper-wide.")
    quote: str = Field(description=QUOTE_DESC)
    source: str = Field(description=SOURCE_DESC)
    confidence: Literal["high", "medium", "low"]


class TermSearch(BaseModel):
    findings: List[TermFinding] = Field(
        description="At least one entry per search term: one per distinct value (e.g. per set) "
                    "when found, or a single found=false entry when the paper doesn't state it.")
