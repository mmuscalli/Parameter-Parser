"""
Tables read by the app (Mickey, 2026-11-07: "let code read the tables, let the model only map them").

A table's cells are read from the PDF's text layer -- words grouped into lines, columns found from the gaps that
run through every numeric line -- or from an HTML table (arXiv: ' | ' rows). Each usable table becomes a Grid with
row and column numbers; the grids go into the paper the model reads, and an extraction step may answer with a
MAPPING (which grid column is which variable, which grid row is which sample) instead of copying every number:
the app then reads the cells itself (`cell`). Output tokens no longer grow with the number of cells, and the
numbers come straight from the PDF.

A grid is only offered when it looks reliable (`usable`): enough columns and numeric rows, a stable column count.
Scanned papers' OCR text, tables whose columns can't be separated, and anything odd stay with the model reading the
table from the text and the table images, as before.

Sub- and superscripts (asymmetric uncertainties '1.23^{+0.05}_{-0.04}', footnote marks) are attached to the cell
they belong to, in the LaTeX-like form the arXiv text uses; `cell_value` reads them.
"""
from __future__ import annotations
import re
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

LINE_TOL = 2.5            # pt: words whose tops differ by less are on one line
MIN_COLUMN_GAP = 6.0      # pt: narrower gaps are spaces between words of one cell
SMALL = 0.85              # a word this much smaller than the table's text is a sub- or superscript
_NUM = re.compile(r"[-+−–]?\d")


@dataclass
class Grid:
    grid_id: str                      # 'G1', 'G2', ...
    table_id: str                     # 'Table 2', 'Table S1', 'Table IV'
    page: str                         # page label ('4', 'S2'); '' for an HTML table
    caption: str
    rows: List[List[str]]
    span: Tuple[int, int] = (-1, -1)   # text sources: the lines [start, end) the table occupies in the text

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def cell(self, r: int, c: int) -> str:
        if 0 <= r < len(self.rows) and 0 <= c < len(self.rows[r]):
            return self.rows[r][c]
        return ""

    def header(self, c: int, upto: int) -> str:
        """The column's header: its cells in the rows above `upto` that hold no number."""
        parts = [self.rows[r][c] for r in range(min(upto, len(self.rows)))
                 if c < len(self.rows[r]) and self.rows[r][c] and not _NUM.search(self.rows[r][c])]
        return " ".join(parts)

    def render(self) -> str:
        """The grid as the model reads it: every cell with its column number, one line per row."""
        head = f"{self.grid_id} = {self.table_id}" + (f" (page {self.page})" if self.page else "") + \
               f", {len(self.rows)} rows x {self.n_cols} columns"
        lines = [head]
        for r, row in enumerate(self.rows):
            cells = " ".join(f"[{c}] {v}" + (" ⚠not readable" if unreadable(v) else "") for c, v in enumerate(row) if v)
            lines.append(f"  r{r}: {cells}")
        return "\n".join(lines)


def usable(rows: List[List[str]]) -> bool:
    """Reliable enough to map: >= 2 columns and >= 2 rows with numbers in >= 2 cells, and (almost) no cell of
    those rows holding loose numbers the cell reader can't take apart -- the mark of a column split in the wrong
    place ('1 45 °C 4 hrs') or of OCR splitting a number ('9 1.4')."""
    if not rows or max(len(r) for r in rows) < 2:
        return False
    # rows holding values: >= 2 cells with numbers (a results table), or a label beside one readable value
    # (a parameter table: 'P | Period (days) | 11.535^{+0.0008}_{-0.0008}')
    numeric = [r for r in rows if sum(1 for v in r if v and _NUM.search(v)) >= 2
               or (sum(1 for v in r if v) >= 2 and any(cell_value(v).value is not None for v in r[1:] if v))]
    if len(numeric) < 3 and len([r for r in numeric if sum(1 for v in r if v and _NUM.search(v)) >= 2]) < 2:
        return False
    # caption or footnote prose that fell inside the table's box isn't a sign of a bad split
    numeric = [r for r in numeric if len(re.findall(r"[A-Za-z]{3,}", " ".join(r))) < 4
               or sum(1 for v in r if v and cell_value(v).value is not None) >= 0.5 * sum(1 for v in r if v)]
    cells = [v for r in numeric for v in r if v and _NUM.search(v)]
    broken = [v for v in cells if unreadable(v)]
    # a few unreadable cells are marked in the grid (the model gives those values itself); many mean the
    # columns were split in the wrong place or the text layer is unreliable
    return len(broken) <= 0.2 * len(cells)


