"""
Find "Fig. N" / "Figure N" captions and estimate each figure's area on the
page, then render the pages so a user can digitize the plots.

Works on the text layer, column by column, because:
  - two-column papers put a caption mid-line if lines are read across the
    page (eder1994's Fig. 1 caption sits in the right column);
  - OCR'd scans can space letters out ("F i g . 2 T h e ..."), so captions
    are matched on the line's text with whitespace removed;
  - scanned papers have no separate figure images (each page is one image),
    so the figure's area has to be inferred from the surrounding text.

Area heuristic: the figure is the space above its caption, in the caption's
column, up to the nearest line of body text (a long line with many words --
axis labels and tick values are short). It's an estimate: the digitizer shows
the whole page zoomed to it, so a wrong guess only costs some panning.
"""
from __future__ import annotations
import re
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from parameter_extractor.schemas.figures import BBox, FigureCandidate

# Captions start with a capital ("Fig. 3", "Figure 3", "FIG. 3"); a lowercase "figure 13,
# ref. 2)" at the start of a line is running text citing another paper (truman2024).
# an appendix's letter is part of the number ('Figure A1', Riggi2023); 'S' is left to supplements, so a
# line of the paper citing 'Figure S1' isn't taken for a caption
CAPTION_RE = re.compile(r"^(?:Fig(?:ure)?|FIG(?:URE)?)\.?([A-RT-Z]?)(\d{1,2})(?![\d(])")
# in a supplement: 'Figure S1' (or the supplement's own 'Figure 1')
SI_CAPTION_RE = re.compile(r"^(?:Fig(?:ure)?|FIG(?:URE)?)\.?(S?)(\d{1,2})(?![\d(])")
MIN_FIGURE_HEIGHT = 30.0    # points; a smaller area means the "caption" wasn't one
RENDER_SCALE = 3.0          # 216 dpi: enough to click points accurately
LINE_TOLERANCE = 3.0        # points; words closer than this vertically share a line
SIDE_MARGIN = 6.0


def drop_overprinted(words: List[dict]) -> List[dict]:
    """Text drawn more than once at nearly the same place (Riggi2023's appendix carries two copies of its
    text ~11 pt apart plus a third with the spaces run together, so its lines read 'Figure FigureA1.X-ray...
    Figure A1' and the 'Figure A1' caption was never seen). Kept: one copy of each word. Dropped: a word
    with the same text as a kept one within a few points, a word whose text is just the kept words it covers
    run together, and a word with every character doubled ('FFiigguurree') over its single copy."""
    near = lambda a, b: abs(a["top"] - b["top"]) <= 4
    kept: List[dict] = []
    for w in words:
        width = w["x1"] - w["x0"]
        if any(k["text"] == w["text"] and near(k, w) and abs(k["x0"] - w["x0"]) <= max(0.6 * width, 12) for k in kept):
            continue
        kept.append(w)
    out = []
    for w in kept:
        covered = sorted((k for k in kept if k is not w and near(k, w) and k["x0"] >= w["x0"] - 2 and k["x1"] <= w["x1"] + 2),
                         key=lambda k: k["x0"])
        if len(covered) >= 2 and "".join(k["text"] for k in covered) in w["text"]:
            continue                                      # the run-together copy
        t = w["text"]
        if (len(t) >= 2 and len(t) % 2 == 0 and t[0::2] == t[1::2]
                and any(k["text"] == t[0::2] and near(k, w) and k["x0"] < w["x1"] and w["x0"] < k["x1"] for k in kept)):
            continue                                      # the doubled-character copy
        out.append(w)
    return out


