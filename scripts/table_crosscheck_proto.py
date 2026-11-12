"""
F3 prototype (2026-11-11): a free second reading of table values. For each value a step read from a table (its
answer names the table, row and column), the same row is looked up in a second, local reading of the paper's tables
-- the PDF's text layer (ingestion/table_grid.pdf_grids) or the arXiv HTML text (text_grids) -- and the value and its
uncertainties are compared with the cell. Measured against ground truth: the NASA Exoplanet Archive comparison of each
run (archive_validation.json: which values match, which differ).

    python scripts/table_crosscheck_proto.py RUN_DIR [RUN_DIR ...] [--source pdf|arxiv|both] [--pdf PDF] [--arxiv ID]
                                                      [--show N]

Per run it prints:
  coverage   table values of the exoplanet steps that could be checked (their row found in a second-reading grid)
  agree / disagree   checked values whose cell has the same / a different value or uncertainty
  recall     values the archive says are wrong that the check flagged (disagree), of those it could check
  false      values the archive says are right that the check flagged anyway, of those it could check
Nothing here changes the app; it reads finished run folders.
"""
import argparse
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor.ingestion.table_grid import Grid, cell_value, grid_rows, pdf_grids, text_grids  # noqa: E402

STEPS = ("planet_parameters", "stellar_parameters", "system_and_discovery")
ARXIV_TEXTS = Path.home() / "Library/Application Support/Parameter Extractor/arxiv_cache/texts"


def _norm(s: str) -> str:
    """A row label for matching: Greek letters, spaces, dashes and case don't matter."""
    s = (s or "").lower().replace("ν", "nu").replace("ε", "eps").replace("ο", "omi").replace("ο", "omi")
    return re.sub(r"[^a-z0-9]", "", s)


def _tokens(cell: str) -> list:
    """A cell split into its values: dense tables whose columns ran together give one cell with several
    ('18.42^{+2.53}_{−2.43} 0.269^{+0.165}_{−0.150}'); spaces inside ^{...} / _{...} don't split."""
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


def _close(a: float, b: float) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(1e-9, 1e-6 * max(abs(a), abs(b)))


def find_tables_of(pdf: Path) -> list:
    """The app's table finder on a PDF (for run folders that kept no tables.json)."""
    import tempfile
    from parameter_extractor.ingestion.pdf_parser import parse_pdf
    from parameter_extractor.ingestion.table_finder import find_tables
    parsed = parse_pdf(str(pdf))
    with tempfile.TemporaryDirectory() as tmp:
        return find_tables(str(pdf), sorted(parsed.table_pages), Path(tmp),
                           rotations=getattr(parsed, "page_rotations", None))


def pdf_second_reading(pdf: Path, tables: list) -> list:
    """Grids from the PDF's text layer, without the cost feature's reliability gate (a cross-check only needs rows)."""
    from parameter_extractor.ingestion import table_grid as tg
    grids = pdf_grids(str(pdf), tables)
    seen = {g.table_id for g in grids}
    for t in tables:                                   # the ones the gate refused: read anyway
        if t["table_id"] in seen:
            continue
        try:
            if t.get("turned"):
                for found, words in tg._turned_tables(str(pdf), t["page_no"] - 1, t["turned"]):
                    x0, top, x1, bottom = found["box"]
                    body = [w for w in words if x0 - 1 <= w["x0"] and w["x1"] <= x1 + 1 and top <= w["top"] <= bottom]
                    grids.append(Grid(f"P{len(grids) + 1}", f"Table {found['label']}", "", "", grid_rows(body)))
        except Exception:
            pass
    return grids


def arxiv_second_reading(arxiv_id: str) -> list:
    path = next(iter(sorted(ARXIV_TEXTS.glob(f"{arxiv_id}*.txt.gz"))), None)
    if path is None:
        raise SystemExit(f"no cached arXiv text for {arxiv_id} in {ARXIV_TEXTS}")
    return text_grids(gzip.decompress(path.read_bytes()).decode())


