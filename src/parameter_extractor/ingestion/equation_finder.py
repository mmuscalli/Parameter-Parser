"""
Find the equations a paper's authors explicitly label, and crop each one as an
image (no API calls).

Strict on purpose (Mickey, 2026-10-15): chemistry papers are full of things
that look like equations (reaction arrows, formulas, rate laws in prose); only
equations the authors highlight with a label count:

  - a display equation with its number set apart at the end or the start of
    the line: "K = [P]/[A][B]      (1)", "(2)   A + B -> C";
  - a line introduced as "Equation 1:", "Eqn. 2", "Eq. (3)".

A "(1)" at the end of a sentence (a citation or a list item) doesn't count:
the number must be separated from the equation by a wide gap, and the
equation part must not read like prose. Sub- and superscripts sit on their
own little lines in the PDF's text, so the crop is widened vertically to take
in nearby smaller text within the equation's horizontal span.

Scanned papers depend on their OCR text layer; equations drawn as images
(reaction schemes) have no text and aren't found -- they're figures.
"""
from __future__ import annotations
import re
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional

from parameter_extractor.schemas.equations import EquationCandidate

RENDER_SCALE = 3.0
LINE_TOLERANCE = 2.5        # points: words this close vertically share a line
BLOCK_LINE_TOLERANCE = 3.5  # around an equation: symbols in a math font sit a little off their line
SEGMENT_GAP = 10.0          # points: a horizontal gap this wide splits a line into segments
LABEL_GAP = 14.0            # points: a label must be at least this far from its equation
PAD = 3.0

_NUMBER = r"[A-Z]?\d{1,3}[a-z]?"                                   # 1, 12, 3a, S1
LABEL = re.compile(rf"[(\[]\s*({_NUMBER})\s*[)\]]")
NAMED = re.compile(rf"^(?:Equation|Eqn\.?|Eq\.?)\s*\(?\s*({_NUMBER})\s*\)?\s*[:.]?\s*(.*)$", re.IGNORECASE)
RELATION = re.compile(r"[=→⇌⇄↔⟶⇀⇋<>≤≥≈∝]")                       # every equation states a relation
NUMERIC_CELL = re.compile(r"[\d.,±−–\-\s()%]+")                     # a table cell, e.g. "2.33±0.05"


def _lines(words: List[dict], tolerance: float = LINE_TOLERANCE) -> List[dict]:
    lines: List[dict] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        for ln in lines:
            if abs(ln["top"] - w["top"]) <= tolerance:
                ln["words"].append(w)
                break
        else:
            lines.append({"top": w["top"], "words": [w]})
    return lines


def _segments(line: dict) -> List[dict]:
    """A line split at wide horizontal gaps (column gutters, equation-number gaps)."""
    segs: List[dict] = []
    for w in sorted(line["words"], key=lambda w: w["x0"]):
        if segs and w["x0"] - segs[-1]["x1"] < SEGMENT_GAP:
            s = segs[-1]
            s["words"].append(w)
            s["x1"], s["bottom"] = max(s["x1"], w["x1"]), max(s["bottom"], w["bottom"])
            s["top"] = min(s["top"], w["top"])
        else:
            segs.append({"x0": w["x0"], "x1": w["x1"], "top": w["top"], "bottom": w["bottom"], "words": [w]})
    for s in segs:
        s["text"] = " ".join(w["text"] for w in s["words"])
    return segs


def _prose(text: str) -> bool:
    """Reads like running text (or has no relation at all) rather than an equation."""
    if not RELATION.search(text):
        return True
    words = text.split()
    alpha = [w for w in words if re.fullmatch(r"[a-z][a-z,.;:]*", w)]
    return len(words) >= 10 and len(alpha) / len(words) > 0.6


def _two_columns(lines: List[dict], page_width: float) -> bool:
    """Most body lines stop short of the middle: a two-column page."""
    mid = page_width / 2
    long_lines = [ln for ln in lines if len(ln["words"]) >= 6]
    if not long_lines:
        return False
    crossing = sum(1 for ln in long_lines if any(s["x0"] < mid - 20 and s["x1"] > mid + 20 for s in _segments(ln)))
    return crossing / len(long_lines) < 0.3


def _side(seg: dict, page_width: float, two_columns: bool) -> str:
    if not two_columns:
        return "page"
    mid = page_width / 2
    return "left" if seg["x1"] <= mid + 5 else ("right" if seg["x0"] >= mid - 5 else "full")


def _prose_line(text: str, width: float, column_width: float) -> bool:
    words = text.split()
    lower = [w for w in words if re.fullmatch(r"[a-z][a-z,.;:()]*", w)]
    return width >= 0.85 * column_width or (len(words) >= 5 and len(lower) / len(words) > 0.6)


