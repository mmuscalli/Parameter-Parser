"""
Nucleic-acid oligomers per row (Mickey, 2026-11-03; the counterpart of peptide_totals.py):

  total_sampled_oligomers_yield -- the sum of the row's oligomer % yields, 2-mers and longer, of the naming
      convention ('sampled_<n>mer_<letters>_aq_%yield', names.oligonucleotide_name). Monomers (1mer) don't count.
  max_oligomer_length_nt -- the longest '<n>mer' with a value on the row (a yield or concentration above zero,
      or 'detected').

A value the paper states (or the conditions step extracted) is kept; the total is then checked against the sum
(a difference beyond rounding is reported). Calculated values are marked: provenance origin "calculated".
"""
from __future__ import annotations
import re
from typing import List

from parameter_extractor.ingestion.flatten_to_template import (DETECTED, MAX_OLIGOMER_COLUMN, TOTAL_OLIGOMERS_COLUMN,
                                                              row_to_template_dict, set_row_value)
from parameter_extractor.registry import is_oligonucleotide_column
from parameter_extractor.schemas.common import CONFIDENCE_ORDER
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow

CHECK_TOLERANCE = 0.05          # percentage points
_LENGTH = re.compile(r"sampled_(?:p-)?(\d+)mer_")      # 'p-2mer_A_3'-5'': a 5'-phosphorylated dimer counts too


def _decimals(value: float) -> int:
    text = f"{value:.10g}"
    return len(text.split(".")[1]) if "." in text and "e" not in text else 0


def _lowest(row, columns):
    levels = [row.provenance[c].confidence for c in columns
              if c in row.provenance and row.provenance[c].confidence in CONFIDENCE_ORDER]
    return min(levels, key=CONFIDENCE_ORDER.index) if levels else None


def fill_oligomer_totals(rows: List[ExtractedRow]):
    """Returns (rows with a calculated total, rows with a calculated max length, [(full_id, stated, sum, parts)]
    where a stated total differs from the sum)."""
    totals, lengths, differing = [], [], []
    for row in rows:
        record = row_to_template_dict(row)
        oligos = {c: v for c, v in record.items() if c.startswith("sampled_") and is_oligonucleotide_column(c)
                  and "_avg_" not in c and v not in (None, "")}
        if not oligos:
            continue
        parts = {c: v for c, v in oligos.items() if c.endswith("_%yield") and isinstance(v, (int, float))
                 and int(_LENGTH.match(c).group(1)) >= 2}
        if parts:
            total = round(sum(parts.values()), max(_decimals(v) for v in parts.values()))
            listed = " + ".join(f"{c.removeprefix('sampled_').removesuffix('_%yield').removesuffix('_aq')} {v:g}" for c, v in parts.items())
            stated = record.get(TOTAL_OLIGOMERS_COLUMN)
            if stated not in (None, ""):
                if isinstance(stated, (int, float)) and abs(stated - total) > CHECK_TOLERANCE:
                    differing.append((row.full_id, stated, total, listed))
            else:
                set_row_value(row, TOTAL_OLIGOMERS_COLUMN, total, CellSource(
                    origin="calculated", source=f"sum of the reported oligomer yields (2-mers and longer): {listed}",
                    confidence=_lowest(row, parts)))
                totals.append(row.full_id)
        present = [c for c, v in oligos.items() if v == DETECTED or (isinstance(v, (int, float)) and v > 0)]
        if present and record.get(MAX_OLIGOMER_COLUMN) in (None, ""):
            longest = max(present, key=lambda c: int(_LENGTH.match(c).group(1)))
            n = int(_LENGTH.match(longest).group(1))
            set_row_value(row, MAX_OLIGOMER_COLUMN, n, CellSource(
                origin="calculated", source=f"longest oligomer with a value on this row: {longest}",
                confidence=_lowest(row, [longest])))
            lengths.append(row.full_id)
    return totals, lengths, differing
