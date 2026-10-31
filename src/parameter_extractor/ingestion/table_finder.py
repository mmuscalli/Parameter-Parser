"""
Find each table ("Table 1", "Table S2") on the pages the parser marked as table pages and save a
crop of it -- caption + table + footnotes -- so values and flags can be checked against the table
itself (Mickey, 2026-10-31: the Tables tab, like the Figures tab). Local, no API call.

Works on the text layer like the figure finder (ingestion/figure_finder.py), column by column:
  - the caption is a line starting "Table N" (whitespace removed, so OCR letter-spacing doesn't
    hide it), with text after the number -- running text citing a table ("Table 1 shows ...") is
    rejected because no table follows it;
  - the table is the block BELOW its caption: lines in the caption's column (or across the page
    when the table's rows cross the middle), down to the next caption, a large vertical gap, or two
    lines of running text in a row (footnotes, single lines, are kept);
  - a caption with no table below it (journals that caption tables underneath) takes the block
    above instead;
  - a page the parser read turned (landscape tables) is saved whole, upright, cropped to its content.
It's an estimate, for reference: the crop is never used to read values (the model reads the
rasterized pages, ingestion/pdf_parser.rasterize_table_pages).
"""
from __future__ import annotations
import re
import statistics
from pathlib import Path
from typing import Dict, List, Optional

from parameter_extractor.ingestion.figure_finder import (CAPTION_RE as FIGURE_CAPTION_RE, _caption_text,
                                                         _continues_across, _group_lines, _is_body_line,
                                                         drop_overprinted)

TABLE_RE = re.compile(r"^(?:Table|TABLE)\.?([A-Z]?)(\d{1,2})(?![\d(])")    # 'Table 2', 'Table S1', 'Table A1'

RENDER_SCALE = 2.5          # 180 dpi: readable on screen, small files
MIN_TABLE_HEIGHT = 18.0     # points below (or above) the caption
MARGIN = 4.0


def _words(page) -> List[dict]:
    from parameter_extractor.ingestion.pdf_parser import (MERGED_WORDS_THRESHOLD, TIGHT_X_TOLERANCE,
                                                          _merged_word_ratio)
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["size"])
    if _merged_word_ratio(" ".join(w["text"] for w in words)) > MERGED_WORDS_THRESHOLD:
        tight = page.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["size"],
                                   x_tolerance=TIGHT_X_TOLERANCE)
        if _merged_word_ratio(" ".join(w["text"] for w in tight)) < _merged_word_ratio(" ".join(w["text"] for w in words)):
            words = tight
    return drop_overprinted([w for w in words if w.get("upright", True)])


def _is_running_text(line: dict, width: float) -> bool:
    """A line of the paper's running text: long, mostly words, ordinary word gaps. A wide table row is
    long too, but has column gaps (eder1994's scanned Table 1) or is mostly numbers."""
    if not _is_body_line(line, width):
        return False
    words = line["words"]
    size = statistics.median(w.get("size", 10) for w in words) or 10
    gaps = [b["x0"] - a["x1"] for a, b in zip(words, words[1:])]
    numeric = sum(any(ch.isdigit() for ch in w["text"]) for w in words) / len(words)
    return (max(gaps, default=0) < 1.2 * size) and numeric < 0.35


def _is_caption(line: dict) -> bool:
    return bool(TABLE_RE.match(line["compact"]) or FIGURE_CAPTION_RE.match(line["compact"]))


def _running(line: dict, width: float, mid: Optional[float]) -> bool:
    """Running text -- for a full-width block (`mid` given), in either half: below a full-width table
    the two columns of text share a line, with the column gap in the middle (eder1994 Table 1)."""
    if mid is None:
        return _is_running_text(line, width)
    halves = ([w for w in line["words"] if w["x1"] <= mid + 4], [w for w in line["words"] if w["x0"] >= mid - 4])
    return _is_running_text(line, width) or any(
        h and _is_running_text(dict(line, words=h, x0=h[0]["x0"], x1=h[-1]["x1"],
                                    compact="".join(w["text"] for w in h)), mid)
        for h in halves)