def _running_text(ln: dict, margin: float, centre: dict) -> bool:
    """A line of the paragraph around an indented equation: it starts at the column's
    margin and has no math, or reads as words."""
    if not (ln["x0"] <= margin + 3 and centre["x0"] > margin + 10):
        return False
    mathy = RELATION.search(ln["text"]) or "(cid:" in ln["text"]
    words = [w for w in ln["text"].split() if re.fullmatch(r"[a-z]{3,}[,.;:]?", w)]
    return not mathy or len(words) >= 3


def _block(words: List[dict], label_seg: dict, x_lo: float, x_hi: float, column_width: float,
           body_size: float) -> Optional[dict]:
    """The equation next to a label: text within [x_lo, x_hi] on the label's line, plus the
    lines just above and below it (fractions, stacked arrows, sub/superscripts) until a
    line of prose or a gap. None if nothing is there."""
    inside = [w for w in words if w["x0"] >= x_lo and w["x1"] <= x_hi]
    lines = sorted(_lines(inside, BLOCK_LINE_TOLERANCE), key=lambda ln: ln["top"])
    if not lines:
        return None
    for ln in lines:
        ln["x0"] = min(w["x0"] for w in ln["words"])
        ln["x1"] = max(w["x1"] for w in ln["words"])
        ln["bottom"] = max(w["bottom"] for w in ln["words"])
        ln["text"] = " ".join(w["text"] for w in sorted(ln["words"], key=lambda w: w["x0"]))
    mid = (label_seg["top"] + label_seg["bottom"]) / 2
    centre = min(range(len(lines)), key=lambda i: abs((lines[i]["top"] + lines[i]["bottom"]) / 2 - mid))
    c = lines[centre]
    height = max(c["bottom"] - c["top"], 4.0)
    if abs((c["top"] + c["bottom"]) / 2 - mid) > height:
        return None                                    # nothing level with the label
    if _prose_line(c["text"], c["x1"] - c["x0"], column_width):
        return None
    centre_of = lambda ln: (ln["top"] + ln["bottom"]) / 2
    margin = min(ln["x0"] for ln in lines)
    block = [c]
    for step in (-1, 1):                               # grow upwards, then downwards
        i, edge, pending, stop = centre + step, c, [], None
        while 0 <= i < len(lines) and len(block) + len(pending) < 8:
            ln = lines[i]
            gap = (edge["top"] - ln["bottom"]) if step < 0 else (ln["top"] - edge["bottom"])
            if gap > 0.8 * height:
                break
            if _prose_line(ln["text"], ln["x1"] - ln["x0"], column_width) or LABEL.search(ln["text"]):
                stop = ln
                break
            if all(w["size"] < 0.9 * body_size for w in ln["words"]):
                pending.append(ln)                     # a sub/superscript fragment: whose is it?
            elif _running_text(ln, margin, c):         # "0, thus" before lemke2009's eq. 3
                stop = ln
                break
            else:
                block += pending + [ln]                # fraction line, stacked arrow line, ...
                pending = []
            edge, i = ln, i + step
        # fragments belong to the equation only if they're nearer to it than to the line beyond
        # (Zamaraev1996: the "LGG" of the sentence's S_LGG sits just above equation 1)
        for frag in pending:
            near = min(abs(centre_of(frag) - centre_of(b)) for b in block)
            if stop is not None and abs(centre_of(stop) - centre_of(frag)) < near:
                break
            block.append(frag)
    block.sort(key=lambda ln: ln["top"])
    return {"x0": min(l["x0"] for l in block), "x1": max(l["x1"] for l in block),
            "top": min(l["top"] for l in block), "bottom": max(l["bottom"] for l in block),
            "text": " / ".join(l["text"] for l in block), "centre_text": c["text"]}


INDENT = 8.0                # points: a display equation starts at least this far in from the margin


