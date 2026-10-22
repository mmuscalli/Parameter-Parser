"""
The long-format record: one Observation per value -- which row, which column,
the value, its unit, and where it came from (origin step, quote, source,
confidence).

This is the canonical form of a run's data. The wide, PaperDataTemplate-
shaped CSV is generated FROM it (observations_to_records -> pivot), and it's
also written as observations.csv, where every value keeps its provenance --
the shape a database, unit normalization or cross-paper analysis wants, and
one that never runs out of columns.
"""
from __future__ import annotations
import csv
import re
from pathlib import Path
from typing import List, Optional, Union

from pydantic import BaseModel

from parameter_extractor.schemas.row_schema import ExtractedRow

ROW_KEYS = ("full_id", "set_id", "sample_id", "entry_number")   # identify the row; not observations
OBSERVATION_FIELDS = ["full_id", "set_id", "sample_id", "column", "value", "unit",
                      "origin", "source", "page", "quote", "quote_in_paper", "confidence"]


class Observation(BaseModel):
    full_id: str
    set_id: str
    sample_id: str
    entry_number: int
    column: str
    value: Union[float, int, str]
    unit: str = ""
    origin: str = ""
    source: str = ""
    page: Union[int, str] = ""          # the page the quote / table is on (validation/quotes.py)
    quote: str = ""
    # "yes": found word for word in the paper's text; "table image": transcribed by the model
    # from a table sent as an image (its text layer differs); "no": the model's own wording --
    # check it; "": no quote
    quote_in_paper: str = ""
    confidence: Optional[str] = None


QUOTE_IN_PAPER = {"in text": "yes", "table image": "table image", "not found": "no"}


# Unit from the column name, following the template's naming conventions.
# Compound units first: "_mL_min" must win over "_min".
_SUFFIX_UNITS = [
    (r"_mL_min$", "mL/min"), (r"_%yield$", "%"), (r"_pct$", "%"), (r"_mM$", "mM"), (r"_C$", "°C"), (r"_hr$", "h"),
    (r"_h$", "h"), (r"_sec$", "s"), (r"_min$", "min"), (r"_bar$", "bar"), (r"_mL$", "mL"),
    (r"_uL$", "µL"), (r"_g$", "g"), (r"_nm$", "nm"), (r"_rpm$", "rpm"), (r"_K$", "K"),
]
_UNITLESS = re.compile(r"(^|_)pH($|_)")


def unit_for_column(column: str) -> str:
    if _UNITLESS.search(column):
        return "pH"
    for pattern, unit in _SUFFIX_UNITS:
        if re.search(pattern, column):
            return unit
    return ""


def rows_to_observations(rows: List[ExtractedRow]) -> List[Observation]:
    from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
    out: List[Observation] = []
    for row in rows:
        record = row_to_template_dict(row)
        for column, value in record.items():
            if column in ROW_KEYS or value is None or value == "":
                continue
            src = row.provenance.get(column)
            out.append(Observation(
                full_id=row.full_id, set_id=row.set_id, sample_id=row.sample_id,
                entry_number=row.entry_number, column=column, value=value, unit=unit_for_column(column),
                origin=src.origin if src else ("pipeline" if column in _PIPELINE_COLUMNS else ""),
                source=src.source if src else "", quote=src.quote if src else "",
                page=src.page if src and src.page else "",
                quote_in_paper=QUOTE_IN_PAPER.get(src.quote_check, "") if src else "",
                confidence=src.confidence if src else None))
    return out


_PIPELINE_COLUMNS = {"source_notes", "extraction_confidence", "yield_below_threshold_note",
                     "original_data_reference"}


def observations_to_records(observations: List[Observation]) -> List[dict]:
    """Pivot back to one {column: value} dict per row, in row order."""
    records: dict = {}
    for o in observations:
        rec = records.setdefault(o.full_id, {"full_id": o.full_id, "set_id": o.set_id,
                                             "sample_id": o.sample_id, "entry_number": o.entry_number})
        rec[o.column] = o.value
    return list(records.values())


def write_observations_csv(observations: List[Observation], out_path: Path) -> None:
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(OBSERVATION_FIELDS)
        for o in observations:
            d = o.model_dump()
            writer.writerow(["" if d[k] is None else d[k] for k in OBSERVATION_FIELDS])