def unreadable(cell: str) -> bool:
    """A cell of numbers the app can't read as one value: two plain numbers side by side ('1 45 °C 4 hrs' -- a
    column split in the wrong place; '9 1.4' -- OCR; '2 991 ± 0 029' -- decimal points missing from the text
    layer), or sub/superscripts that don't make a value. Identifiers, coordinates and references
    ('J00174714-6621323', '00:17:47.14', 'Sec. 3.1 & 3.3') aren't."""
    if cell_value(cell).value is not None or re.fullmatch(r"\s*\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?\s*", cell):
        return False
    plain_number = re.compile(r"[-+−]?\d+(?:\.\d+)?")
    tokens = cell.split()
    if any(plain_number.fullmatch(a) and plain_number.fullmatch(b) for a, b in zip(tokens, tokens[1:])):
        return True
    return bool(re.search(r"[\^_]\{", cell)) and bool(re.match(r"\s*[-+−]?\d", cell))


# ---- PDF ----------------------------------------------------------------------------------------------------

def _lines(words: List[dict]) -> List[dict]:
    lines: List[dict] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        for ln in lines:
            if abs(ln["top"] - w["top"]) <= LINE_TOL:
                ln["words"].append(w)
                ln["bottom"] = max(ln["bottom"], w["bottom"])
                break
        else:
            lines.append({"top": w["top"], "bottom": w["bottom"], "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
    return sorted(lines, key=lambda l: l["top"])


def _attach_scripts(lines: List[dict], small: List[dict]) -> None:
    """Sub-/superscript words onto the word they follow on the nearest line: '^{+0.05}' above its middle,
    '_{-0.04}' below."""
    for w in small:
        mid = (w["top"] + w["bottom"]) / 2
        ln = min(lines, key=lambda l: abs((l["top"] + l["bottom"]) / 2 - mid), default=None)
        if ln is None or abs((ln["top"] + ln["bottom"]) / 2 - mid) > 2 * (ln["bottom"] - ln["top"]):
            continue
        base = [b for b in ln["words"] if b["x0"] <= w["x0"] + 1]
        if not base:
            continue
        b = max(base, key=lambda b: b["x1"])
        mark = "^" if mid < (ln["top"] + ln["bottom"]) / 2 else "_"
        b.setdefault("scripts", []).append((w["x0"], f"{mark}{{{w['text']}}}"))
        b["x1"] = max(b["x1"], w["x1"])


def _word_text(w: dict) -> str:
    return w["text"] + "".join(s for _, s in sorted(w.get("scripts", [])))


def _columns(lines: List[dict]) -> List[float]:
    """Column separators: x positions inside gaps (> MIN_COLUMN_GAP) that no word of any numeric line covers."""
    # rows of the table body: several words, at least 40% of them numbers (a caption's last line or a footnote
    # that mentions '45 °C and 55 °C' would bridge every gap)
    numeric = [ln for ln in lines if len(ln["words"]) >= 2
               and sum(1 for w in ln["words"] if _NUM.search(w["text"])) >= max(1, 0.4 * len(ln["words"]))]
    if not numeric:
        return []
    spans = sorted((w["x0"], w["x1"]) for ln in numeric for w in ln["words"])
    merged = [list(spans[0])]
    for a, b in spans[1:]:
        if a <= merged[-1][1] + MIN_COLUMN_GAP:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(merged[i][1] + merged[i + 1][0]) / 2 for i in range(len(merged) - 1)]


def _join_decimals_drop_leaders(words: List[dict]) -> List[dict]:
    """EXOFAST-style tables (nielsen2019 Table 3): the decimal point is a word of its own ('11', '.', '53533') and
    dot leaders ('. . . .') fill the gaps between columns. Digits-dot-digits close together become one number;
    the dots left are leaders and go."""
    ws = [dict(w) for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"]))]
    out: List[dict] = []
    i = 0
    digit_end = lambda t: bool(re.search(r"\d$", t))
    while i < len(ws):
        w = ws[i]
        nxt = ws[i + 1] if i + 1 < len(ws) else None
        prev = out[-1] if out else None
        line = lambda a, b: a is not None and b is not None and abs(a["top"] - b["top"]) <= LINE_TOL
        # a lone '.' between two digit words, close on both sides: a decimal point ('2 . 991' -> '2.991')
        if (w["text"] == "." and line(prev, w) and line(w, nxt) and digit_end(prev["text"])
                and nxt["text"][:1].isdigit() and nxt["x0"] - prev["x1"] < 8):
            prev["text"] += "." + nxt["text"]
            prev["x1"] = nxt["x1"]
            for k in ("scripts",):
                if k in nxt:
                    prev.setdefault(k, []).extend(nxt[k])
            i += 2
            continue
        out.append(w)
        i += 1
    return [w for w in out if not re.fullmatch(r"\.+", w["text"])]


def grid_rows(words: List[dict]) -> List[List[str]]:
    """Words of one table's body (caption left out) -> rows of cells."""
    if not words:
        return []
    words = _join_decimals_drop_leaders(words)
    size = statistics.median(w.get("size", 10) for w in words)
    normal = [dict(w) for w in words if w.get("size", size) >= SMALL * size]
    small = [w for w in words if w.get("size", size) < SMALL * size]
    lines = _lines(normal)
    _attach_scripts(lines, small)
    seps = _columns(lines)
    rows = []
    for ln in lines:
        cells = [[] for _ in range(len(seps) + 1)]
        for w in ln["words"]:
            centre = (w["x0"] + w["x1"]) / 2
            cells[sum(1 for s in seps if centre > s)].append(_word_text(w))
        row = [" ".join(c) for c in cells]
        if any(row):
            rows.append(row)
    return rows


def pdf_grids(pdf_path: str, tables: List[dict], start: int = 1) -> List[Grid]:
    """Grids for the tables table_finder found (their `box` / `caption_box` in PDF points); tables on turned
    (landscape) pages are found and read on an upright copy of the page."""
    from parameter_extractor.ingestion.pdf_parser import open_plumber
    from parameter_extractor.ingestion.table_finder import _words
    out: List[Grid] = []

    def add(t: dict, words: List[dict], box, cap) -> None:
        x0, top, x1, bottom = box
        # only the caption's first line ('Table 1. ...') is left out: its next lines can be the table's header
        # rows (faisal2005); leftover caption prose falls into a row the model ignores
        first = cap[0] + 1.2 * statistics.median([w["bottom"] - w["top"] for w in words] or [10])
        body = [w for w in words if x0 - 1 <= w["x0"] and w["x1"] <= x1 + 1 and top <= w["top"] <= bottom
                and not (cap[0] - 0.5 <= w["top"] < first)]
        rows = grid_rows(body)
        if usable(rows):
            out.append(Grid(f"G{start + len(out)}", t["table_id"], t.get("page_label", ""), t.get("caption", ""), rows))

    with open_plumber(pdf_path) as doc:
        for t in tables:
            if t.get("turned"):
                for found, words in _turned_tables(pdf_path, t["page_no"] - 1, t["turned"]):
                    add({**t, "table_id": t["table_id"] if t["table_id"].startswith("Table ") and
                         not t["table_id"].startswith("Table on page") else f"Table {found['label']}"},
                        words, found["box"], found["caption_box"])
            elif t.get("box") and not _scanned(pdf_path, t["page_no"] - 1):
                add(t, _words(doc.pages[t["page_no"] - 1]), t["box"], t.get("caption_box", (0, 0)))
    return out


def _scanned(pdf_path: str, index: int) -> bool:
    """A scanned page: its text is OCR drawn invisibly over the page image (text render mode 3), which splits
    numbers ('9 1.4'). No grids -- the model reads the table from the page image, as before. (A full-page image
    alone isn't a sign: kim2017's accepted manuscript has one behind ordinary text.)"""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        modes = [raw.FPDFTextObj_GetTextRenderMode(o.raw) for o in doc[index].get_objects(max_depth=3)
                 if o.type == raw.FPDF_PAGEOBJ_TEXT]
    finally:
        doc.close()
    return bool(modes) and sum(1 for m in modes if m == 3) > 0.5 * len(modes)


def _turned_tables(pdf_path: str, index: int, angle: int):
    """[(table_finder entry, words)] for the tables on a landscape page, read from an upright copy of it."""
    import io
    import pdfplumber
    import pypdfium2 as pdfium
    from parameter_extractor.ingestion.table_finder import _find_on_page, _words
    src = pdfium.PdfDocument(str(pdf_path))
    new = pdfium.PdfDocument.new()
    try:
        new.import_pages(src, [index])
        new[0].set_rotation((new[0].get_rotation() + angle) % 360)
        buf = io.BytesIO()
        new.save(buf)
    finally:
        new.close()
        src.close()
    buf.seek(0)
    with pdfplumber.open(buf) as d:
        page = d.pages[0]
        words = _words(page)
        return [(f, words) for f in _find_on_page(page, index + 1)]


# ---- text with ' | ' rows (arXiv HTML) ----------------------------------------------------------------------

_CAPTION = re.compile(r"^\s*(Table\s+([A-Z]?\d+|[IVXLC]+))\b[.:]?\s*(.*)$", re.IGNORECASE)


def text_grids(text: str, start: int = 1) -> List[Grid]:
    """Grids from a text whose tables are rows of ' | '-separated cells (html_text.py), named by the nearest
    'Table N' caption above (within 8 lines) or below (within 5)."""
    lines = text.splitlines()
    out: List[Grid] = []
    i = 0
    while i < len(lines):
        if " | " not in lines[i]:
            i += 1
            continue
        j, rows = i, []
        while j < len(lines) and (" | " in lines[j] or (not lines[j].strip() and j + 1 < len(lines)
                                                         and " | " in lines[j + 1])):
            if lines[j].strip():
                rows.append([c.strip() for c in lines[j].split(" | ")])
            j += 1
        caption, table_id = "", ""
        for k in list(range(i - 1, max(i - 9, -1), -1)) + list(range(j, min(j + 5, len(lines)))):
            m = _CAPTION.match(lines[k])
            if m:
                table_id, caption = m.group(1).title().replace("Table", "Table"), lines[k].strip()
                break
        if usable(rows):
            out.append(Grid(f"G{start + len(out)}", table_id or f"Table at line {i + 1}", "", caption, rows, (i, j)))
        i = j
    return out


def inline(text: str, grids: List[Grid]) -> str:
    """A text source with each gridded table replaced, where it stands, by its numbered grid (the arXiv text holds
    its tables as ' | ' rows: appending the grids as well stored every table twice -- aa57186, +4K tokens)."""
    lines = text.splitlines()
    for g in sorted((g for g in grids if g.span[0] >= 0), key=lambda g: -g.span[0]):
        lines[g.span[0]:g.span[1]] = [f"=== TABLE GRID {g.render()}", "=== END OF TABLE GRID " + g.grid_id]
    return "\n".join(lines)


def render_all(grids: List[Grid]) -> str:
    if not grids:
        return ""
    return ("\n\n=== TABLE GRIDS -- the app has read these tables' cells (r = row number, [n] = column number). "
            "Answer for these tables with a mapping (grid id, column numbers, row numbers), not by copying their "
            "numbers. ===\n"
            + "\n\n".join(g.render() for g in grids) + "\n=== END OF TABLE GRIDS ===\n")


# ---- reading a cell -------------------------------------------------------------------------------------------

@dataclass
class CellValue:
    value: Optional[float] = None
    high: float = 0.0                 # a range's upper end
    err_plus: float = 0.0
    err_minus: float = 0.0
    limit: int = 0                    # 1 = upper limit ('< 3.5'), -1 = lower ('> 13')
    text: str = ""                    # the cell as printed (marks removed)
    unit: str = ""                    # a unit printed in the cell itself ('45 °C', '2.5 µL')
    detected: str = ""                # 'not detected' / 'detected' for n.d. / + style cells


_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-", "‒": "-"})
_FOOT = re.compile(r"\^\{[a-zA-Z*†‡§¶#]{1,2}\}|(?<=\d)[*†‡§¶#]+|(?<=\d)[a-e](?=\s|$)")
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s*[x×]\s*10\^?\{?[-+]?\d+\}?|[eE][-+]?\d+)?"


def _float(s: str) -> Optional[float]:
    s = s.replace(" ", "")
    m = re.fullmatch(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))(?:[x×]10\^?\{?([-+]?\d+)\}?|[eE]([-+]?\d+))?", s)
    if not m:
        return None
    v = float(m.group(1))
    exp = m.group(2) or m.group(3)
    return v * 10 ** int(exp) if exp else v


