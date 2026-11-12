"""
A free second reading of table values (F3, 2026-11-11; prototype and measurements: scripts/table_crosscheck_proto.py,
eval/table_crosscheck_2026-11-11.md). Every value a step read from a table cell -- its answer names the table and the
row -- is looked up in a second, local reading of the paper's tables, and compared:

- the same number in the row with other ± uncertainties -> a `table_check` flag (strong evidence: on teng2023 it
  caught 54 of 58 misread uncertainties of local-model runs, flagging 2% of the right ones);
- the number not in its row at all -> a `table_not_found` flag, only where the second reading's table is positively
  the one the answer names (Mickey, 2026-11-11: flagged for now, kept or dropped after he has seen its noise).

The second reading (Mickey: the arXiv version when there is one, as the least likely to cause problems): the paper's
arXiv HTML text, when online lookups are on and the paper is on arXiv (found from an arXiv ID or DOI on its first
pages; cached); else the PDF's text layer (table_grid.pdf_grids, without the table-grid feature's reliability gate:
a cross-check only needs rows; garbled grids -- decimal points lost -- are skipped). Never on a run that read the
arXiv text itself. Values are never changed: flags only, grouped per table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from parameter_extractor.ingestion.table_grid import Grid, cell_value, grid_rows, pdf_grids, text_grids

_SPLIT_NUMBER = re.compile(r"(?<![\d.])\d+ \d{2,}(?![\d.])")          # '312 08': a decimal point lost
_ROW_SOURCE = re.compile(r"(Table\s+(?:S|[A-Z])?\d+)\s*,\s*row\s+(.+?)\s*(?:,\s*column\b|$)", re.I)
_SHORT_SOURCE = re.compile(r"(Table\s+(?:S|[A-Z])?\d+)\s*,\s*([^,]+?)\s*,\s*[^,]+$", re.I)
_TABLE = re.compile(r"\s*(Table\s+(?:S|[A-Z])?\d+)", re.I)


@dataclass
class TableValue:
    """One value a step read from a table."""
    step: str
    table: str            # 'Table 3' ('' when the source doesn't say)
    row: str              # the row's label as the answer gives it ('' when it doesn't)
    target: str           # what the value is about (sample / set label) -- also a row label to try
    column: str           # the dataset column / species
    value: float
    err_plus: float = 0.0
    err_minus: float = 0.0


@dataclass
class Finding:
    kind: str             # 'table_check' (uncertainties differ) / 'table_not_found' (not in its row)
    item: TableValue
    cell: str             # what the second reading has there


# ---- the second reading -----------------------------------------------------------------------------------------

def _norm(s: str) -> str:
    s = (s or "").lower().replace("ν", "nu").replace("ε", "eps").replace("ο", "omi")
    return re.sub(r"[^a-z0-9]", "", s)


def garbled(g: Grid) -> bool:
    """A grid whose text layer lost decimal points or ran numbers together: no second reading from it."""
    cells = [c for r in g.rows for c in r if c and any(ch.isdigit() for ch in c)]
    return not cells or sum(bool(_SPLIT_NUMBER.search(c)) for c in cells) > 0.1 * len(cells)


def pdf_reading(pdf_path: str, tables: List[dict]) -> List[Grid]:
    """Grids from the PDF's text layer for the tables the app found; tables the table-grid feature's reliability gate
    refuses are read anyway (landscape pages included)."""
    from parameter_extractor.ingestion import table_grid as tg
    tables = [t for t in tables if not t.get("supplement") and t.get("page_no")]
    grids = pdf_grids(pdf_path, tables)
    seen = {g.table_id for g in grids}
    for t in tables:
        if t["table_id"] in seen or not t.get("turned"):
            continue
        try:
            for found, words in tg._turned_tables(pdf_path, t["page_no"] - 1, t["turned"]):
                x0, top, x1, bottom = found["box"]
                body = [w for w in words if x0 - 1 <= w["x0"] and w["x1"] <= x1 + 1 and top <= w["top"] <= bottom]
                grids.append(Grid(f"P{len(grids) + 1}", f"Table {found['label']}", "", "", grid_rows(body)))
        except Exception:
            continue
    return [g for g in grids if not garbled(g)]


def arxiv_reading(text: str) -> List[Grid]:
    return [g for g in text_grids(text) if not garbled(g)]


# ---- what the steps read from tables ----------------------------------------------------------------------------

def values_from(optional: Iterable[Tuple[object, object]], chemistry=None) -> List[TableValue]:
    """Table values of the configurable steps (`optional`: [(spec, result)]) and of the chemistry step."""
    out: List[TableValue] = []
    for spec, result in optional or []:
        for p in getattr(result, "parameters", []) or []:
            src = getattr(p, "source", "") or ""
            if "table" not in src.lower() or getattr(p, "value", None) is None:
                continue
            if getattr(p, "mode", "") or getattr(p, "method", "") or getattr(p, "text", ""):
                continue
            m, t = _ROW_SOURCE.search(src), _TABLE.match(src)
            target = getattr(p, "sample_label", "") or getattr(p, "set_label", "") or ""
            out.append(TableValue(spec.name, (t.group(1) if t else "").title(), m.group(2) if m else "", target,
                                  p.parameter, float(p.value), float(getattr(p, "err_plus", 0) or 0),
                                  float(getattr(p, "err_minus", 0) or 0)))
    for s in (getattr(chemistry, "solutes", None) or []):
        src = s.source or ""
        m = _ROW_SOURCE.search(src) or _SHORT_SOURCE.search(src)
        if not m or "caption" in m.group(2).lower() or s.concentration_value is None:
            continue
        out.append(TableValue("chemistry", m.group(1).title(), m.group(2), "", s.name, float(s.concentration_value),
                              float(getattr(s, "err_plus", 0) or 0), float(getattr(s, "err_minus", 0) or 0)))
    return out


# ---- the comparison -------------------------------------------------------------------------------------------------

def _close(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(1e-9, 1e-6 * max(abs(a), abs(b)))


def _tokens(cell: str) -> List[str]:
    """A cell, plus its values when a dense table ran several together ('18.42^{+2.53}_{−2.43} 0.269^{+0.165}...');
    spaces inside ^{...} / _{...} don't split."""
    out, depth, cur = [], 0, ""
    for ch in cell:
        depth += {"{": 1, "}": -1}.get(ch, 0)
        if ch.isspace() and depth == 0:
            if cur:
                out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return [cell] + (out if len(out) > 1 else [])