def _group_lines(words: List[dict]) -> List[dict]:
    """Words -> lines (top, bottom, x0, x1, words) for one column."""
    lines: List[dict] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        for ln in lines:
            if abs(ln["top"] - w["top"]) <= LINE_TOLERANCE:
                ln["words"].append(w)
                ln["x0"], ln["x1"] = min(ln["x0"], w["x0"]), max(ln["x1"], w["x1"])
                ln["bottom"] = max(ln["bottom"], w["bottom"])
                break
        else:
            lines.append({"top": w["top"], "bottom": w["bottom"], "x0": w["x0"], "x1": w["x1"],
                          "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
        ln["compact"] = "".join(w["text"] for w in ln["words"])
        ln["text"] = " ".join(w["text"] for w in ln["words"])
    return sorted(lines, key=lambda l: l["top"])


def _continues_across(line: dict, words: List[dict], mid: float) -> bool:
    """The line goes on past the middle with an ordinary word gap -- so the page (here)
    is one column, not two."""
    end = max(w["x1"] for w in line["words"])
    return any(abs(w["top"] - line["top"]) <= 3 and w["x1"] > mid and -1 <= w["x0"] - end <= 12
               for w in words)


def _caption_text(lines: List[dict]) -> str:
    text = " ".join(l["text"] for l in lines)
    words = text.split()
    # OCR letter-spacing: if most "words" are single characters, the spaces are noise
    if words and sum(len(w) == 1 for w in words) / len(words) > 0.5:
        text = "".join(words)
    return re.sub(r"\s+", " ", text).strip()


def _is_body_line(line: dict, col_width: float) -> bool:
    return (line["x1"] - line["x0"]) >= 0.55 * col_width and len(line["compact"]) >= 30


def _find_on_page(page, page_no: int, caption_re=CAPTION_RE) -> List[dict]:
    mid = page.width / 2
    columns: Dict[str, Tuple[float, float]] = {
        "left": (0.0, mid), "right": (mid, page.width), "full": (0.0, page.width)}
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["size"])
    # tightly set text runs words together with the default gap ("Figure3.Plotsofthe...",
    # alargov2002): re-read with a smaller one, as pdf_parser does for the main text
    from parameter_extractor.ingestion.pdf_parser import (MERGED_WORDS_THRESHOLD, TIGHT_X_TOLERANCE,
                                                          _merged_word_ratio)
    if _merged_word_ratio(" ".join(w["text"] for w in words)) > MERGED_WORDS_THRESHOLD:
        tight = page.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["size"],
                                   x_tolerance=TIGHT_X_TOLERANCE)
        if _merged_word_ratio(" ".join(w["text"] for w in tight)) < _merged_word_ratio(" ".join(w["text"] for w in words)):
            words = tight
    # drop sideways text (publisher watermarks down the margin, rotated axis titles): it
    # would otherwise join the start of whatever line it happens to sit beside
    words = drop_overprinted([w for w in words if w.get("upright", True)])
    by_col: Dict[str, List[dict]] = {"left": [], "right": [], "full": []}
    for w in words:
        if w["x1"] <= mid + 4:
            by_col["left"].append(w)
        elif w["x0"] >= mid - 4:
            by_col["right"].append(w)
        else:
            by_col["full"].append(w)
    lines = {c: _group_lines(ws) for c, ws in by_col.items()}
    body_size = statistics.median([w["size"] for w in words]) if words else 0

    found = []
    for col in ("left", "right", "full"):
        col_lines = lines[col]
        for i, ln in enumerate(col_lines):
            m = caption_re.match(ln["compact"])
            # a real caption has text after the number; a bare "Fig. 4" is the tail of some
            # other line (e.g. a table caption "...distribution of Fig. 4") split at the column gap
            if not m or len(ln["compact"]) - m.end() < 3:
                continue
            # caption block: following lines in the same column, closely spaced
            block = [ln]
            for nxt in col_lines[i + 1:]:
                gap = nxt["top"] - block[-1]["bottom"]
                if gap > 0.9 * (ln["bottom"] - ln["top"]) + 2 or caption_re.match(nxt["compact"]):
                    break
                block.append(nxt)
            size = statistics.mean(w["size"] for l in block for w in l["words"])
            wide = col == "left" and (max(l["x1"] for l in block) > mid + 20 or _continues_across(ln, words, mid))
            if wide and col == "left":
                # a single-column page: the caption's lines were cut at the middle -- rebuild them
                # from all the words in the caption's band (alargov2002 once its words split)
                band = [w for w in words if block[0]["top"] - 2 <= w["top"] <= block[-1]["bottom"]]
                block = _group_lines(band)
            found.append({"number": int(m.group(2)), "prefix": m.group(1), "col": "full" if wide else col,
                          "block": block, "size": size, "page_no": page_no})

    results = []
    for cap in found:
        if cap.get("skip"):
            continue
        col = cap["col"]
        cx0, cx1 = columns[col]
        cap_top = cap["block"][0]["top"]
        cap_bottom = cap["block"][-1]["bottom"]
        # lines above the caption that lie within the caption's column
        above = [l for c in (("left", "right", "full") if col == "full" else (col, "full"))
                 for l in lines[c] if l["bottom"] <= cap_top - 1]
        col_width = cx1 - cx0
        top = 28.0
        for l in sorted(above, key=lambda l: l["bottom"], reverse=True):
            if _is_body_line(l, col_width if l in lines[col] else page.width) or caption_re.match(l["compact"]):
                top = l["bottom"] + 3
                break
        cap["figure_bbox"] = (max(cx0 + (SIDE_MARGIN if col == "right" else 20), 0.0), top,
                              min(cx1 - (SIDE_MARGIN if col == "left" else 20), page.width), cap_top - 1)
        if cap["figure_bbox"][3] - cap["figure_bbox"][1] < MIN_FIGURE_HEIGHT:
            continue        # no room for a figure above it: running text, not a caption
        cap["caption_bbox"] = (min(l["x0"] for l in cap["block"]), cap_top,
                               max(l["x1"] for l in cap["block"]), cap_bottom)
        cap["caption"] = _caption_text(cap["block"])
        cap["numbers"] = [w for w in words if _NUMBER.fullmatch(w["text"])]    # tick labels of vector plots
        results.append(cap)
    return results