def _with_scripts(s: str):
    """(value, err_plus, err_minus) for a number followed by one or two ^{...} / _{...} uncertainties (braces may
    nest: '_{-4.2\\times 10^{-7}}'), else None."""
    m = re.match(r"\s*(" + _NUMBER + r")\s*(?=[_^]\{)", s)
    if not m:
        return None
    value, rest, scripts = _float(m.group(1)), s[m.end():], []
    while rest.strip():
        rest = rest.strip()
        if rest[:2] not in ("^{", "_{"):
            return None
        depth, i = 0, 1
        for i in range(1, len(rest)):
            depth += {"{": 1, "}": -1}.get(rest[i], 0)
            if depth == 0:
                break
        inner, mark, rest = rest[2:i], rest[0], rest[i + 1:]
        inner = re.sub(r"\\times|×", "x", inner).replace(" ", "")
        n = _float(re.sub(r"x10\^\{?([-+]?\d+)\}?", r"x10^\1", inner))
        if n is None:
            return None
        scripts.append((mark, n))
    if value is None or not 1 <= len(scripts) <= 2 or len({m for m, _ in scripts}) != len(scripts):
        return None
    ep = next((abs(n) for mk, n in scripts if mk == "^"), 0.0)
    em = next((-abs(n) for mk, n in scripts if mk == "_"), 0.0)
    return value, ep, em


