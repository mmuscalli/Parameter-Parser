"""
Where a value is in a saved table image (Mickey, 2026-11-12: the Flagged values window highlights it). Local only,
no model: the table crops (tables/table-N.png, ingestion/table_finder.py) are renders of the PDF, and the PDF's text
layer says where every word is, so the words that carry a cell's value can be boxed on the crop.

- `TableWords(pdf, entry)`: the words inside a tables.json entry's crop, in the crop's pixels. New runs save where
  the crop sits on its page (`crop_px`, `scale`); for older runs it's found by matching the crop against the page
  render (only the left edge is unknown: the crop was widened to the table's ink).
- `locate(words, value, quote)`: boxes for the words equal to the cell's value; else, for a value the app converted
  ('2500 mM' from '2.50 mol dm-3'), the numbers of the cell's quote where they occur close together (the quote of a
  table cell names its row: '2.50 mol dm-3 80 C'). Text values: their distinctive words.
Not covered: landscape pages shown whole, pages without a text layer (a scan with no OCR), digitized figures.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

Box = Tuple[float, float, float, float]          # x0, y0, x1, y1 in the crop's pixels
_NUMBER = re.compile(r"(?<![A-Za-z\d.])[-−+]?\d+(?:\.\d+)?(?![\d])")
_WORD_NUMBER = re.compile(r"^[(\[<>~≈±]*([-−+]?\d+(?:\.\d+)?)[)\]%,;:*a-z†‡§¶]{0,2}$")


@dataclass
class Word:
    text: str
    box: Box

    @property
    def number(self) -> Optional[float]:
        m = _WORD_NUMBER.match(self.text.strip())
        return float(m.group(1).replace("−", "-")) if m else None


def numbers_in(text: str) -> List[float]:
    """The numbers of a value or quote as printed -- not exponents or charges glued to a word ('dm-3', 'Ca2+')."""
    out = []
    for m in _NUMBER.finditer(text or ""):
        text = text or ""
        tail = text[m.end():m.end() + 1]
        if tail and tail in "+-":                   # 'Ca2+' -- a charge
            continue
        if re.search(r"[A-Za-z][-−]$", text[:m.start()]) or re.search(r"[A-Za-z][-−]?$", text[:m.start()]) and \
                m.group(0)[0] in "-−":              # 'dm-3' -- an exponent
            continue
        out.append(float(m.group(0).replace("−", "-")))
    return out


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


class TableWords:
    """The words of one saved table crop, positioned on the crop image."""

    def __init__(self, pdf: Path, entry: dict):
        self.words: List[Word] = []
        self.problem = ""
        if entry.get("turned"):
            self.problem = "a landscape page shown whole: values aren't located on it"
            return
        if not entry.get("box") or not entry.get("page_no") or not entry.get("image"):
            self.problem = "this table's position on its page wasn't saved"
            return
        try:
            self._read(Path(pdf), entry)
        except Exception as e:                       # never stops the window: just no highlights
            self.problem = f"the PDF couldn't be read here ({type(e).__name__})"

    def _read(self, pdf: Path, entry: dict) -> None:
        import pdfplumber
        import pypdfium2 as pdfium
        from PIL import Image
        from parameter_extractor.ingestion.pdf_parser import render_offset, to_render_box
        from parameter_extractor.ingestion.table_finder import RENDER_SCALE
        scale = float(entry.get("scale") or RENDER_SCALE)
        doc = pdfium.PdfDocument(str(pdf))
        try:
            page = doc[entry["page_no"] - 1]
            offset = render_offset(page)
            if entry.get("crop_px"):
                x0, y0 = entry["crop_px"][:2]
            else:
                x0, y0 = _find_crop(page, entry, offset, scale, Image.open(entry["image"]))
        finally:
            doc.close()
        with pdfplumber.open(str(pdf)) as plumber:
            page = plumber.pages[entry["page_no"] - 1]
            words = page.extract_words(x_tolerance=1.5, keep_blank_chars=False, use_text_flow=False)
        width, height = Image.open(entry["image"]).size
        for w in words:
            bx = [v * scale for v in to_render_box((w["x0"], w["top"], w["x1"], w["bottom"]), offset)]
            box = (bx[0] - x0, bx[1] - y0, bx[2] - x0, bx[3] - y0)
            if box[2] < 0 or box[3] < 0 or box[0] > width or box[1] > height:
                continue
            self.words.append(Word(w["text"], box))
        if not self.words:
            self.problem = "the PDF has no text layer on this table (an image): values aren't located"


def _find_crop(page, entry: dict, offset, scale: float, crop) -> Tuple[int, int]:
    """(left, top) of an older run's crop on the page render: top from the saved box, left by matching the crop."""
    import numpy as np
    from parameter_extractor.ingestion.pdf_parser import to_render_box
    box = [round(v * scale) for v in to_render_box(entry["box"], offset)]
    img = np.asarray(page.render(scale=scale).to_pil().convert("L"), dtype=np.int16)
    tpl = np.asarray(crop.convert("L"), dtype=np.int16)
    h, w = tpl.shape
    best, best_x, best_y = None, box[0], box[1]
    for dy in (0, -1, 1):
        y = box[1] + dy
        if y < 0 or y + h > img.shape[0]:
            continue
        strip = img[y:y + h:3]
        sub = tpl[::3, ::3]
        for x in range(max(0, box[0] - 400), min(img.shape[1] - w, box[0] + 2) + 1):
            diff = np.abs(strip[:, x:x + w:3] - sub).mean()
            if best is None or diff < best:
                best, best_x, best_y = diff, x, y
    return best_x, best_y