def _lines(grids: List[Grid], key: str):
    """(grid, cells) where a label is: its row (first cell, or the second when the first is empty), or -- a
    transposed table, one object per column -- the column it heads."""
    for g in grids:
        for r in g.rows:
            if r and (_norm(r[0]) == key or (len(r) > 1 and not r[0].strip() and _norm(r[1]) == key)):
                yield g, list(r)
        for i, r in enumerate(g.rows[:4]):
            for j, c in enumerate(r):
                if j >= 1 and _norm(c) == key and (r[0].strip() or j > 1):
                    yield g, [row[j] for row in g.rows[i + 1:] if j < len(row)]


def _by_conditions(grids: List[Grid], label: str):
    """A row named by its conditions ('240 °C/10.0 s'): the row whose first cells hold those numbers in order."""
    nums = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", label or "")]
    if not nums:
        return
    for g in grids:
        for r in g.rows:
            lead = [cell_value(c).value for c in r[:len(nums)]]
            if len(lead) == len(nums) and all(_close(a, b) for a, b in zip(lead, nums)):
                yield g, list(r)


def _in_label(item: TableValue) -> bool:
    """A value that is its row's own label ('Cycle 1' -> cycle_number 1): not a cell, nothing to compare."""
    nums = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", f"{item.row} {item.target}")]
    return any(_close(n, item.value) for n in nums) and not item.err_plus and not item.err_minus


def check(item: TableValue, grids: List[Grid], ids_reliable: bool) -> Optional[Finding]:
    """A finding for one value, or None (it agrees, or its row isn't in the second reading)."""
    if _in_label(item):
        return None
    named = [g for g in grids if item.table and g.table_id.lower() == item.table.lower()]
    lines, sure = [], False
    for label in (item.row, item.target):
        key = _norm(label)
        if key and not lines:
            lines = list(_lines(named, key)) or list(_lines(grids, key))
    if not lines and item.row:
        lines = list(_by_conditions(named or grids, item.row))
    if lines:
        sure = ids_reliable and bool(named) and all(g in named for g, _ in lines)
    elif named and ids_reliable:                       # the row not located: the whole named table (weaker)
        lines = [(g, [c for r in g.rows for c in r]) for g in named]
    if not lines:
        return None
    same_number = ""
    for g, cells in lines:
        for raw in (t for cell in cells for t in _tokens(cell)):
            c = re.sub(r"(?<![_^])\{([-+]?[\d.]+)\}", r"\1", raw)          # '${30.7}_{-4.9}' -> '$30.7_{-4.9}'
            cv = cell_value(c)
            if cv.detected == "not detected" and item.value == 0:     # 'ND' is stored as 0
                return None
            if not _close(cv.value, item.value):
                continue
            no_errors_here = not cv.err_plus and not cv.err_minus              # its uncertainty printed elsewhere
            if (not item.err_plus and not item.err_minus) or no_errors_here or (
                    _close(cv.err_plus, item.err_plus) and _close(cv.err_minus, item.err_minus)):
                return None
            same_number = same_number or raw
    if same_number:
        cv = cell_value(re.sub(r"(?<![_^])\{([-+]?[\d.]+)\}", r"\1", same_number))
        return Finding("table_check", item, _shown(cv.value, cv.err_plus, cv.err_minus))
    if sure:
        return Finding("table_not_found", item, "row: " + " | ".join(c for c in lines[0][1] if c)[:150])
    return None