def items(run: Path):
    """(step, row label, column, value, err_plus, err_minus, source) for every value a step read from a table."""
    for step in STEPS:
        f = run / f"{step}.output.json"
        if not f.is_file():
            continue
        d = json.loads(f.read_text())
        flat = d.get("parameters") or d.get("legacy_parameters") or []          # the older, flat answer format
        rows = d.get("rows") or [{"set_label": "", "sample_label": "", "values": flat}]
        for row in rows:
            for v in row.get("values", []):
                src = v.get("source", "")
                if "table" not in src.lower() or v.get("value") is None or v.get("mode") or v.get("method") \
                        or v.get("text"):
                    continue
                label = v.get("sample_label") or row.get("sample_label") or row.get("set_label") or ""
                m = re.search(r"row ([^,]+)", src)
                yield (step, m.group(1).strip() if m else label, label, v["parameter"], v["value"],
                       v.get("err_plus") or 0.0, v.get("err_minus") or 0.0, src)


_SPLIT_NUMBER = re.compile(r"(?<![\d.])\d+ \d{2,}(?![\d.])")      # '312 08': a decimal point lost


def garbled(g: Grid) -> bool:
    """A grid whose text layer lost decimal points or ran columns together: no second reading from it."""
    cells = [c for r in g.rows for c in r if c and any(ch.isdigit() for ch in c)]
    return not cells or sum(bool(_SPLIT_NUMBER.search(c)) for c in cells) > 0.1 * len(cells)


def _lines_for(grids: list, key: str):
    """The cells to look in for a row label: its row (label in the first two cells), or -- a transposed table, one
    object per COLUMN -- its column (label in a header row)."""
    for g in grids:
        for i, r in enumerate(g.rows):
            # a row label: the first cell, or the second when the first is empty (an indented sub-row)
            if r and (_norm(r[0]) == key or (len(r) > 1 and not r[0].strip() and _norm(r[1]) == key)):
                yield g, list(r)
        for i, r in enumerate(g.rows[:4]):                 # a transposed table: the label heads a column
            for j, c in enumerate(r):
                if j >= 1 and r[0].strip() and _norm(c) == key or (j >= 1 and not r[0].strip() and j > 1
                                                                      and _norm(c) == key):
                    yield g, [row[j] for row in g.rows[i + 1:] if j < len(row)]


def check(grids: list, row_label: str, value, ep, em, table: str = ""):
    """'agree' / 'disagree' (with what the cell says) / 'not found' / None when the row isn't found. When the row
    can't be located (a layout with one parameter per row, or an answer naming only the table), the whole named
    table is searched -- weaker: a repeated number can stand for another cell."""
    key = _norm(row_label)
    readable = [g for g in grids if not garbled(g)]
    lines = list(_lines_for(readable, key)) if key else []
    if not lines and table:
        lines = [(g, [c for r in g.rows for c in r]) for g in readable if g.table_id.lower() == table.lower()]
    if not lines:
        return None, ""
    best = ""
    for g, cells in lines:
        for c in [t for cell in cells for t in _tokens(cell)]:
            c = re.sub(r"(?<![_^])\{([-+]?[\d.]+)\}", r"\1", c)         # '${30.7}_{-4.9}' -> '$30.7_{-4.9}'
            cv = cell_value(c)
            if not _close(cv.value, value):
                continue
            no_errors_here = not cv.err_plus and not cv.err_minus     # its uncertainty printed elsewhere
            if (not ep and not em) or no_errors_here or (_close(cv.err_plus, ep) and _close(cv.err_minus, em)) or \
                    (ep and _close(cv.err_plus, ep) and not cv.err_minus and not em):
                return "agree", c
            best = best or c
    if best:
        return "disagree", best                     # the same number, other uncertainties: strong evidence
    row_text = " | ".join(" | ".join(cells) for g, cells in lines)
    return "not found", f"value not in the row: {row_text[:160]}"   # weak: another table, a rounding ...