def locate(words: List[Word], value: str, quote: str = "") -> Tuple[List[Box], str]:
    """(boxes, how they were found) for one cell."""
    if not words:
        return [], ""
    value = (value or "").strip()
    wanted = numbers_in(value) if re.fullmatch(r"[-−+]?\d+(?:\.\d+)?", value) else []
    if wanted:
        hits = [w for w in words if w.number is not None and any(_same(w.number, n) for n in wanted)]
        if hits:
            return [w.box for w in hits], "the value"
    quoted = [n for n in numbers_in(quote)]
    if quoted:
        boxes = _near_each_other(words, quoted)
        if boxes:
            return boxes, "the numbers of its quote"
    if value and not wanted:                        # a text value: its words
        terms = {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9+\-]{3,}", value)}
        hits = [w for w in words if re.sub(r"[^\w+\-]", "", w.text).lower() in terms]
        if hits:
            return [w.box for w in hits], "the words of the value"
    return [], ""


def _near_each_other(words: List[Word], quoted: List[float]) -> List[Box]:
    """The quote's numbers where they occur together: anchored on its rarest number, the occurrence with most of the
    others close by (a few lines down, a third of the table across), plus the nearest of each other number."""
    occ: Dict[float, List[Word]] = {}
    for n in dict.fromkeys(quoted):
        found = [w for w in words if w.number is not None and _same(w.number, n)]
        if found:
            occ[n] = found
    if not occ:
        return []
    line = sorted(w.box[3] - w.box[1] for w in words)[len(words) // 2] or 10.0
    span = max(w.box[2] for w in words) - min(w.box[0] for w in words)

    def close(a: Word, b: Word) -> bool:
        return abs(a.box[1] - b.box[1]) <= 3.5 * line and abs(a.box[0] - b.box[0]) <= span / 3

    anchor = min(occ, key=lambda n: len(occ[n]))
    scored = [(sum(any(close(a, o) for o in occ[n]) for n in occ if n != anchor), a) for a in occ[anchor]]
    top = max(s for s, _ in scored)
    if len(occ) > 1 and top == 0 and len(occ[anchor]) > 1:
        return []                                    # the numbers never occur together: not this table's cell
    def dist(a: Word, o: Word) -> float:
        return abs(o.box[1] - a.box[1]) + abs(o.box[0] - a.box[0])

    def group(a: Word) -> Tuple[float, List[Box]]:
        boxes, total = [a.box], 0.0
        for n in occ:
            near = [o for o in occ[n] if n != anchor and close(a, o)]
            if near:
                b = min(near, key=lambda o: dist(a, o))
                boxes.append(b.box)
                total += dist(a, b)
        return total, boxes

    # the tightest group wins (eder1994 Table 2: '2.50 mol dm-3 80 °C' and '... 87 °C' blocks both print 2.50);
    # groups equally tight are all shown
    groups = [group(a) for s, a in scored if s == top]
    tightest = min(t for t, _ in groups)
    return list(dict.fromkeys(b for t, boxes in groups if t <= tightest + 1 for b in boxes))
