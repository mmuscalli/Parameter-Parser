"""
Text recognition for scanned pages (Mickey, 2026-11-14: the pack study's Flores1973, Inoue1993 and Rabinowitz1969 are
scans -- no text layer, so no rows). macOS only, like table_ocr.py: the system's Vision framework, offline and free;
elsewhere `available()` is False and a scanned paper is refused as before.

A page needs it when its text layer is (nearly) empty but the page carries an image: `needs_ocr`. Inoue1993's only
text is a library's watermark line, so this is decided page by page, not by "no text at all".

`page_text(pdf, page)` renders the page and returns its text in reading order. Vision returns lines without columns;
the old two-column journal pages would interleave, so lines are put back in order: a line spanning the middle of the
page (a title, a caption, a full-width table row) starts a new band, and within a band the left column's lines come
before the right column's. Lookalike characters in numbers are mapped back as for tables (table_ocr._clean),
and a raised decimal point ('0•28') becomes '.'.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from parameter_extractor.ingestion.table_ocr import _clean, available  # noqa: F401 -- available re-exported

MIN_TEXT_CHARS = 200          # a page with fewer characters in its text layer (a watermark, a page number) is a scan
RENDER_DPI = 300


_RAISED_DOT = re.compile(r"(?<=\d)[•·∙⋅](?=\d)")


def clean(text: str) -> str:
    """Recognized text with lookalikes in numbers mapped back (table_ocr._clean), and a raised decimal point read as
    a bullet ('0•28', old Nature typesetting) made a point -- between two digits it is never a bullet."""
    return _RAISED_DOT.sub(".", _clean(text))


def needs_ocr(text: str, image_count: int) -> bool:
    """A scanned page: (almost) no text layer, but an image on the page."""
    return image_count > 0 and len("".join(text.split())) < MIN_TEXT_CHARS


Line = Tuple[str, Tuple[float, float, float, float]]          # text, (x0, top, x1, bottom) as fractions of the page


def recognize(image: Path) -> List[Line]:
    """The text lines Vision finds in an image, with their boxes (fractions of the image, top-left origin)."""
    import Quartz
    import Vision
    from Foundation import NSURL
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(image)), None)
    if src is None:
        return []
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if img is None:
        return []
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(True)                   # prose; numbers are cleaned after (_clean)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    ok, _err = handler.performRequests_error_([request], None)
    if not ok:
        return []
    lines = []
    for obs in request.results() or []:
        text = str(obs.topCandidates_(1)[0].string())
        bb = obs.boundingBox()
        top = 1 - bb.origin.y - bb.size.height                  # Vision's origin is bottom-left
        lines.append((clean(text), (bb.origin.x, top, bb.origin.x + bb.size.width, top + bb.size.height)))
    return lines


def _rows(lines: List[Line]) -> List[Line]:
    """Pieces of one printed line merged: Vision splits a line where a sentence ends mid-line ('...the coordinated
    form.' | 'The doped dipyridyl sample was'), with tops a pixel apart -- sorted by top alone, the second piece came
    first. Pieces whose vertical extents overlap by half a line and that sit in the same column join, left to right."""
    rows: List[List[Line]] = []
    for line in sorted(lines, key=lambda ln: ln[1][1]):
        x0, top, x1, bottom = line[1]
        side = (x0 + x1) / 2 < 0.5
        for row in rows:
            r0, rt, r1, rb = row[0][1]
            same_side = ((r0 + r1) / 2 < 0.5) == side or (x0 < 0.45 and x1 > 0.55) or (r0 < 0.45 and r1 > 0.55)
            if same_side and min(bottom, rb) - max(top, rt) >= 0.5 * min(bottom - top, rb - rt):
                row.append(line)
                break
        else:
            rows.append([line])
    merged = []
    for row in rows:
        row.sort(key=lambda ln: ln[1][0])
        box = (min(ln[1][0] for ln in row), min(ln[1][1] for ln in row), max(ln[1][2] for ln in row),
               max(ln[1][3] for ln in row))
        merged.append((" ".join(t for t, _ in row), box))
    return merged


def reading_order(lines: List[Line]) -> List[str]:
    """Lines in reading order for one- and two-column pages (module text)."""
    lines = sorted(_rows(lines), key=lambda ln: (ln[1][1], ln[1][0]))
    out: List[str] = []
    band: List[Line] = []

    def flush():
        left = [ln for ln in band if (ln[1][0] + ln[1][2]) / 2 < 0.5]
        right = [ln for ln in band if (ln[1][0] + ln[1][2]) / 2 >= 0.5]
        out.extend(t for t, _ in left)
        out.extend(t for t, _ in right)
        band.clear()

    for line in lines:
        x0, _top, x1, _bottom = line[1]
        if x0 < 0.45 and x1 > 0.55:             # spans the middle: full width, ends the band
            flush()
            out.append(line[0])
        else:
            band.append(line)
    flush()
    return out


def page_text(pdf_path: str, page_number: int, rotation: int = 0) -> str:
    """The recognized text of one page (1-indexed), in reading order; '' if nothing was recognized."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf_path)
    try:
        bitmap = doc[page_number - 1].render(scale=RENDER_DPI / 72, rotation=rotation)
        image = bitmap.to_pil().convert("L")
    finally:
        doc.close()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.png"
        image.save(path)
        return "\n".join(reading_order(recognize(path)))


def recognize_pages(pdf_path: str, pages: List[int], rotations: Optional[dict] = None) -> dict:
    """{page: text} for the pages asked for; pages with nothing recognized are left out."""
    out = {}
    for n in pages:
        text = page_text(pdf_path, n, (rotations or {}).get(n, 0))
        if text.strip():
            out[n] = text
    return out
