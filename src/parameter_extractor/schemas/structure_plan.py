"""Stage 2: figure out the row skeleton BEFORE extracting any values.

This is the step the earlier design discussion flagged as the most
consequential one to get right: papers routinely report a sweep (different
salts, concentrations, time points) in a single table, and getting the
grouping/row-count wrong here corrupts everything extracted after it.
Mirrors the template's full_id / set_id / sample_id / set_type hierarchy.
"""
from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

# "Average" (Mickey, 2026-10-31): a result averaged over several runs whose individual values the paper doesn't give
SetType = Literal["Independent", "Time Series", "Evaporation Cycle", "Average"]


class PlannedSample(BaseModel):
    sample_label: str = Field(description="Short human-readable label, e.g. 't = 97.3 h'")
    duration_hr: Optional[float] = None
    source: str = Field(description="e.g. 'Table 1, Na+ 3.33 mol dm-3 row, 1st time point'")


class PlannedSet(BaseModel):
    set_label: str = Field(description="e.g. 'Na+ 3.33 mol dm-3, 81 C'")
    set_type: SetType
    varying_condition_summary: str = Field(
        description="What distinguishes this set from the others, e.g. 'cation = Na+, "
                    "salt conc = 3.33 mol/dm3, T = 81 C'"
    )
    source_table_or_section: str
    data_source: str = Field(
        default="",
        description="'' if this set's data was measured in THIS paper. If the paper reproduces it from "
                    "another publication (cited table, redrawn figure, quoted results), the original "
                    "reference as the paper gives it, e.g. 'Rodriguez-Garcia et al. 2015, Nat. Commun. 6:8385 "
                    "(ref. 12)'.")
    samples: List[PlannedSample]


class StructurePlan(BaseModel):
    paper_id: str
    experiment_sets: List[PlannedSet]
    total_planned_rows: int = Field(description="Sum of len(samples) across all sets -- sanity check.")
    excluded_data: List[str] = Field(
        default_factory=list,
        description="Data explicitly NOT being planned into rows and why -- e.g. figure-only "
                    "data points, evaporation-cycle experiments, etc.",
    )
    notes: Optional[str] = None
