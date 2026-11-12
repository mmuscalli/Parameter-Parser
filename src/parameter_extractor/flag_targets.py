"""
Which values a flag is about (Mickey, 2026-11-11, after an eder1994 review): the cells -- (row id, column) -- an entry
of "Things to check" concerns, worked out from the run's own files, so it works for older run folders too.

- the columns: dataset columns the message names (`experiment_type`), else the compounds it names, mapped to their
  columns (`initial BaCl2` -> initial_BaCl2_aq_mM; a bare 'BaCl2' -> every column of BaCl2); table cross-check flags
  list their values one per line ('- HD 4732 b, pl_orbeccen: read 0.266 ...') and are matched by column and value;
- the rows: a row flag's own row; else the cells whose recorded source or quote is the flag's (the BaCl2 flags of
  eder1994 and their three cells all say 'Table 2, Conditions (right block, third group)'); else every row with a
  value in the column.

Used by `consolidate` (flags about exactly the same cells become one entry: the strongest reason first, the others
listed under it -- nothing dropped) and by the Flagged values view (gui/flagged_values.py).
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

Cell = Tuple[str, str]                         # (full_id, column)

# flags about the paper or the run, not about particular values
NOT_ABOUT_VALUES = {"reused_answer", "paper_source", "cited_data", "scope", "local_model", "no_results", "new_variable",
                    "duplicate_removed", "analysis", "fit_model", "lookup_unavailable", "archive_match",
                    "term_not_found", "figure_problem", "auto_digitized"}
# which reason leads when flags are merged: the more specific / serious first
PRIORITY = ["identity_not_quoted", "assumed_value", "table_check", "conflicting_values", "out_of_range",
            "unit_conversion", "value_range", "table_not_found", "concentration_not_stated", "pass_disagreement",
            "multimodal", "other_estimates", "archive_check", "assumed_default", "derived_value", "low_confidence"]
_COMPOUND = re.compile(r"^(initial|stock|sampled)_(.+?)_(aq|gas|s)_")
_LISTED = re.compile(r"^- (.+?), ([A-Za-z0-9_%+\-.()]+): read ([-+]?\d[\d.eE+-]*)")
_ROW_IDS = {"entry_number", "full_id", "set_id", "sample_id"}


def _norm_text(s: str) -> str:
    """For comparing locations and quotes: lower case, single spaces, without the notes the app appends in brackets
    ('Table 2, Conditions [mM computed by the pipeline from 2.5 mol dm-3]')."""
    s = re.sub(r"\s*\[[^\]]*\]", "", s or "")
    return re.sub(r"\s+", " ", s.strip().lower())


def _number(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Index:
    """The run's cells: values by (row, column), and each cell's recorded source and quote."""

    def __init__(self, observations: Iterable[dict], header: Iterable[str] = ()):
        self.values: Dict[Cell, str] = {}
        self.source: Dict[Cell, str] = {}
        self.quote: Dict[Cell, str] = {}
        cols = set(header)
        for o in observations:
            key = (str(o.get("full_id", "")), str(o.get("column", "")))
            if not key[0] or not key[1]:
                continue
            # a value corrected to empty is still the value the flag was about: its value as extracted
            self.values[key] = str(o.get("value", "") or o.get("extracted_value", "") or "")
            self.source[key] = _norm_text(o.get("source", ""))
            self.quote[key] = _norm_text(o.get("quote", ""))
            cols.add(key[1])
        self.columns = sorted(c for c in cols if c not in _ROW_IDS)
        self.compounds: Dict[str, List[Tuple[str, str]]] = {}           # name -> [(role, column)]
        for c in self.columns:
            m = _COMPOUND.match(c)
            if m:
                self.compounds.setdefault(m.group(2), []).append((m.group(1), c))

    def rows_with(self, column: str) -> List[str]:
        return [fid for (fid, col), v in self.values.items() if col == column and v != ""]


def _columns(flag, index: Index) -> List[str]:
    text = flag.message or ""
    named = [c for c in index.columns if re.search(rf"(?<![A-Za-z0-9_]){re.escape(c)}(?![A-Za-z0-9_])", text)]
    if named:
        return named
    found = []
    for name, cols in index.compounds.items():
        m = re.search(rf"(?:\b(initial|stock|sampled)\s+)?(?<![A-Za-z0-9_+-]){re.escape(name)}(?![A-Za-z0-9_+-])", text)
        if not m:
            continue
        role = m.group(1)
        found += [c for r, c in cols if not role or r == role]
    return found


def targets(flag, index: Index, row_id: str = "") -> Set[Cell]:
    """The cells a flag is about (empty: not about particular values)."""
    return located(flag, index, row_id)[0]


def located(flag, index: Index, row_id: str = "") -> Tuple[Set[Cell], bool]:
    """(cells, precise): precise when the flag's own row, its source / quote, or its listed values pinned the cells --
    not when they are every row with a value in the column (a guess)."""
    if flag.kind in NOT_ABOUT_VALUES:
        return set(), False
    if flag.kind in ("table_check", "table_not_found"):
        cells = set()
        for line in (flag.message or "").splitlines():
            m = _LISTED.match(line.strip())
            if not m:
                continue
            column, read = m.group(2), _number(m.group(3))
            for (fid, col), v in index.values.items():
                if col == column and read is not None and _number(v) is not None and \
                        abs(_number(v) - read) <= max(1e-9, 1e-6 * abs(read)):
                    cells.add((fid, col))
        return cells, bool(cells)
    columns = _columns(flag, index)
    if not columns:
        return set(), False
    if row_id:
        return {(row_id, c) for c in columns}, True
    candidates = {(fid, c) for c in columns for fid in index.rows_with(c)}
    src, quote = _norm_text(flag.source or ""), _norm_text(flag.quote or "")
    matched = {cell for cell in candidates
               if (src and index.source.get(cell) == src) or (quote and index.quote.get(cell) == quote)}
    return (matched, True) if matched else (candidates, False)


def _rank(kind: str) -> int:
    return PRIORITY.index(kind) if kind in PRIORITY else len(PRIORITY)


def consolidate(paper_flags: list, row_flags: Dict[str, list], index: Index) -> Tuple[list, Dict[str, list]]:
    """Paper-level flags about exactly the same cells become one: the strongest reason (PRIORITY) leads, the others are
    listed under it ('Also flagged: ...'), quotes and locations kept from the first that has them. Row flags merge
    the same way within their row. Only flags whose cells were located precisely (`located`), and only flags of
    different kinds, are merged: two flags that merely concern the same column say different things about it."""
    from parameter_extractor.validation.plausibility_checks import Flag

    def merged(flags: list, row_id: str = "") -> list:
        groups: Dict[frozenset, list] = {}
        order: List[object] = []
        for f in flags:
            found, precise = located(f, index, row_id)
            cells = frozenset(found) if precise else frozenset()
            if not cells:
                order.append(f)
                continue
            if cells not in groups:
                groups[cells] = []
                order.append(cells)
            groups[cells].append(f)
        out = []
        for item in order:
            if not isinstance(item, frozenset):
                out.append(item)
                continue
            fs = sorted(groups[item], key=lambda f: _rank(f.kind))
            if len(fs) == 1 or len({f.kind for f in fs}) < len(fs):
                # one flag; or two of the same kind -- separate entries by design (one per planet, per species): the
                # cells weren't told apart (teng2023: three planets' mode flags all citing 'Table 4'), merge none
                out += fs
                continue
            lead = fs[0]
            also = "\n".join(f"- ({f.kind.replace('_', ' ')}) {f.message}" for f in fs[1:])
            out.append(Flag(lead.kind, f"{lead.message}\nAlso flagged for the same value(s):\n{also}",
                            quote=next((f.quote for f in fs if f.quote), None),
                            source=next((f.source for f in fs if f.source), None),
                            unverified_quote=next((f.unverified_quote for f in fs if f.unverified_quote), None),
                            table_image_quote=next((f.table_image_quote for f in fs if f.table_image_quote), None),
                            model_note=lead.model_note,
                            page=next((f.page for f in fs if f.page), None)))
        return out

    return merged(paper_flags), {rid: merged(fs, rid) for rid, fs in row_flags.items()}