def truth(run: Path):
    """(planet, column) -> 'right' / 'wrong' from the archive comparison (adopted rows only)."""
    out = {}
    path = run / "archive_validation.json"
    if not path.is_file():
        return out
    for r in json.loads(path.read_text()):
        if r.get("status") != "compared" or r.get("archive_solution"):
            continue
        name = _norm(r.get("pl_name"))
        for col in (r.get("matches") or []):
            out[(name, col if isinstance(col, str) else col.get("column"))] = "right"
        for d in (r.get("differs") or []):
            out[(name, d["column"] if isinstance(d, dict) else d)] = "wrong"
    return out


def evaluate(run: Path, grids: list, label: str, show: int) -> None:
    t = truth(run)
    counts, flags = Counter(), []
    for step, row_label, sample, col, v, ep, em, src in items(run):
        counts["table values"] += 1
        m = re.match(r"\s*(Table\s+[A-Z]?\d+)", src, re.I)
        verdict, cell = check(grids, row_label, v, ep, em, m.group(1).title() if m else "")
        if verdict is None:
            continue
        counts["checked"] += 1
        counts[verdict] += 1
        planet = _norm(sample.split("[")[0])
        cols = [col] + ([col + "err1"] if ep else []) + ([col + "err2"] if em else [])
        states = {t.get((planet, c)) for c in cols} - {None}
        state = "wrong" if "wrong" in states else ("right" if states == {"right"} else "")
        if state:
            counts[f"{state} checked"] += 1
            if verdict == "disagree":
                counts[f"{state} flagged"] += 1
            if verdict == "not found":
                counts[f"{state} not found"] += 1
        if verdict == "disagree":
            flags.append((state or "?", sample, col, v, ep, em, cell))
    c = counts
    rec = f"{c['wrong flagged']}/{c['wrong checked']}" if c["wrong checked"] else "-"
    fal = f"{c['right flagged']}/{c['right checked']}" if c["right checked"] else "-"
    print(f"{run.name} [{label}]: {c['checked']}/{c['table values']} found, {c['agree']} agree, {c['disagree']} "
          f"disagree (flagged), {c['not found']} value not in its row; recall {rec}, false flags {fal}; "
          f"not-found among wrong {c['wrong not found']}, among right {c['right not found']}")
    by_state = Counter(f[0] for f in flags)
    print(f"    flags by archive verdict: {dict(by_state)}; flagged columns: "
          f"{Counter(f[2] for f in flags).most_common(6)}")
    unknown = [f for f in flags if f[0] == "?"]
    for f in unknown[:show]:
        print(f"    ?     {f[1][:28]:28} {f[2]:16} {f[3]!s:>10} +{f[4]} {f[5]}   cell: {str(f[6])[:70]}")
    for f in [f for f in flags if f[0] != "?"][:show]:
        print(f"    {f[0]:5} {f[1][:28]:28} {f[2]:16} {f[3]!s:>10} +{f[4]} {f[5]}   cell: {str(f[6])[:70]}")


# ---- chemistry tables (prebiotic reference runs, PDF text layer) ------------------------------------------------
_CELL_SOURCE = re.compile(r"(Table\s+[A-Z]?\d+|Table\s+S\d+)\s*,\s*row\s+(.+?)\s*,\s*column", re.I)
# the older answer format: 'Table 1, 240 °C/10.0 s, Gly-Gly' -- the row named by its conditions, then the column
_SHORT_SOURCE = re.compile(r"(Table\s+[A-Z]?\d+|Table\s+S\d+)\s*,\s*([^,]+?)\s*,\s*[^,]+$", re.I)


def chemistry_items(run: Path):
    """(table id, row label, value) for chemistry values read from a table cell (the source names its row)."""
    d = json.loads((run / "chemistry.output.json").read_text())
    for sol in d.get("solutes", []):
        m = _CELL_SOURCE.search(sol.get("source") or "") or _SHORT_SOURCE.search(sol.get("source") or "")
        if m and "caption" in m.group(2).lower():
            continue
        if m and sol.get("concentration_value") is not None:
            yield re.sub(r"\s+", " ", m.group(1)).title().replace("Table S", "Table S"), m.group(2), \
                sol["concentration_value"]


