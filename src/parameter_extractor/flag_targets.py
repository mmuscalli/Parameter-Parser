"""
Which values a flag is about (Mickey, 2026-11-11, after an eder1994 review): the cells -- (row id, column) -- an entry
of "Things to check" concerns, worked out from the run's own files, so it works for older run folders too.

- the columns: dataset columns the message names (`experiment_type`), else the compounds it names, mapped to their
  columns (`initial BaCl2` -> initial_BaCl2_aq_mM; a bare 'BaCl2' -> every column of BaCl2); table cross-check flags
  list their values one per line ('- HD 4732 b, pl_orbeccen: read 0.266 ...') and are matched by column and value;
- the rows: a row flag's own row; else the experiment sets whose labels the message names ("initial BaCl2 = 2.5 mol
  dm-3 (set 'Ba2+ 2.50 mol dm-3, 87 C')": that set's rows only -- 2026-11-12, it had marked every BaCl2 cell); then the
  cells whose recorded quote, else source, is the flag's (the quote may be kept as a table-image or unverified quote);
  else every row with a value in the column (a guess).

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
PRIORITY = ["identity_not_quoted", "quote_unrelated", "assumed_value", "table_check", "conflicting_values", "out_of_range",
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


def _quote_matches(cell_quote: str, flag_quote: str) -> bool:
    """A cell's quote and a flag's: the same, or one inside the other (a grouped flag quotes several cells, joined)."""
    if not cell_quote or not flag_quote:
        return False
    return cell_quote == flag_quote or cell_quote in flag_quote or (len(flag_quote) > 12 and flag_quote in cell_quote)


def _label_text(s: str) -> str:
    """A set label for matching: lower case, single spaces, no degree signs ('87 °C' and '87 C' alike)."""
    return re.sub(r"\s+", " ", (s or "").replace("°", " ").lower()).replace(" ,", ",").strip()


def plan_set_labels(run_dir) -> List[str]:
    """The set labels of a run's row plan (structure_planner.output.json), in order; [] when absent."""
    import json
    from pathlib import Path
    try:
        plan = json.loads((Path(run_dir) / "structure_planner.output.json").read_text())
    except (OSError, ValueError):
        return []
    return [s.get("set_label", "") or s.get("label", "") for s in plan.get("experiment_sets", plan.get("sets", []))]


def _number(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Index:
    """The run's cells: values by (row, column), and each cell's recorded source and quote."""

    def __init__(self, observations: Iterable[dict], header: Iterable[str] = (), set_labels: Iterable[str] = ()):
        self.values: Dict[Cell, str] = {}
        self.set_of: Dict[str, str] = {}                                 # row -> its set's number in the plan
        # the row plan's set labels, in order (set n = rows whose set_id ends in n): flags name sets by label
        self.set_labels = [(_label_text(label), f"{n:03d}") for n, label in enumerate(set_labels, start=1)
                           if len(_label_text(label)) >= 6]
        self.source: Dict[Cell, str] = {}
        self.quote: Dict[Cell, str] = {}
        cols = set(header)
        for o in observations:
            key = (str(o.get("full_id", "")), str(o.get("column", "")))
            if not key[0] or not key[1]:
                continue
            # a value corrected to empty is still the value the flag was about: its value as extracted
            self.values[key] = str(o.get("value", "") or o.get("extracted_value", "") or "")
            self.set_of[key[0]] = str(o.get("set_id", "") or "")[-3:]
            self.source[key] = _norm_text(o.get("source", ""))
            self.quote[key] = _norm_text(o.get("quote", ""))
            cols.add(key[1])
        self.columns = sorted(c for c in cols if c not in _ROW_IDS)
        self.compounds: Dict[str, List[Tuple[str, str]]] = {}           # name -> [(role, column)]
        for c in self.columns:
            m = _COMPOUND.match(c)
            if m:
                self.compounds.setdefault(m.group(2), []).append((m.group(1), c))

    def sets_named(self, text: str) -> Set[str]:
        """The plan sets whose labels `text` names (a label inside a longer named label doesn't count)."""
        text = _label_text(text)
        spans = []
        for label, number in self.set_labels:
            spans += [(m.start(), m.end(), number) for m in re.finditer(re.escape(label), text)]
        return {n for a, b, n in spans if not any(a2 <= a and b <= b2 and (a2, b2) != (a, b) for a2, b2, _ in spans)}

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
    narrowed = False
    named = index.sets_named(flag.message or "")
    in_sets = {cell for cell in candidates if index.set_of.get(cell[0]) in named}
    if in_sets:
        candidates, narrowed = in_sets, True
    src = _norm_text(flag.source or "")
    quote = _norm_text(flag.quote or flag.table_image_quote or flag.unverified_quote or "")
    # the quote first: it tells the cells apart where a location doesn't (eder1994: 'Table 2, Conditions' is every
    # CaCl2 cell's location, but '2.50 mol dm-3 80 °C' is the quote of the three the flag is about)
    by_quote = {cell for cell in candidates if quote and _quote_matches(index.quote.get(cell, ""), quote)}
    if by_quote:
        return by_quote, True
    by_source = {cell for cell in candidates if src and index.source.get(cell) == src}
    if by_source and by_source != candidates:          # a location every cell shares tells nothing apart
        return by_source, True
    return candidates, narrowed


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