def _block(lines: List[dict], start: int, step: int, width: float, line_h: float,
           mid: Optional[float] = None) -> List[dict]:
    """Lines from lines[start] onwards (step +1 down, -1 up) that belong to the table."""
    out, body_run = [], 0
    i = start
    while 0 <= i < len(lines):
        ln = lines[i]
        prev = out[-1] if out else None
        if prev is not None:
            gap = (ln["top"] - prev["bottom"]) if step > 0 else (prev["top"] - ln["bottom"])
            if gap > 4 * line_h:
                break
        if _is_caption(ln):
            break
        body_run = body_run + 1 if _running(ln, width, mid) else 0
        if body_run >= 2:
            out.pop()                     # the first of two running-text lines isn't the table's
            break
        out.append(ln)
        i += step
    return out


def _find_on_page(page, page_no: int) -> List[dict]:
    words = _words(page)
    if not words:
        return []
    mid = page.width / 2
    by_col: Dict[str, List[dict]] = {"left": [], "right": [], "full": []}
    for w in words:
        by_col["left" if w["x1"] <= mid + 4 else "right" if w["x0"] >= mid - 4 else "full"].append(w)
    lines_all = _group_lines(words)
    one_column = sum(1 for l in lines_all if l["x0"] < mid - 20 and l["x1"] > mid + 20 and
                     not any(b["x0"] - a["x1"] > 15 and a["x1"] <= mid + 4 <= b["x0"] + 8
                             for a, b in zip(l["words"], l["words"][1:]))) > 0.4 * len(lines_all)
    if one_column:                        # lines run across the middle: the page is one column
        by_col = {"left": [], "right": [], "full": words}
    lines = {c: _group_lines(ws) for c, ws in by_col.items()}
    found = []
    for col in ("left", "right", "full"):
        for i, ln in enumerate(lines[col]):
            m = TABLE_RE.match(ln["compact"])
            if not m or len(ln["compact"]) - m.end() < 1:
                continue
            line_h = max(ln["bottom"] - ln["top"], 6.0)
            # the caption: following lines of the same column, closely spaced
            caption = [ln]
            for nxt in lines[col][i + 1:]:
                if (nxt["top"] - caption[-1]["bottom"] > 0.9 * line_h + 2 or _is_caption(nxt)
                        or abs(nxt["x0"] - ln["x0"]) > 15):        # another column's line beside it
                    break
                if len(caption) >= 4:
                    break
                caption.append(nxt)
            wide = col == "full" or _continues_across(ln, words, mid)
            top, bottom = caption[0]["top"] - 1, caption[-1]["bottom"]
            # the table's lines: its column's, or the whole width's when its rows cross the middle
            col_words = words if wide else by_col[col] + by_col["full"]
            band = _group_lines([w for w in col_words if w["top"] > bottom + 0.5])
            if not wide:
                crossing = [w for w in by_col["full"] if bottom < w["top"] < bottom + 12 * line_h]
                if crossing:                   # rows run across the middle: a full-width table
                    wide = True
                    band = _group_lines([w for w in words if w["top"] > bottom + 0.5])
            if wide and col != "full":          # the caption's lines were cut at the middle: rebuild them
                cap_band = [w for w in words if caption[0]["top"] - 2 <= w["top"] <= caption[-1]["bottom"]]
                caption = _group_lines(cap_band) or caption
            width = page.width if wide else mid
            below = _block(band, 0, 1, width, line_h, mid if wide and not one_column else None)
            region = below
            if not below or below[-1]["bottom"] - top < MIN_TABLE_HEIGHT + (bottom - top):
                above = _group_lines([w for w in (words if wide else by_col[col] + by_col["full"])
                                      if w["bottom"] < top - 0.5])
                region = list(reversed(_block(above, len(above) - 1, -1, width, line_h,
                                              mid if wide and not one_column else None)))
                if not region or bottom - region[0]["top"] < MIN_TABLE_HEIGHT + (bottom - top):
                    continue                   # no table next to it: a sentence citing a table
            x0s = [l["x0"] for l in region + caption]
            x1s = [l["x1"] for l in region + caption]
            box = (max(min(x0s) - MARGIN, 0.0), max(min(top, region[0]["top"]) - MARGIN, 0.0),
                   min(max(x1s) + MARGIN, page.width), min(max(bottom, region[-1]["bottom"]) + MARGIN, page.height))
            found.append({"number": int(m.group(2)), "letter": m.group(1), "page_no": page_no,
                          "caption": _caption_text(caption), "box": box,
                          "size": statistics.mean(w["size"] for l in caption for w in l["words"]),
                          "height": box[3] - box[1],
                          "xrange": (0.0, page.width) if wide or one_column else
                                    ((0.0, mid + 4) if col == "left" else (mid - 4, page.width))})
    return found


