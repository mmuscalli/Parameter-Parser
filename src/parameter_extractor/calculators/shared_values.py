"""
Values the paper's experiments share (Mickey, 2026-11-12, Cleaves2008: the analysis method, HPLC settings, vessel and
solvent were on the 4 text-result rows only, not on the 16 rows digitized from Fig. 2 -- the same experiments' methods).

Local, no model. For each column a data pack declares shared (pack.json `shared_columns`: variable categories, columns,
regex patterns, exclusions), among the rows with measured results (a sampled_ / total_sampled_ value -- not rows of
values the paper only calculated, not data reproduced from another paper): when every such row that has a value has
the SAME value, the rows without one get it. Different values mean the paper specified them: nothing is filled.
Filled cells are marked assumed in their provenance, with one `assumed_shared` flag per column (grouped in Things to
check) -- never silently.
"""
from __future__ import annotations

import re
from typing import Dict, List

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.validation.plausibility_checks import Flag

_RESULT = re.compile(r"^(?:total_sampled_|sampled_.+_(?:aq|gas|s)(?:_[a-z0-9]+)*_)")
_NEVER = {"set_type", "full_id", "set_id", "sample_id", "entry_number", "data_location", "original_data_reference",
          "source_notes", "extraction_confidence", "yield_below_threshold_note"}
_COMPOUND = re.compile(r"^(?:initial|sampled|stock|calculated|added)_")


def _empty(v) -> bool:
    return v is None or v == "" or (isinstance(v, float) and v != v)


def measured(record: dict) -> bool:
    """A row with at least one measured result (not only values the paper calculated)."""
    return any(_RESULT.match(c) and not _empty(v) for c, v in record.items())


def shared_columns(columns, spec: dict, order) -> List[str]:
    """The columns `spec` (pack.json shared_columns) makes shared, among `columns`."""
    cats = set(spec.get("categories", []))
    named = set(spec.get("columns", []))
    patterns = [re.compile(p) for p in spec.get("patterns", [])]
    exclude = set(spec.get("exclude", [])) | _NEVER
    out = []
    for c in columns:
        if c in exclude or (_COMPOUND.match(c) and c not in named):
            continue
        if c in named or order.category_of(c) in cats or any(p.search(c) for p in patterns):
            out.append(c)
    return out


def fill_shared(rows: List[ExtractedRow], spec: dict, order) -> List[Flag]:
    """Fill the shared columns of measured rows that lack them (see the module text); one flag per column filled."""
    if not spec or not rows:
        return []
    records = {r.full_id: row_to_template_dict(r) for r in rows}
    eligible = [r for r in rows if measured(records[r.full_id]) and not r.original_data_reference]
    if len(eligible) < 2:
        return []
    present = {c for r in eligible for c, v in records[r.full_id].items() if not _empty(v)}
    filled: Dict[tuple, list] = {}                       # the rows filled -> [(column, value)]: one flag each
    for column in shared_columns(sorted(present), spec, order):
        have = [r for r in eligible if not _empty(records[r.full_id].get(column))]
        missing = [r for r in eligible if _empty(records[r.full_id].get(column))]
        values = {str(records[r.full_id][column]) for r in have}
        if not missing or len(values) != 1:
            continue                                      # nothing to fill, or the paper gives different values
        donor = have[0]
        value = records[donor.full_id][column]
        src: CellSource = donor.provenance.get(column) or CellSource(origin="", source="")
        note = (f"assumed the same as the paper's other experiments ({len(have)} row(s) state it, e.g. "
                f"{donor.full_id})")
        for r in missing:
            set_row_value(r, column, value, CellSource(
                origin=f"{src.origin or 'the other rows'} -- assumed shared", quote=src.quote,
                source=(src.source + f" [{note}]").strip(), confidence="low"))
        filled.setdefault(tuple(r.full_id for r in missing), []).append((column, value))
    flags = []
    for ids, items in filled.items():
        listed = "; ".join(f"{c} = '{v if len(str(v)) <= 60 else str(v)[:60] + ' …'}'" for c, v in items)
        flags.append(Flag(
            "assumed_shared",
            f"{len(items)} method value(s) filled into {len(ids)} row(s) that don't state them: every other row with "
            f"measured results has the same value, so they're assumed the same for these experiments -- check they "
            f"hold. {listed}. Rows: {', '.join(ids)}."))
    return flags