def _row_cells(grids: list, table: str, label: str):
    """The cells of a value's row -- or of its column, in a transposed table -- in the named table's grid."""
    key = _norm(label)
    mine = [g for g in grids if g.table_id.lower() == table.lower() and not garbled(g)]
    found = [cells for _g, cells in _lines_for(mine, key)]
    if not found and key:                          # labels written longer or shorter than in the table
        for g in mine:
            for r in g.rows:
                if r and _norm(r[0]) and (_norm(r[0]).startswith(key) or key.startswith(_norm(r[0]))):
                    found.append(list(r))
    if not found:                                  # a row named by its conditions: '240 °C/10.0 s' -> 240, 10.0
        nums = [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", label)]
        if nums:
            for g in mine:
                for r in g.rows:
                    lead = [cell_value(c).value for c in r[:len(nums)]]
                    if len(lead) == len(nums) and all(_close(a, b) for a, b in zip(lead, nums)):
                        found.append(list(r))
    yield from found


def _values(cells) -> list:
    out = []
    for c in [t for cell in cells for t in _tokens(cell)]:
        v = cell_value(re.sub(r"(?<![_^])\{([-+]?[\d.]+)\}", r"\1", c)).value
        if v is not None:
            out.append(v)
    return out


def evaluate_chemistry(ref: Path) -> None:
    import random
    import tempfile
    from parameter_extractor.ingestion.pdf_parser import parse_pdf
    from parameter_extractor.ingestion.table_finder import find_tables
    info = json.loads((ref / "reference.json").read_text())
    pdf = ROOT.parent / "Paper Files" / info["pdf"]
    grids = pdf_second_reading(pdf, find_tables_of(pdf))
    usable_grids = [g for g in grids if not garbled(g)]
    items = list(chemistry_items(ref))
    c, wrong_rows = Counter(), []
    rng = random.Random(1)
    for table, label, value in items:
        c["cell values"] += 1
        rows = list(_row_cells(grids, table, label))
        if not rows:
            continue
        c["row found"] += 1
        values = [v for r in rows for v in _values(r)]
        if any(_close(v, value) for v in values):
            c["agree"] += 1
        else:
            c["not in its row (false alarm)"] += 1
            wrong_rows.append((table, label, value, " | ".join(rows[0])[:90]))
            continue
        # synthetic misreading: the value of the same table read from another row
        others = [v for g in usable_grids if g.table_id.lower() == table.lower() for r in g.rows
                  if r and not any(_norm(x) == _norm(label) for x in r[:2]) for v in _values(r)
                  if not _close(v, value)]
        if others:
            fake = rng.choice(others)
            c["synthetic errors"] += 1
            if not any(_close(v, fake) for v in values):
                c["synthetic errors caught"] += 1
    print(f"{ref.name} [PDF text layer]: grids {len(usable_grids)}/{len(grids)} readable "
          f"({', '.join(g.table_id for g in usable_grids)}); {c['row found']}/{c['cell values']} table-cell values "
          f"located, {c['agree']} agree, {c['not in its row (false alarm)']} false alarms; synthetic wrong-row "
          f"misreadings caught {c['synthetic errors caught']}/{c['synthetic errors']}")
    for w in wrong_rows[:5]:
        print("    not found:", w)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--source", choices=["pdf", "arxiv", "both"], default="both")
    ap.add_argument("--pdf", type=Path, default=ROOT.parent / "Paper Files/Paper Lists/Teng2023/teng2023.pdf")
    ap.add_argument("--arxiv", default="2308.05343")
    ap.add_argument("--show", type=int, default=8)
    ap.add_argument("--chemistry", action="store_true", help="RUNS are runs/reference/<name> folders: check the "
                    "chemistry step's table values against the PDF's text layer")
    a = ap.parse_args()
    if a.chemistry:
        for ref in a.runs:
            evaluate_chemistry(ref)
        return 0
    for run in a.runs:
        if a.source in ("pdf", "both"):
            tables = json.loads((run / "tables.json").read_text()) if (run / "tables.json").is_file() else \
                find_tables_of(a.pdf)
            evaluate(run, pdf_second_reading(a.pdf, tables), "PDF text layer", a.show)
        if a.source in ("arxiv", "both"):
            evaluate(run, arxiv_second_reading(a.arxiv), "arXiv text", a.show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