def _margins(lines: List[dict], mid: Optional[float]) -> dict:
    """Left text margin of each column ('left'/'right'), or of the page ('page')."""
    starts: Dict[str, List[float]] = {}
    for ln in lines:
        if len(ln["words"]) < 6:
            continue                                  # body lines only
        for s in _segments(ln):
            key = "page" if mid is None else ("left" if s["x0"] < mid else "right")
            starts.setdefault(key, []).append(s["x0"])
    # the most common start, not the minimum: a stray mark in the margin shouldn't count
    return {k: median(sorted(v)[: max(1, len(v) // 2)]) for k, v in starts.items()}


def _attached_label(seg: dict, margins: dict, mid: Optional[float]):
    """'(N)' as the last word of an indented line -- how OCR'd scans often come out, the
    number close behind the equation rather than set apart. Returns (label word, x-range
    of its equation, column width) or None."""
    words = sorted(seg["words"], key=lambda w: w["x0"])
    if len(words) < 3 or not LABEL.fullmatch(words[-1]["text"].strip()):
        return None
    key = "page" if mid is None else ("left" if seg["x0"] < mid else "right")
    margin = margins.get(key)
    if margin is None or seg["x0"] < margin + INDENT:
        return None                                   # starts at the margin: a sentence, not a display
    lo = 0 if key in ("page", "left") else mid
    hi = (mid if key == "left" else None)
    label = dict(words[-1], text=words[-1]["text"].strip())
    col_width = (hi or label["x1"]) - lo
    return label, (lo, label["x0"] - 0.5), max(col_width, 1.0)


def _find_on_page(page) -> List[dict]:
    words = page.extract_words(x_tolerance=1.5, extra_attrs=["size"])
    if not words:
        return []
    lines = _lines(words)
    two = _two_columns(lines, page.width)
    mid = page.width / 2
    body = median(w["size"] for w in words)
    found = []
    margins = _margins(lines, mid if two else None)
    for line in lines:
        segs = _segments(line)
        for i, seg in enumerate(segs):
            m = LABEL.fullmatch(seg["text"].strip())
            if m:
                side = _side(seg, page.width, two)
                col_lo, col_hi = {"left": (0, mid), "right": (mid, page.width)}.get(side, (0, page.width))
                for x_lo, x_hi in ((col_lo, seg["x0"] - 2), (seg["x1"] + 2, col_hi)):   # "K = ... (1)", "(1) K = ..."
                    b = _block(words, seg, x_lo, x_hi, col_hi - col_lo, body)
                    if b is None:
                        continue
                    gap = seg["x0"] - b["x1"] if x_hi < seg["x0"] else b["x0"] - seg["x1"]
                    table_row = any(NUMERIC_CELL.fullmatch(p) and re.search(r"\d", p)
                                    for p in re.split(r"\s{2,}| / ", b["centre_text"]))
                    # a relation -- or glyphs of a math font the PDF gives no text for ("(cid:5)" is
                    # lemke2009's "="): the image is still right, only the text layer isn't
                    mathy = RELATION.search(b["text"]) or "(cid:" in b["text"]
                    if gap >= LABEL_GAP and not table_row and mathy:
                        found.append({"label": m.group(1), "label_seg": seg, "text": b["text"],
                                      "bbox": [min(b["x0"], seg["x0"]), min(b["top"], seg["top"]),
                                               max(b["x1"], seg["x1"]), max(b["bottom"], seg["bottom"])]})
                        break
                continue
            attached = _attached_label(seg, margins, mid if two else None)
            if attached:                               # OCR'd "... [H+]^b (1)" (eder1994 eq. 1)
                label, (x_lo, x_hi), col_width = attached
                b = _block(words, label, x_lo, x_hi, col_width, body)
                if b is not None and RELATION.search(b["text"]) and not _prose(b["centre_text"]):
                    found.append({"label": LABEL.fullmatch(label["text"]).group(1), "label_seg": label,
                                  "text": b["text"],
                                  "bbox": [b["x0"], min(b["top"], label["top"]), label["x1"],
                                           max(b["bottom"], label["bottom"])]})
                continue
            m = NAMED.match(seg["text"].strip())
            if m and m.group(2) and RELATION.search(m.group(2)) and not _prose(m.group(2)):   # "Equation 1: K = ..."
                found.append({"label": m.group(1), "label_seg": None, "text": m.group(2),
                              "bbox": [seg["x0"], seg["top"], seg["x1"], seg["bottom"]]})
    return found


def find_equations(pdf_path: str, out_dir: Path, render_scale: float = RENDER_SCALE) -> List[EquationCandidate]:
    """Labelled equations, in page order, each with a cropped image in out_dir."""
    import pypdfium2 as pdfium
    from parameter_extractor.ingestion.pdf_parser import open_plumber, render_offset, to_render_box

    out_dir = Path(out_dir)
    hits: List[tuple] = []
    with open_plumber(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for eq in _find_on_page(page):
                hits.append((page_no, eq))
    if not hits:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(pdf_path)
    rendered: Dict[int, object] = {}
    result: List[EquationCandidate] = []
    seen = set()
    try:
        for page_no, eq in hits:
            key = (eq["label"], eq["text"])
            if key in seen:                     # the same equation repeated (e.g. running header)
                continue
            seen.add(key)
            if page_no not in rendered:
                rendered[page_no] = doc[page_no - 1].render(scale=render_scale).to_pil().convert("RGB")
            x0, top, x1, bottom = to_render_box(eq["bbox"], render_offset(doc[page_no - 1]))
            box = [round(v * render_scale) for v in (x0 - PAD, top - PAD, x1 + PAD, bottom + PAD)]
            n = sum(1 for e in result if e.label == eq["label"])
            name = f"eq-{eq['label']}{'-' + str(n + 1) if n else ''}-p{page_no}.png"
            rendered[page_no].crop(box).save(out_dir / name)
            result.append(EquationCandidate(label=eq["label"], page=page_no, bbox=eq["bbox"],
                                            text=eq["text"], image=str(out_dir / name)))
    finally:
        doc.close()
    return result
