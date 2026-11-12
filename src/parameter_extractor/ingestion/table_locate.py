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
# scientific notation as printed or quoted: '3e-4', '1.2E+03', '3×10-4', '3 × 10^-4', '3x10−4', '3·10(-4)' (Cleaves2008,
# 2026-11-12: quotes like '3×10-4 M 3e-4')
_SCI = re.compile(r"(?<![\w.])([-−+]?\d+(?:\.\d+)?)\s*(?:[eE]\s*([-−+]?\d+)|[x×✕·*]\s*10\s*(?:\^|\*\*)?\s*\(?\s*([-−+–]?\s*\d+)\)?)")
# a power of ten alone: '10-9 M', '10^-9'
_POWER = re.compile(r"(?<![\w.])10\s*(?:\^|\*\*)\s*\(?([-−+–]?\d+)\)?|(?<![\w.])10([-−–]\d+)(?!\d)")
_NUMBER = re.compile(r"(?<![A-Za-z\d.])[-−+]?\d+(?:\.\d+)?(?![\d])")
# a number with a unit stuck to it counts as that number ('25°C', '300 °C' read as one word, '5%')
_WORD_NUMBER = re.compile(r"^[(\[<>~≈±]*([-−+]?\d+(?:\.\d+)?)(?:\s?[°º]\s?[CFK]?|[)\]%,;:*a-z†‡§¶]{0,2})[,;)]?$")


@dataclass
class Word:
    text: str
    box: Box

    @property
    def number(self) -> Optional[float]:
        text = self.text.strip()
        sci, rest = sci_numbers(text)
        if len(sci) == 1 and not re.sub(r"[\s()\[\]%,;:*]", "", rest):
            return sci[0]
        m = _WORD_NUMBER.match(text)
        return float(m.group(1).replace("−", "-")) if m else None


def _exponent(text: str) -> int:
    return int(re.sub(r"\s", "", text).replace("−", "-").replace("–", "-"))


def sci_numbers(text: str) -> Tuple[List[float], str]:
    """(the values written in scientific notation, the text with them blanked out)."""
    values = []

    def take(m):
        mantissa = float(m.group(1).replace("−", "-"))
        exp = m.group(2) or m.group(3)
        values.append(mantissa * 10 ** _exponent(exp))
        return " " * len(m.group(0))

    text = _SCI.sub(take, text or "")

    def power(m):
        values.append(10.0 ** _exponent(m.group(1) or m.group(2)))
        return " " * len(m.group(0))

    return values, _POWER.sub(power, text)


def numbers_in(text: str) -> List[float]:
    """The numbers of a value or quote as printed -- not exponents or charges glued to a word ('dm-3', 'Ca2+');
    scientific notation as one number ('3×10-4' = 0.0003)."""
    sci, text = sci_numbers(text or "")
    out = list(sci)
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
    if a == b:
        return True
    if a and b and (abs(a) < 1e-3 or abs(b) < 1e-3 or abs(a) > 1e6):       # small / large: relative only
        return abs(a - b) <= 1e-6 * max(abs(a), abs(b))
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def joined_words(words: List["Word"]) -> List["Word"]:
    """The words plus scientific notation split over two or three words of one line ('3×10' + a raised '−4',
    '3' '×' '10−4'), joined into one word with their boxes merged. Words are on one line when their boxes overlap
    vertically (a superscript sits a little higher)."""
    out = list(words)

    def right_of(w: "Word") -> Optional["Word"]:
        height = w.box[3] - w.box[1]
        nxt = [o for o in words if o is not w and o.box[0] >= w.box[2] - 1 and o.box[0] - w.box[2] <= height
               and min(o.box[3], w.box[3]) - max(o.box[1], w.box[1]) > 0]
        return min(nxt, key=lambda o: o.box[0]) if nxt else None

    for w in words:
        group = [w]
        for _ in (2, 3):
            n = right_of(group[-1])
            if n is None:
                break
            group.append(n)
            text = "".join(g.text for g in group)
            if not re.search(r"10|[eE]", text):
                continue
            joined = Word(text, (min(g.box[0] for g in group), min(g.box[1] for g in group),
                                 max(g.box[2] for g in group), max(g.box[3] for g in group)))
            if joined.number is not None and (_SCI.search(text) or _POWER.search(text)):
                out.append(joined)
    return out


class TableWords:
    """The words of one saved table crop, positioned on the crop image."""

    def __init__(self, pdf, entry: dict):
        self.words: List[Word] = []
        self.problem = ""
        self.how = "the PDF's text"
        if entry.get("turned"):
            self.problem = "a landscape page shown whole: values aren't located on it"
        elif not entry.get("box") or not entry.get("page_no") or not entry.get("image"):
            self.problem = "this table's position on its page wasn't saved"
        elif not pdf or not Path(pdf).is_file():
            self.problem = "the paper's PDF isn't where the run read it"
        else:
            try:
                self._read(Path(pdf), entry)
            except Exception as e:                   # never stops the window: just no highlights
                self.problem = f"the PDF couldn't be read here ({type(e).__name__})"
        if self.problem and entry.get("image") and Path(entry["image"]).is_file():
            self._recognise(Path(entry["image"]))

    def _recognise(self, image: Path) -> None:
        """No usable text layer: the values read from the table's image (macOS text recognition, table_ocr.py)."""
        from parameter_extractor.ingestion import table_ocr
        if not table_ocr.available():
            return
        try:
            found = table_ocr.words(image)
        except Exception:                            # (the text layer's reason stays the problem)
            return
        if found:
            self.words, self.problem, self.how = found, "", "text recognition on the image"

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
        caption_bottom = (entry["caption_box"][1] - entry["box"][1]) * scale if entry.get("caption_box") else 0
        body_numbers = [w for w in self.words if w.box[1] > caption_bottom and w.number is not None]
        if not self.words:
            self.problem = "the PDF has no text layer on this table (an image): values aren't located"
        elif len(body_numbers) < 3:
            self.problem = ("the PDF has no text for this table's values (drawn as shapes or an image -- only its "
                            "caption is text): values aren't located")


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
    words = joined_words(words)
    value = (value or "").strip()
    wanted = numbers_in(value) if re.fullmatch(r"[-−+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", value) else []
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
        dy = abs(a.box[1] - b.box[1])
        return dy <= 0.6 * line or (dy <= 3.5 * line and abs(a.box[0] - b.box[0]) <= span / 3)   # same line: close

    # the rarest number; among equally rare ones the LAST in the quote -- a table cell's quote is '<row> <value>'
    order = list(dict.fromkeys(quoted))
    anchor = min(occ, key=lambda n: (len(occ[n]), -order.index(n)))
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
