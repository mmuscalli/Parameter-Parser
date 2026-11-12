"""
Values the paper's experiments share -- filled into rows that don't state them (Mickey, 2026-11-12: papers state a
method once, in the Methods or a caption, without repeating it for every experiment; the datasets had it only on the rows
where it was explicitly referenced).

Local, no model. Only rows with measured results get values (a sampled_ / total_sampled_ value -- not rows of values the
paper only calculated, not data reproduced from another paper), never over a value a step gave, and every filled cell
says so in its provenance ("assumed shared") and in one grouped `assumed_shared` flag per rule and set of rows. Three
rules, each configured in pack.json:

1. `group_columns` -- within a group of related rows (first the rows of one experiment set, then the rows from one
   figure or table): when the group's rows that state a column all have the same value, the group's other rows get it
   (a pressure or flow rate given for one row of a series).
2. `shared_columns` -- across the paper: when every measured row that states the column has the same value, every
   measured row gets it (analysis settings, vessel, solvent, suppliers). When they DISAGREE, nothing is filled and a
   `method_differs` flag asks the user to set the rows that have none (Mickey: never guess between values).
3. `column_pairs` -- related columns ([["sampled_temperature_C", "initial_temperature_C"], ...]): when at least two rows
   state both and in every one they are equal, a row stating one gets the other (Cleaves2008: the sampled temperature
   is the heating temperature on every row that gives both).

Selectors (`shared_columns`, `group_columns`): {"categories": [variable category ids], "columns": [...], "patterns":
[regex], "exclude": [...]}.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.validation.plausibility_checks import Flag

_RESULT = re.compile(r"^(?:total_sampled_|sampled_.+_(?:aq|gas|s)(?:_[a-z0-9]+)*_)")
_NEVER = {"set_type", "result_basis", "full_id", "set_id", "sample_id", "entry_number", "data_location",
          "original_data_reference", "source_notes", "extraction_confidence", "yield_below_threshold_note"}
_COMPOUND = re.compile(r"^(?:initial|sampled|stock|calculated|added)_")


def _empty(v) -> bool:
    return v is None or v == "" or (isinstance(v, float) and v != v)


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-3 * max(abs(a), abs(b)) or a == b     # 0.3333 h and 0.333333 h are both 20 min
    return str(a).strip() == str(b).strip()


def measured(record: dict) -> bool:
    """A row with at least one measured result (not only values the paper calculated)."""
    return any(_RESULT.match(c) and not _empty(v) for c, v in record.items())


def shared_columns(columns, spec: dict, order) -> List[str]:
    """The columns a selector (pack.json shared_columns / group_columns) picks, among `columns`."""
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


class _Filler:
    """The rows, their current values, and what was filled by which rule."""

    def __init__(self, rows: List[ExtractedRow]):
        self.rows = rows
        self.records = {r.full_id: row_to_template_dict(r) for r in rows}
        self.eligible = [r for r in rows if measured(self.records[r.full_id]) and not r.original_data_reference]
        self.filled: Dict[tuple, list] = {}             # (rule, rows filled) -> [(column, value)]

    def value(self, r: ExtractedRow, column: str):
        return self.records[r.full_id].get(column)

    def present(self) -> List[str]:
        return sorted({c for r in self.eligible for c, v in self.records[r.full_id].items() if not _empty(v)})

    def fill(self, rule: str, column: str, value, donor: ExtractedRow, targets: Sequence[ExtractedRow], why: str,
             donor_column: Optional[str] = None) -> None:
        src: CellSource = donor.provenance.get(donor_column or column) or CellSource(origin="", source="")
        for r in targets:
            set_row_value(r, column, value, CellSource(
                origin=f"{src.origin or 'the other rows'} -- assumed shared ({rule})", quote=src.quote,
                source=(src.source + f" [{why}]").strip(), confidence="low"))
            self.records[r.full_id][column] = value
        self.filled.setdefault((rule, tuple(r.full_id for r in targets)), []).append((column, value))

    def agreed(self, rows: Sequence[ExtractedRow], column: str):
        """(value, rows that have it, rows without) when the rows that state `column` all agree; else None."""
        have = [r for r in rows if not _empty(self.value(r, column))]
        missing = [r for r in rows if _empty(self.value(r, column))]
        if not have or not missing:
            return None
        first = self.value(have[0], column)
        if not all(_same(self.value(r, column), first) for r in have[1:]):
            return None
        return first, have, missing


def _groups(rows: List[ExtractedRow]) -> List[List[ExtractedRow]]:
    """Related rows: each experiment set, then each figure / table (its data location)."""
    by_set: Dict[str, list] = {}
    by_place: Dict[str, list] = {}
    for r in rows:
        by_set.setdefault(r.set_id, []).append(r)
        place = str(r.extra.get("data_location", "") or "")
        if place:
            by_place.setdefault(place, []).append(r)
    return [g for g in list(by_set.values()) + list(by_place.values()) if len(g) >= 2]


RULE_TEXT = {
    "same experiment set or figure": "every other row of their experiment set or figure / table that states them "
                                     "has the same value",
    "whole paper": "every other row with measured results has the same value",
    "related column": "every row that gives both columns has them equal",
}


def fill_in(rows: List[ExtractedRow], shared: Optional[dict], group: Optional[dict] = None,
            pairs: Sequence[Sequence[str]] = (), order=None) -> List[Flag]:
    """Apply the three rules (module text) to `rows`, in place. Returns the flags."""
    if not rows or not (shared or group or pairs):
        return []
    f = _Filler(rows)
    if len(f.eligible) < 2:
        return []
    # 1. within a group of related rows
    if group:
        columns = shared_columns(f.present(), group, order)
        for g in _groups(f.eligible):
            for column in columns:
                found = f.agreed(g, column)
                if found:
                    value, have, missing = found
                    f.fill("same experiment set or figure", column, value, have[0], missing,
                           f"assumed the same as the {len(have)} other row(s) of its set / figure that state it, "
                           f"e.g. {have[0].full_id}")
    # 2. across the paper
    differs = []
    if shared:
        for column in shared_columns(f.present(), shared, order):
            found = f.agreed(f.eligible, column)
            if found:
                value, have, missing = found
                f.fill("whole paper", column, value, have[0], missing,
                       f"assumed the same as the paper's other experiments ({len(have)} row(s) state it, e.g. "
                       f"{have[0].full_id})")
                continue
            missing = [r for r in f.eligible if _empty(f.value(r, column))]
            values = sorted({str(f.value(r, column)) for r in f.eligible if not _empty(f.value(r, column))})
            if missing and len(values) > 1:
                differs.append((column, values, missing))
    # 3. related columns
    for pair in pairs or ():
        a, b = pair[0], pair[1]
        both = [r for r in f.eligible if not _empty(f.value(r, a)) and not _empty(f.value(r, b))]
        if len(both) < 2 or not all(_same(f.value(r, a), f.value(r, b)) for r in both):
            continue
        for src, dst in ((b, a), (a, b)):
            targets = [r for r in f.eligible if not _empty(f.value(r, src)) and _empty(f.value(r, dst))]
            for r in targets:          # each row from its own value of the other column
                f.fill("related column", dst, f.value(r, src), r, [r],
                       f"{dst} = {src} on this paper's {len(both)} rows that give both", donor_column=src)

    flags = []
    by_pair: Dict[tuple, list] = {}
    for (rule, ids), items in f.filled.items():
        if rule == "related column":                  # one row at a time: grouped per column below
            key = tuple(sorted({c for c, _v in items}))
            by_pair.setdefault(key, []).extend(ids)
            continue
        listed = "; ".join(f"{c} = '{v if len(str(v)) <= 60 else str(v)[:60] + ' …'}'" for c, v in items)
        flags.append(Flag(
            "assumed_shared",
            f"{len(items)} value(s) filled into {len(ids)} row(s) that don't state them ({rule}): "
            f"{RULE_TEXT[rule]}, so they're assumed the same for these experiments -- check they hold. {listed}. "
            f"Rows: {', '.join(ids)}."))
    for cols, ids in by_pair.items():
        ids = sorted(set(ids))
        flags.append(Flag(
            "assumed_shared",
            f"{', '.join(cols)} filled into {len(ids)} row(s) from the related column (related column): "
            f"{RULE_TEXT['related column']}, so it's assumed for these rows too -- check it holds. "
            f"Rows: {', '.join(ids)}."))
    for column, values, missing in differs:
        shown = "; ".join(f"'{v if len(v) <= 40 else v[:40] + ' …'}'" for v in values[:4])
        flags.append(Flag(
            "method_differs",
            f"{column} differs between experiments ({shown}{' …' if len(values) > 4 else ''}), so it wasn't filled "
            f"into the {len(missing)} row(s) that don't state it -- set it for them if the paper says which applies. "
            f"Rows: {', '.join(r.full_id for r in missing)}."))
    return flags


def fill_shared(rows: List[ExtractedRow], spec: dict, order) -> List[Flag]:
    """The paper-wide rule alone (kept for callers and tests from before the other rules)."""
    return fill_in(rows, spec, order=order)