def cell_value(cell: str) -> CellValue:
    """A table cell's number(s): '13.96', '1.23 ± 0.05', '1.23^{+0.05}_{-0.04}', '$1.23_{-0.04}^{+0.05}$',
    '< 3.5', '> 13', '5-10' (range), '2.5 x 10^-3', 'n.d.' -> not detected; footnote marks dropped. Text that
    isn't one of these comes back as `text` only."""
    raw = (cell or "").strip()
    s = raw.translate(_MINUS).replace("$", "").replace("\\pm", "±").replace("+/-", "±").replace("\\times", "×")
    s = re.sub(r"\\,|\\;|\\!|~", " ", s).strip()
    out = CellValue(text=raw)
    if re.fullmatch(r"(n\.?\s?d\.?|not detected|nd|ND|N\.D\.)", s):
        out.detected = "not detected"
        return out
    s = _FOOT.sub("", s).strip()
    m = re.fullmatch(r"(?:(" + _NUMBER + r")\s*[x×]\s*)?10\s*\^\s*\{?\s*([-+]?\d+)\s*\}?", s)
    if m:                                  # a power of ten: '10^{-4}', '2 × 10^{-3}' (truman2024 Table 2)
        out.value = (_float(m.group(1)) if m.group(1) else 1.0) * 10 ** int(m.group(2))
        return out
    m = re.fullmatch(r"([<>≤≥])\s*(" + _NUMBER + r")", s)
    if m:
        out.value, out.limit = _float(m.group(2)), (1 if m.group(1) in "<≤" else -1)
        return out
    m = re.fullmatch(r"(" + _NUMBER + r")\s*±\s*(" + _NUMBER + r")", s)
    if m:
        out.value = _float(m.group(1))
        e = _float(m.group(2))
        out.err_plus, out.err_minus = (e, -e) if e is not None else (0.0, 0.0)
        return out
    scripted = _with_scripts(s)
    if scripted:                         # '1.23^{+0.05}_{-0.04}', '1.557_{-4.2\times 10^{-7}}^{+3.6\times 10^{-7}}'
        out.value, out.err_plus, out.err_minus = scripted
        return out
    m = re.fullmatch(r"(" + _NUMBER + r")\s*-\s*(" + _NUMBER + r")", s)
    if m and _float(m.group(1)) is not None and _float(m.group(2)) is not None \
            and _float(m.group(1)) < _float(m.group(2)) and not re.fullmatch(r"10\s*-\s*\d", s):
        out.value, out.high = _float(m.group(1)), _float(m.group(2))
        return out
    v = _float(s)
    if v is not None:
        out.value = v
        return out
    # a number with its unit in the cell ('45 °C', '2.5 µ L', '10 mM'): the unit kept for conversion
    m = re.fullmatch(r"(" + _NUMBER + r")\s*([^\d\s][^\d]{0,11})", s)
    if m and _float(m.group(1)) is not None and re.search(r"[A-Za-zµ°%Å]", m.group(2)):
        out.value, out.unit = _float(m.group(1)), re.sub(r"\s+", "", m.group(2)) if "µ" in m.group(2) else m.group(2).strip()
    return out


def plain(cell: str) -> str:
    """A cell as plain printed text for readers that take '2.77', '1.2 ± 0.1', '5-10', 'nd' (the chemistry step's
    table cells): footnote marks dropped, powers of ten written out, asymmetric uncertainties as the larger ±."""
    v = cell_value(cell)
    if v.detected:
        return "nd" if v.detected == "not detected" else "detected"
    if v.value is None or v.limit:
        return (cell or "").strip()
    num = f"{v.value:.10g}"
    if v.high:
        return f"{num}-{v.high:.10g}"
    if v.err_plus or v.err_minus:
        return f"{num} ± {max(abs(v.err_plus), abs(v.err_minus)):.10g}"
    return f"{num} {v.unit}".strip()
