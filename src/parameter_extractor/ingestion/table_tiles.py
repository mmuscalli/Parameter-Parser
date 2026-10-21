"""
Dense table pages, cut into pieces the model can read.

The API scales every image down to about 1568 px on its long side, so a full
page of small type -- teng2023's landscape Table 3, 37 rows x 9 columns with
superscript/subscript uncertainties -- arrives at ~140 dpi and superscripts get
misread (HD 167042 b's e uncertainty: +0.033 read as +0.003). So a table page is
rendered sharper (settings.TABLE_RASTER_DPI), its margins are cropped, and if it
is still larger than the API's limit it is cut into pieces:

  - rows: cut at a horizontal band of white space near the middle (never
    through a line of text);
  - columns (wide pages): cut at vertical white space, and every piece that
    continues to the right gets the page's row-label column (the first column
    of text, up to the first wide vertical gap) pasted on its left, so each
    row is still named.

Each piece is a separate image; api_client puts a short label before each
("page 9, piece 2 of 4") so the model knows how they fit together. Pure numpy +
Pillow (both already dependencies).
"""
from __future__ import annotations
from typing import List, Optional, Tuple

MAX_SIDE = 1568            # the API's long-side limit (larger images are scaled down)
TOLERANCE = 1.15           # up to 15% over is left whole: scaled down a little, not cut
INK = 200                  # grey level below which a pixel counts as ink
MARGIN = 12                # px kept around the cropped content
COLUMN_GAP_INK = 0.03      # a column "gap" may have ink in up to 3% of its rows (caption, rules)


def _ink(image):
    import numpy as np
    return np.asarray(image.convert("L")) < INK


def _content_box(ink) -> Tuple[int, int, int, int]:
    import numpy as np
    rows, cols = np.where(ink.sum(axis=1) > 2)[0], np.where(ink.sum(axis=0) > 2)[0]
    if not len(rows) or not len(cols):
        return 0, 0, ink.shape[1], ink.shape[0]
    return (max(int(cols[0]) - MARGIN, 0), max(int(rows[0]) - MARGIN, 0),
            min(int(cols[-1]) + MARGIN + 1, ink.shape[1]), min(int(rows[-1]) + MARGIN + 1, ink.shape[0]))


def _gaps(profile, min_len: int, threshold: float = 0) -> List[Tuple[int, int]]:
    """Runs of (near-)empty positions in an ink profile: [(start, end)]. `threshold`: most
    ink a position may have and still count as empty -- a column gap is crossed by the
    caption and the table's horizontal rules."""
    out, start = [], None
    for i, v in enumerate(list(profile) + [threshold + 1]):
        empty = v <= threshold and i < len(profile)
        if empty and start is None:
            start = i
        elif not empty and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    return out


def _cuts(profile, pieces: int, min_gap: int, threshold: float = 0) -> Optional[List[int]]:
    """Cut positions (centres of white-space gaps) closest to equal divisions, or None if
    there's no gap to cut at."""
    gaps = [(a + b) // 2 for a, b in _gaps(profile, min_gap, threshold)]
    n = len(profile)
    cuts = []
    for k in range(1, pieces):
        target = n * k // pieces
        options = [g for g in gaps if (cuts[-1] if cuts else 0) < g < n]
        if not options:
            return None
        cuts.append(min(options, key=lambda g: abs(g - target)))
    return sorted(set(cuts))


def _label_strip_end(ink, max_fraction: float = 0.4) -> int:
    """Where the row-label column ends: the start of the widest vertical white gap in the
    left part of the content (0 if there's none)."""
    height, width = ink.shape
    profile = ink.sum(axis=0)
    threshold = COLUMN_GAP_INK * height
    first = next((i for i, v in enumerate(profile) if v > threshold), 0)
    gaps = [(a, b) for a, b in _gaps(profile, max(6, width // 150), threshold) if first < a < width * max_fraction]
    if not gaps:
        return 0
    a, b = max(gaps, key=lambda g: g[1] - g[0])
    return a + min(MARGIN, (b - a) // 2)


def tile(image, max_side: int = MAX_SIDE) -> List:
    """The page cropped to its content, as one image or as pieces (row-major order) that
    each fit within max_side without scaling."""
    from PIL import Image
    import math
    ink = _ink(image)
    box = _content_box(ink)
    image, ink = image.crop(box), ink[box[1]:box[3], box[0]:box[2]]
    w, h = image.size
    limit = max_side * TOLERANCE
    if w <= limit and h <= limit:
        return [image]
    # rows first
    row_bands = [(0, h)]
    if h > limit:
        pieces = math.ceil(h / max_side)
        cuts = _cuts(ink.sum(axis=1), pieces, min_gap=4) or [h * k // pieces for k in range(1, pieces)]
        edges = [0] + cuts + [h]
        row_bands = list(zip(edges, edges[1:]))
    out = []
    for top, bottom in row_bands:
        band, band_ink = image.crop((0, top, w, bottom)), ink[top:bottom]
        if w <= limit:
            out.append(band)
            continue
        label_end = _label_strip_end(band_ink)
        if label_end > max_side // 3:
            label_end = 0                      # no plausible label column: plain pieces
        room = max_side - label_end
        pieces = math.ceil((w - label_end) / room) if label_end else math.ceil(w / max_side)
        data = band_ink[:, label_end:]
        cuts = _cuts(data.sum(axis=0), pieces, min_gap=6, threshold=COLUMN_GAP_INK * data.shape[0])
        if cuts is None:
            cuts = [(w - label_end) * k // pieces for k in range(1, pieces)]
        edges = [label_end] + [label_end + c for c in cuts] + [w]
        for i, (left, right) in enumerate(zip(edges, edges[1:])):
            if i == 0:
                out.append(band.crop((0, 0, right, band.size[1])))
                continue
            piece = band.crop((left, 0, right, band.size[1]))
            if label_end:                      # repeat the row labels on the left
                labels = band.crop((0, 0, label_end, band.size[1]))
                joined = Image.new("RGB", (label_end + piece.size[0], band.size[1]), "white")
                joined.paste(labels, (0, 0))
                joined.paste(piece, (label_end, 0))
                piece = joined
            out.append(piece)
    return out
