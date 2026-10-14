"""
The final, flattened shape: one ExtractedRow per sample, in the same spirit
as a row of PaperDataTemplate.xlsx. This is assembled by
ingestion/flatten_to_template.py from a StructurePlan + Methodology +
ChemistryExtraction + measured yields -- it is NOT something the model
produces directly, because a wide fixed-width output is exactly what the
earlier design discussion flagged as hallucination-prone when asked for in
one shot. Species concentrations stay as a dict keyed by template column name
(e.g. 'initial_NaCl_aq_mM') rather than ~150 static fields.
"""
from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel


class ExtractedRow(BaseModel):
    full_id: str
    set_id: str
    sample_id: str
    set_type: str
    entry_number: int

    paper_doi: Optional[str] = None
    paper_title: str
    authors: List[str]
    year_published: int
    journal_published: str

    experiment_type: str
    solution_type: str
    duration_hr: Optional[float] = None
    vessel_material: Optional[str] = None
    solvent_name: Optional[str] = None
    analysis_method: Optional[str] = None
    headspace_gas: Optional[str] = None
    initial_temperature_C: Optional[float] = None
    initial_pressure_bar: Optional[float] = None
    sampled_temperature_C: Optional[float] = None

    # template column name -> value, e.g. {"initial_NaCl_aq_mM": 3330.0}
    species_mM: Dict[str, float] = {}

    sampled_2peptide_Gly_mM: Optional[float] = None
    sampled_3peptide_Gly_mM: Optional[float] = None
    sampled_2peptide_Gly_pct_yield: Optional[float] = None
    sampled_3peptide_Gly_pct_yield: Optional[float] = None
    yield_below_threshold_note: Optional[str] = None

    # any other template column -> value (e.g. {"initial_pH": 2.6}), for values
    # that don't have a dedicated field above -- currently only from digitized figures
    extra: Dict[str, float] = {}

    source_notes: Optional[str] = None
    extraction_confidence: Optional[str] = None