def find_tables(pdf_path: str, pages: List[int], out_dir: Path, supplement: bool = False,
                page_offset: int = 0, rotations: Optional[Dict[int, int]] = None,
                captions: Optional[Dict[int, List[str]]] = None) -> List[dict]:
    """[{table_id, number, page, page_label, caption, image}] for the tables on `pages` (1-based, of
    this PDF) -- crops saved in out_dir as table-N.png ('table-SN.png' for a supplement, whose ids are
    'Table SN'). `page` is in the paper's numbering (page_offset added for a supplement)."""
    import pypdfium2 as pdfium
    from parameter_extractor.ingestion.pdf_parser import open_plumber, render_offset, to_render_box
    from parameter_extractor.ingestion.table_tiles import _content_box, _ink
    rotations = rotations or {}
    with open_plumber(pdf_path) as doc:
        caps = [c for p in pages if 1 <= p <= len(doc.pages) and not rotations.get(p)
                for c in _find_on_page(doc.pages[p - 1], p)]
    turned = [p for p in pages if rotations.get(p)]
    best: Dict[tuple, dict] = {}     # (letter, number): Table 1 and Table A1 (appendix) are different tables
    for c in caps:                   # one per table: the caption with the biggest table next to it
        key = ("S" if supplement else c["letter"], c["number"])
        if key not in best or c["height"] > best[key]["height"]:
            best[key] = c
    if not best and not turned:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    sp = "S" if supplement else ""       # a supplement's page names
    pdf = pdfium.PdfDocument(pdf_path)
    tables = []
    try:
        for (prefix, number) in sorted(best, key=lambda k: (k[0] != "", k[0], k[1])):
            c = best[(prefix, number)]
            page = pdf[c["page_no"] - 1]
            img = page.render(scale=RENDER_SCALE).to_pil().convert("RGB")
            offset = render_offset(page)
            box = [round(v * RENDER_SCALE) for v in to_render_box(c["box"], offset)]
            # widen to the ink across the table's rows, within its column: a scan's OCR text layer can
            # miss whole columns (eder1994 Table 2's (Gly)3)
            lo, hi = (round(v * RENDER_SCALE) for v in to_render_box((c["xrange"][0], 0, c["xrange"][1], 0), offset)[::2])
            lo, hi = max(lo, 0), min(hi, img.width)
            ink = _ink(img.crop((lo, box[1], hi, box[3])))
            cols = ink.sum(axis=0).nonzero()[0] if ink.size else []
            if len(cols):
                box[0], box[2] = min(box[0], lo + int(cols[0]) - 6), max(box[2], lo + int(cols[-1]) + 6)
            path = out_dir / f"table-{prefix}{number}.png"
            img.crop(box).save(path)
            tables.append({"table_id": f"Table {prefix}{number}", "number": number, "prefix": prefix,
                           "page": c["page_no"] + page_offset,
                           "page_label": f"S{c['page_no']}" if supplement else str(c["page_no"]),
                           "caption": c["caption"], "image": str(path)})
        for p in turned:              # landscape page: the whole page, upright, cropped to its content
            img = pdf[p - 1].render(scale=RENDER_SCALE, rotation=rotations[p]).to_pil().convert("RGB")
            x0, y0, x1, y1 = _content_box(_ink(img))
            # named by the caption the parser found on it (faisal2005 p. 3: 'Table 1. Reaction Products ...')
            caption = next((c for c in (captions or {}).get(p + page_offset, [])
                            if TABLE_RE.match(re.sub(r"\s+", "", c))), "")
            m = TABLE_RE.match(re.sub(r"\s+", "", caption))
            number = int(m.group(2)) if m else 0
            prefix = sp or (m.group(1) if m else "")
            if m and (prefix, number) in best:
                continue                              # already cropped from an upright page
            path = out_dir / (f"table-{prefix}{number}.png" if m else f"table-page-{sp}{p}.png")
            img.crop((max(x0 - 10, 0), max(y0 - 10, 0), x1 + 10, y1 + 10)).save(path)
            tables.append({"table_id": f"Table {prefix}{number}" if m else f"Table on page {sp}{p}",
                           "number": number, "prefix": prefix, "page": p + page_offset,
                           "page_label": f"S{p}" if supplement else str(p),
                           "caption": (caption + " " if caption else "") + "(landscape page, shown whole)",
                           "image": str(path)})
    finally:
        pdf.close()
    tables.sort(key=lambda t: (t["number"] == 0, t.get("prefix", "") != "", t.get("prefix", ""), t["number"]))
    return tables