def cross_check(values: List[TableValue], grids: List[Grid], ids_reliable: bool) -> List[Finding]:
    return [f for f in (check(v, grids, ids_reliable) for v in values) if f is not None]


# ---- flags -------------------------------------------------------------------------------------------------------------

def _shown(v: float, ep: float, em: float) -> str:
    text = f"{v:g}"
    if ep or em:
        text += f" (+{abs(ep):g} / −{abs(em):g})" if abs(ep) != abs(em) else f" ± {abs(ep):g}"
    return text


def flag_messages(findings: List[Finding], reading: str) -> List[Tuple[str, str]]:
    """(kind, message) per table and kind: every value listed on its own line with both readings."""
    groups = {}
    for f in findings:
        groups.setdefault((f.kind, f.item.table or "a table"), []).append(f)
    out = []
    for (kind, table), fs in sorted(groups.items()):
        lines = [f"- {f.item.target or f.item.row}, {f.item.column}: read {_shown(f.item.value, f.item.err_plus, f.item.err_minus)}"
                 f"; the table has {f.cell}" for f in fs]
        if kind == "table_check":
            head = (f"{table}: {len(fs)} value(s) whose uncertainties differ from a second reading of the table "
                    f"({reading}). Check them against the paper:")
        else:
            head = (f"{table}: {len(fs)} value(s) not found in their row of a second reading of the table "
                    f"({reading}) -- a misread value, or one the step derived or took from elsewhere:")
        out.append((kind, head + "\n" + "\n".join(lines)))
    return out


def second_reading(ex, config) -> Tuple[List[Grid], str, bool]:
    """(grids, what they were read from, whether their table numbers can be trusted) for a run, or ([], why, False)."""
    source = getattr(ex, "source", None)
    if source is not None and getattr(source, "text", ""):
        return [], "the run read the arXiv text itself", False
    from pathlib import Path
    pdf = str(ex.pdf_path) if getattr(ex, "pdf_path", None) and Path(ex.pdf_path).is_file() else ""
    # the arXiv text: with online lookups and the arXiv cache the app and the command line set (not in plain library
    # use or tests, which stay offline and give the same result every time)
    if getattr(config, "online_checks", False) and getattr(config, "arxiv_cache_dir", None) and pdf:
        try:
            text, label = _arxiv_text(ex, config)
        except Exception:
            text, label = "", ""
        if text:
            grids = arxiv_reading(text)
            if grids:
                return grids, label, False
    if pdf:
        try:
            grids = pdf_reading(pdf, list(getattr(ex, "tables", []) or []))
        except Exception as e:                       # a second reading is a convenience: never in the way
            return [], f"the PDF's tables couldn't be read ({e})", False
        return grids, "the PDF's text layer", True
    return [], "no PDF", False


def _arxiv_text(ex, config) -> Tuple[str, str]:
    """The arXiv HTML text of a PDF run's paper (its arXiv ID or DOI on the first pages; cached), or ('', '')."""
    from parameter_extractor.ingestion import arxiv_source as ax
    source = getattr(ex, "source", None)
    record = getattr(source, "record", None) if source is not None else None
    cache = ax.LookupCache(config.arxiv_cache_dir) if getattr(config, "arxiv_cache_dir", None) else None
    if record is None:
        pages = getattr(ex.parsed, "page_texts", None) or [ex.parsed.text]
        ident = ax.identifier_in_text("\n".join(pages[:2]))
        if ident is None:
            return "", ""
        key = f"{ident.kind}:{ident.value}"
        cached = cache.record(key) if cache is not None else None
        if isinstance(cached, Exception):
            return "", ""
        record = cached or ax.resolve(ident)
        if cache is not None and not cached:
            cache.put(key, record)
            cache.save()
    text = ax.fetch_html_text(record, cache=cache)
    return (text or ""), f"the arXiv version {record.arxiv_id}{record.version}"