_NUMBER = re.compile(r"[-−–]?\d+(?:[.,]\d+)?")


def _numbers_in(words, figure_bbox, offset):
    """Numeric words (pdfplumber boxes) inside the figure, in rendered-page points."""
    from parameter_extractor.ingestion.pdf_parser import to_render_box
    _, ftop, _, fbottom = figure_bbox
    out = []
    for w in words:
        if not _NUMBER.fullmatch(w["text"]):
            continue
        box = to_render_box([w["x0"], w["top"], w["x1"], w["bottom"]], offset)
        # any x: y-axis numbers can sit outside the estimated plot area's sides
        if ftop - 5 <= box[1] and box[3] <= fbottom + 5:
            out.append((box, float(w["text"].replace(",", ".").replace("−", "-").replace("–", "-"))))
    return out


def find_figures(pdf_path: str, out_dir: Path, render_scale: float = RENDER_SCALE, supplement: bool = False,
                 page_offset: int = 0) -> List[FigureCandidate]:
    """Detect figures and render their pages (and a figure+caption crop each)
    into out_dir. One candidate per figure number: if a number matches more
    than one line (a caption, plus body text that happens to start a line
    with "Fig. N"), the line in the smaller font -- the caption -- wins.
    `supplement`: the paper's supplementary information -- figures 'Fig. S<n>' (files fig-S<n>.png,
    page-S<p>.png), pages numbered on from the paper's (`page_offset`), page_label 'S<p>'."""
    import pypdfium2 as pdfium
    from parameter_extractor.ingestion.pdf_parser import open_plumber, render_offset, to_render_box

    with open_plumber(pdf_path) as doc:
        caps = [c for i, page in enumerate(doc.pages, start=1)
                for c in _find_on_page(page, i, SI_CAPTION_RE if supplement else CAPTION_RE)]

    best: Dict[Tuple[str, int], dict] = {}
    for c in caps:
        key = ("S" if supplement else c["prefix"], c["number"])     # Fig. 1 and Fig. A1 are different figures
        if key not in best or c["size"] < best[key]["size"] - 0.2:
            best[key] = c
    if not best:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    sp = "S" if supplement else ""          # a supplement's page names
    pdf = pdfium.PdfDocument(pdf_path)
    rendered: Dict[int, object] = {}
    candidates = []
    try:
        for (s, number) in sorted(best, key=lambda k: (k[0] != "", k[0], k[1])):
            c = best[(s, number)]
            page_no = c["page_no"]
            if page_no not in rendered:
                img = pdf[page_no - 1].render(scale=render_scale).to_pil().convert("RGB")
                img.save(out_dir / f"page-{sp}{page_no}.png")
                rendered[page_no] = img
            img = rendered[page_no]
            # boxes in rendered-page points (the render shows the CropBox only)
            offset = render_offset(pdf[page_no - 1])
            figure_bbox, caption_bbox = to_render_box(c["figure_bbox"], offset), to_render_box(c["caption_bbox"], offset)
            fx0, ftop, fx1, _ = figure_bbox
            _, _, cx1, cbottom = caption_bbox
            crop_box = [round(v * render_scale) for v in (fx0, ftop, max(fx1, cx1), cbottom + 2)]
            crop_path = out_dir / f"fig-{s}{number}.png"
            img.crop(crop_box).save(crop_path)
            candidates.append(FigureCandidate(
                figure_id=f"Fig. {s}{number}", number=number, page=page_no + page_offset, caption=c["caption"],
                supplement=supplement, page_label=f"S{page_no}" if supplement else "", prefix=s,
                figure_bbox=figure_bbox, caption_bbox=caption_bbox,
                tick_numbers=[((x0 + x1) / 2 * render_scale, (t + b) / 2 * render_scale, v)
                              for (x0, t, x1, b), v in _numbers_in(c.get("numbers", []), figure_bbox, offset)],
                page_image=str(out_dir / f"page-{sp}{page_no}.png"), crop_image=str(crop_path),
                render_scale=render_scale))
    finally:
        pdf.close()
    return candidates
