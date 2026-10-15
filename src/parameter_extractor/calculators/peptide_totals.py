"""
total_sampled_peptides_yield = the sum of a row's sampled peptide % yields.

In the original dataset this column was always calculated that way (Mickey,
2026-10-15). A paper that states the total itself (truman2024's figures) keeps
its stated value; otherwise, for any row with at least one sampled peptide
%-yield, the sum is filled in and marked as calculated, listing what was
added. Peptides are the columns of the peptide naming convention
(registry.is_peptide_column): homopolymers of length >= 2 and sequences.
Cyclic peptides (cyclo_*, e.g. the DKPs) count too: they draw on the same pool
of amino-acid monomers (Mickey, 2026-10-15).

Where the paper states the total, the sum is a check: a difference beyond
rounding is reported (rounding in the paper, or lengths it doesn't list).

Only the yields the paper reports for that row are summed -- if a paper
reports only some lengths, the total covers only those (the provenance says
which).
"""
from __future__ import annotations
from typing import List

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value
from parameter_extractor.registry import is_peptide_column
from parameter_extractor.schemas.common import CONFIDENCE_ORDER
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow

TOTAL_COLUMN = "total_sampled_peptides_yield"
CHECK_TOLERANCE = 0.05          # percentage points: the papers' own rounding


def _decimals(value: float) -> int:
    text = f"{value:.10g}"
    return len(text.split(".")[1]) if "." in text and "e" not in text else 0


def fill_total_peptide_yield(rows: List[ExtractedRow]):
    """Fills the total where it's empty. Returns (full_ids filled, [(full_id, stated, sum,
    parts text)] where a stated total differs from the sum)."""
    filled, differing = [], []
    for row in rows:
        record = row_to_template_dict(row)
        parts = {c: v for c, v in record.items()
                 if c.startswith("sampled_") and c.endswith("_%yield") and is_peptide_column(c)
                 and isinstance(v, (int, float))}
        if not parts:
            continue
        total = round(sum(parts.values()), max(_decimals(v) for v in parts.values()))
        listed = " + ".join(f"{c.removeprefix('sampled_').removesuffix('_%yield')} {v:g}"
                            for c, v in parts.items())
        stated = record.get(TOTAL_COLUMN)
        if stated not in (None, ""):                   # stated by the paper (or digitized): check it
            if isinstance(stated, (int, float)) and abs(stated - total) > CHECK_TOLERANCE:
                differing.append((row.full_id, stated, total, listed))
            continue
        levels = [row.provenance[c].confidence for c in parts
                  if c in row.provenance and row.provenance[c].confidence in CONFIDENCE_ORDER]
        set_row_value(row, TOTAL_COLUMN, total, CellSource(
            origin="calculated", source=f"sum of the reported peptide yields: {listed}",
            confidence=min(levels, key=CONFIDENCE_ORDER.index) if levels else None))
        filled.append(row.full_id)
    return filled, differing
