"""Stage 1: should this paper even be processed further?

Mirrors the inclusion/exclusion criteria from the project's own draft paper
(Muscalli_Literature_Database_Paper_Draft.docx, "Dataset Scope and Selection
Criteria"): aqueous solution system, single amino acid per experiment,
quantifiable peptide yield, prebiotically plausible conditions, not a
wet-dry/alternating-phase system, not a mixed-peptide (heteropolymer) system.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class TriageResult(BaseModel):
    paper_id: str
    is_aqueous_system: bool
    is_single_amino_acid: bool
    has_quantifiable_yield: bool
    is_prebiotically_plausible: bool = Field(
        description="False if the paper relies on industrial/pharma condensation agents "
                    "or engineered protecting groups producing yields well in excess of "
                    "plausible natural systems (often >90%)."
    )
    is_wet_dry_or_mixed_phase: bool = Field(
        description="True if the system alternates aqueous/non-aqueous states. "
                    "POLO currently can't describe these -- out of scope."
    )
    is_mixed_peptide_system: bool = Field(
        description="True if products are heteropolymers (more than one amino acid type "
                    "incorporated). Excluded to keep per-amino-acid comparisons clean."
    )
    recommendation: Literal["include", "exclude", "needs_human_review"]
    reasoning: str
    excluded_experiment_note: Optional[str] = Field(
        default=None,
        description="If only SOME experiments/sections in the paper should be excluded "
                    "(e.g. a subset uses set_type 'Evaporation Cycle', which the POLO "
                    "mapping notes says to skip), name them here rather than excluding "
                    "the whole paper.",
    )
