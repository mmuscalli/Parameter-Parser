"""
Optional automatic data-point detection (Mickey, 2026-11-03): the tops of bars and the centres of
scatter markers inside a plot frame, found locally in the page image (numpy only -- no model call).

Meant for clean, readable plots (Riggi2023's bar charts, vector-drawn scatter plots); the user checks
every point. What it can't do, by design:
  - markers drawn only as strokes ('+', 'x', '*'): lines are removed before markers are looked for, and
    these markers are lines -- 'Find similar points' (auto_points.py) handles them from an example;
  - markers hidden under other markers or merged into thick curves;
  - stacked bars (only the top of the stack) and bars below the baseline.

Bars: for every pixel column, the run of ink rising from the frame's bottom (the x axis, or the lowest
gridline); neighbouring columns of the same height and colour make a bar, its top read from the middle
of the bar (an error bar's whisker in the centre doesn't count). Hollow bars: two outline edges of the
same height joined by an inked top.

Markers: ink (dark or coloured pixels) inside the frame, enclosed holes filled (open circles become
discs), then a morphological opening whose size comes from the marker cores themselves -- lines, curves,
gridlines and most text strokes are thinner and vanish; what's left are the markers. Touching markers
are split by area. Each marker gets a few appearance features (colour, filled or open, shape) used to
group them by series and to match the groups with the series' marker descriptions ('open circles',
'filled red triangles').
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from parameter_extractor.digitizing.auto_points import _box_sum

INK_LUMINANCE = 170          # darker than this is ink (gridlines and pale shading are lighter)
INK_CHROMA = 60              # or coloured: max - min channel
MAX_HOLE = 70                # pixels: enclosed background no larger than this is a marker's inside
MIN_BAR_HEIGHT = 4
MIN_BAR_WIDTH = 5
MIN_MARKER_PX = 5            # a marker narrower than this (at the 216 dpi render) isn't findable
MAX_MARKER_PX = 60

Box = Tuple[float, float, float, float]


@dataclass
class Found:
    x: float
    y: float
    kind: str                    # "bar" or "marker"
    color: Tuple[float, float, float]
    filled: float = 1.0          # share of the marker's area that is ink (1 solid, ~0.3-0.6 open)
    fill_ratio: float = 1.0      # area / bounding box (circle ~0.79, square 1, triangle / diamond ~0.5)
    pointing: float = 0.0        # centroid below (+) / above (-) the box centre, in heights: triangles
    sideways: float = 0.0        # the same across, in widths: a triangle pointing left / right (arrowheads)
    size: float = 0.0
    box: Box = (0, 0, 0, 0)
    group: int = -1


# ---- images and masks ---------------------------------------------------------------------------

def ink_mask(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(np.int16)
    lum = 0.299 * c[..., 0] + 0.587 * c[..., 1] + 0.114 * c[..., 2]
    chroma = c.max(axis=2) - c.min(axis=2)
    return (lum < INK_LUMINANCE) | ((chroma > INK_CHROMA) & (lum < 235))


def _runs_per_row(mask: np.ndarray):
    """[(y, start, end)] runs of True, end exclusive."""
    padded = np.pad(mask, ((0, 0), (1, 1))).astype(np.int8)
    d = np.diff(padded, axis=1)
    ys, xs = np.nonzero(d)
    vals = d[ys, xs]
    starts = [(y, x) for y, x, v in zip(ys.tolist(), xs.tolist(), vals.tolist()) if v == 1]
    ends = [x for v, x in zip(vals.tolist(), xs.tolist()) if v == -1]
    return [(y, s, e) for (y, s), e in zip(starts, ends)]


def label(mask: np.ndarray) -> Tuple[np.ndarray, int]:
    """Connected components (8-connected) by run-length union-find: (labels 1..n, n)."""
    runs = _runs_per_row(mask)
    parent = list(range(len(runs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_row: Dict[int, List[int]] = {}
    for i, (y, s, e) in enumerate(runs):
        by_row.setdefault(y, []).append(i)
    for i, (y, s, e) in enumerate(runs):
        for j in by_row.get(y - 1, ()):
            _, s2, e2 = runs[j]
            if s2 <= e and s <= e2:            # overlapping or touching diagonally
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    labels = np.zeros(mask.shape, dtype=np.int32)
    ids: Dict[int, int] = {}
    for i, (y, s, e) in enumerate(runs):
        root = find(i)
        labels[y, s:e] = ids.setdefault(root, len(ids) + 1)
    return labels, len(ids)


def _stats(labels: np.ndarray, n: int):
    """Per label 1..n: area, bbox (x0, y0, x1, y1 inclusive), centroid."""
    ys, xs = np.nonzero(labels)
    lab = labels[ys, xs]
    area = np.bincount(lab, minlength=n + 1)
    cx = np.bincount(lab, xs, minlength=n + 1) / np.maximum(area, 1)
    cy = np.bincount(lab, ys, minlength=n + 1) / np.maximum(area, 1)
    x0 = np.full(n + 1, 1 << 30); y0 = np.full(n + 1, 1 << 30)
    x1 = np.full(n + 1, -1); y1 = np.full(n + 1, -1)
    np.minimum.at(x0, lab, xs); np.minimum.at(y0, lab, ys)
    np.maximum.at(x1, lab, xs); np.maximum.at(y1, lab, ys)
    return area, (x0, y0, x1, y1), (cx, cy)


def fill_holes(mask: np.ndarray, max_size: int = MAX_HOLE) -> np.ndarray:
    """Background enclosed by ink and no larger than max_size across -> ink (open markers -> discs)."""
    labels, n = label(~mask)
    if n == 0:
        return mask
    _, (x0, y0, x1, y1), _ = _stats(labels, n)
    h, w = mask.shape
    hole = np.zeros(n + 1, dtype=bool)
    for i in range(1, n + 1):
        if x0[i] > 0 and y0[i] > 0 and x1[i] < w - 1 and y1[i] < h - 1 and \
                x1[i] - x0[i] < max_size and y1[i] - y0[i] < max_size:
            hole[i] = True
    return mask | hole[labels]


def erode(mask: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return mask.copy()
    r = k // 2
    full = _box_sum(mask.astype(np.int32), k, k) == k * k
    out = np.zeros_like(mask)
    out[r:r + full.shape[0], r:r + full.shape[1]] = full
    return out


def _disc_offsets(radius: float):
    r = int(np.floor(radius))
    return [(dy, dx) for dy in range(-r, r + 1) for dx in range(-r, r + 1) if dy * dy + dx * dx <= radius * radius]


def disc_erode(mask: np.ndarray, radius: float) -> np.ndarray:
    """Pixels whose whole disc of `radius` is ink (shifted copies ANDed; radii here are small)."""
    r = int(np.floor(radius))
    p = np.pad(mask, r)
    h, w = mask.shape
    out = np.ones_like(mask)
    for dy, dx in _disc_offsets(radius):
        out &= p[r + dy:r + dy + h, r + dx:r + dx + w]
    return out


def disc_dilate(mask: np.ndarray, radius: float) -> np.ndarray:
    r = int(np.floor(radius))
    p = np.pad(mask, r)
    h, w = mask.shape
    out = np.zeros_like(mask)
    for dy, dx in _disc_offsets(radius):
        out |= p[r + dy:r + dy + h, r + dx:r + dx + w]
    return out


def dilate(mask: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return mask.copy()
    r = k // 2
    padded = np.pad(mask.astype(np.int32), r)
    return _box_sum(padded, k, k) > 0


# ---- bars ---------------------------------------------------------------------------------------

def find_bars(rgb: np.ndarray, frame: Box) -> List[Found]:
    """Bars standing on the frame's bottom: (centre x, top y) each, left to right."""
    left, top, right, bottom = (int(round(v)) for v in frame)
    ink = ink_mask(rgb)
    h, w = ink.shape
    x_from, x_to = max(left + 2, 0), min(right - 1, w)
    base = min(bottom, h - 1)
    # just above the axis line (scanned axes are a few pixels thick)
    start = base - 1
    while start > max(top, base - 6) and ink[start, x_from:x_to].mean() > 0.97:
        start -= 1                        # a fully inked row is the axis line (thick in scans)
    heights = np.zeros(x_to - x_from, dtype=int)
    for i, x in enumerate(range(x_from, x_to)):
        col = ink[top - 2:start + 1, x][::-1] if top >= 2 else ink[:start + 1, x][::-1]
        if col.size == 0 or not col[0]:
            continue
        stop = np.argmin(col) if not col.all() else col.size
        heights[i] = stop
    tops = start - heights + 1
    probe = max(start - 2, top)
    colours = rgb[probe, x_from:x_to].astype(float)

    # columns -> segments of similar colour and height
    segments: List[Tuple[int, int]] = []
    i = 0
    n = len(heights)
    while i < n:
        if heights[i] < MIN_BAR_HEIGHT:
            i += 1
            continue
        j = i + 1
        while j < n and heights[j] >= MIN_BAR_HEIGHT and \
                np.abs(colours[j] - colours[j - 1]).max() < 45 and \
                not (abs(heights[j] - heights[j - 1]) > 6 and abs(heights[j] - np.median(heights[i:j])) > 6
                     and j - i >= MIN_BAR_WIDTH and _stays(heights, j, heights[j])):
            j += 1
        segments.append((i, j))
        i = j

    bars: List[Found] = []
    thin = []
    for i, j in segments:
        width = j - i
        if width < MIN_BAR_WIDTH:
            thin.append((i, j))
            continue
        core = heights[i + width // 5: j - width // 5] if width >= 5 else heights[i:j]
        hgt = float(np.median(core))
        lo, hi = np.percentile(core, [10, 90])
        if hi - lo > max(3.0, 0.06 * hgt):
            continue                          # a dome (a marker on the axis, a peak), not a flat bar top
        y_top = start - hgt + 1
        cx = x_from + (i + j - 1) / 2
        colour = tuple(float(v) for v in np.median(colours[i:j], axis=0))
        bars.append(Found(x=cx, y=float(y_top), kind="bar", color=colour, size=float(width),
                          box=(x_from + i, float(y_top), x_from + j - 1, float(start))))
    # hollow bars: two thin outline edges of the same height, their tops joined by a line. Thin columns
    # touching a solid bar are its anti-aliased edge, not an outline (Riggi2023 Fig. 3 paired two such
    # edges across a gridline at the bars' height)
    solid = [(int(b.box[0]) - x_from, int(b.box[2]) - x_from) for b in bars]
    thin = [(i, j) for i, j in thin if not any(a - 3 <= j and i <= c + 3 for a, c in solid)]
    used = set()
    for a in range(len(thin)):
        if a in used:
            continue
        for b in range(a + 1, len(thin)):
            (i1, j1), (i2, j2) = thin[a], thin[b]
            h1, h2 = heights[i1:j1].max(), heights[i2:j2].max()
            if abs(h1 - h2) > 3 or i2 - j1 < 3:
                continue
            y_top = int(start - max(h1, h2) + 1)
            row = ink[max(y_top - 1, 0):y_top + 2, x_from + j1:x_from + i2].any(axis=0)
            inside = [x for x in range(x_from + j1, x_from + i2)]
            if row.size and row.mean() > 0.8 and not any(b_.box[0] <= x <= b_.box[2] for b_ in bars for x in inside[:1]):
                bars.append(Found(x=x_from + (i1 + j2 - 1) / 2, y=float(y_top), kind="bar",
                                  color=tuple(float(v) for v in rgb[y_top, x_from + i1]), size=float(j2 - i1),
                                  box=(x_from + i1, float(y_top), x_from + j2 - 1, float(start))))
                used |= {a, b}
                break
    bars.sort(key=lambda b: b.x)
    return bars


def _stays(heights: np.ndarray, j: int, value: int, span: int = 4) -> bool:
    """The height change at column j lasts (a bar's next neighbour, not one stray column)."""
    window = heights[j:j + span]
    return window.size >= 2 and bool(np.all(np.abs(window - value) <= 4))


def detect_points(rgb: np.ndarray, frame: Box, kind: str = "auto", exclude: Sequence[Box] = (),
                  tick_numbers: Sequence[Tuple[float, float, float]] = ()) -> Tuple[List[Found], str]:
    """Bars or markers in one plot frame. kind 'bars' (a category chart), 'markers', or 'auto': bars
    when the frame holds two or more bars of similar width, else markers. Returns (found, kind used)."""
    if kind in ("auto", "bars"):
        bars = find_bars(rgb, frame)
        if kind == "bars":
            return bars, "bars"
        wide = [b for b in bars if b.size >= 8]
        if len(wide) >= 2:
            median = float(np.median([b.size for b in wide]))
            similar = [b for b in wide if 0.7 * median <= b.size <= 1.3 * median]
            if len(similar) >= 2:
                return similar, "bars"
    # tick numbers from the text layer (vector plots): digits with holes look like open markers. Only a
    # marker CENTRED on one is dropped -- blanking the label's box cut markers sitting on the axis in half
    # (sakata2010 Fig. 6d)
    found = find_markers(rgb, frame, exclude=exclude)
    found = [f for f in found if not any(abs(f.x - x) < 14 and abs(f.y - y) < 9 for x, y, _ in tick_numbers)]
    return found, "markers"


# ---- markers ------------------------------------------------------------------------------------

def find_markers(rgb: np.ndarray, frame: Box, exclude: Sequence[Box] = ()) -> List[Found]:
    """Marker centres inside the frame (page pixels), with appearance features."""
    left, top, right, bottom = (int(round(v)) for v in frame)
    # a little beyond the frame: markers sitting on an axis (t = 0) are whole; axis lines and ticks are
    # thin and opened away; only centres inside the frame are kept
    pad = 12
    x0, y0 = max(left - pad, 0), max(top - pad, 0)
    x1, y1 = min(right + pad, rgb.shape[1]), min(bottom + pad, rgb.shape[0])
    if x1 - x0 < 20 or y1 - y0 < 20:
        return []
    sub = rgb[y0:y1, x0:x1]
    ink = ink_mask(sub)
    for bx0, by0, bx1, by1 in exclude:           # legends and text
        ink[max(int(by0) - y0 - 2, 0):max(int(by1) - y0 + 3, 0), max(int(bx0) - x0 - 2, 0):max(int(bx1) - x0 + 3, 0)] = False
    filled = fill_holes(ink)

    # thickness: how many 3x3 erosions a pixel survives (lines 0-1, a marker's core ~ its inradius)
    t = np.zeros(filled.shape, dtype=np.int16)
    m = filled
    for depth in range(1, MAX_MARKER_PX // 2):
        m = erode(m, 3)
        if not m.any():
            break
        t[m] = depth
    cores, n = label(t >= 2)
    if n == 0:
        return []
    peak = np.zeros(n + 1, dtype=int)
    np.maximum.at(peak, cores[cores > 0], t[cores > 0])
    peaks = peak[1:]
    peaks = peaks[peaks >= 2]
    if peaks.size == 0:
        return []
    # opened with a disc a little smaller than the thinnest common marker (triangles have a small
    # inradius) but wider than the lines: lines and curves vanish, markers keep their shape
    radius = max(1.5, min(4.0, 0.5 * float(np.percentile(peaks, 75))))
    opened = disc_dilate(disc_erode(filled, radius), radius) & filled
    labels, n = label(opened)
    if n == 0:
        return []
    area, (bx0, by0, bx1, by1), (cx, cy) = _stats(labels, n)
    widths, heights = bx1 - bx0 + 1, by1 - by0 + 1
    keep = [i for i in range(1, n + 1)
            if MIN_MARKER_PX <= widths[i] <= MAX_MARKER_PX * 2.5 and MIN_MARKER_PX <= heights[i] <= MAX_MARKER_PX * 2.5]
    if not keep:
        return []
    # one marker's area: from marker-like blobs (about as wide as high, filling their box), not dash pieces
    like = [area[i] for i in keep if widths[i] <= MAX_MARKER_PX and heights[i] <= MAX_MARKER_PX
            and max(widths[i], heights[i]) <= 1.5 * min(widths[i], heights[i])
            and area[i] >= 0.45 * widths[i] * heights[i]]
    single = float(np.median(like or [area[i] for i in keep]))
    found: List[Found] = []
    for i in keep:
        comp = labels[by0[i]:by1[i] + 1, bx0[i]:bx1[i] + 1] == i
        count = int(area[i] / single + 0.3) if single else 1     # lines stuck to touching markers add area
        compact = area[i] / (widths[i] * heights[i]) >= 0.45 and max(widths[i], heights[i]) <= 3 * min(widths[i], heights[i])
        if not compact:
            continue                            # a thick curve or a filled area, not markers
        if count >= 2 and count <= 6:
            centres = _split(comp, count)
        else:
            if widths[i] > MAX_MARKER_PX or heights[i] > MAX_MARKER_PX:
                continue                        # a thick blob, not markers (a filled area, a photo)
            if max(widths[i], heights[i]) > 1.45 * min(widths[i], heights[i]) or area[i] < 0.35 * single:
                continue                        # a piece of a dashed or thick line, a fragment
            ys, xs = np.nonzero(comp)
            centres = [(xs.mean(), ys.mean())]
        g = 3
        ya, yb, xa, xb = max(by0[i] - g, 0), by1[i] + g + 1, max(bx0[i] - g, 0), bx1[i] + g + 1
        grown = disc_dilate(labels[ya:yb, xa:xb] == i, 2.0) & filled[ya:yb, xa:xb]
        own_ink = ink[ya:yb, xa:xb] & grown
        colour_px = sub[ya:yb, xa:xb][own_ink]
        colour = tuple(float(v) for v in (np.median(colour_px, axis=0) if colour_px.size else (0, 0, 0)))
        solid = float(own_ink.sum() / max(grown.sum(), 1))
        # shape: the marker grown back to its own edge, inside its box (lines leaving it don't stretch it)
        inner = grown[by0[i] - ya:by1[i] - ya + 1, bx0[i] - xa:bx1[i] - xa + 1] | comp
        ratio = float(inner.sum() / max(inner.size, 1)) if count < 2 else 0.785
        gy, gx = np.nonzero(inner)
        pointing = float((gy.mean() - (inner.shape[0] - 1) / 2) / inner.shape[0]) if count < 2 and gy.size else 0.0
        sideways = float((gx.mean() - (inner.shape[1] - 1) / 2) / inner.shape[1]) if count < 2 and gx.size else 0.0
        size = float(np.sqrt(area[i] / max(count, 1)))
        for mx, my in centres:
            if not (left - 3 <= x0 + bx0[i] + mx <= right + 3 and top - 3 <= y0 + by0[i] + my <= bottom + 3):
                continue                        # outside the plot: tick labels, axis titles
            own_solid = solid
            if count >= 2:
                # touching markers (a filled one over an open one): each judged within its own radius
                yy, xx = np.mgrid[0:comp.shape[0], 0:comp.shape[1]]
                disc = comp & ((xx - mx) ** 2 + (yy - my) ** 2 <= (0.5 * size) ** 2)
                part_ink = ink[by0[i]:by1[i] + 1, bx0[i]:bx1[i] + 1] & disc
                own_solid = float(part_ink.sum() / max(disc.sum(), 1))
            found.append(Found(x=x0 + bx0[i] + float(mx), y=y0 + by0[i] + float(my), kind="marker", color=colour,
                               filled=own_solid, fill_ratio=ratio, pointing=pointing, sideways=sideways, size=size,
                               box=(x0 + bx0[i], y0 + by0[i], x0 + bx1[i], y0 + by1[i])))
    return found


def _split(comp: np.ndarray, count: int) -> List[Tuple[float, float]]:
    """Centres of `count` touching markers: k-means on the component's pixels."""
    ys, xs = np.nonzero(comp)
    pts = np.stack([xs, ys], axis=1).astype(float)
    order = np.argsort(pts[:, 0] + pts[:, 1])
    centres = pts[order[np.linspace(0, len(pts) - 1, count).astype(int)]]
    for _ in range(15):
        d = ((pts[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
        nearest = d.argmin(axis=1)
        new = np.array([pts[nearest == c].mean(axis=0) if (nearest == c).any() else centres[c] for c in range(count)])
        if np.allclose(new, centres, atol=0.2):
            break
        centres = new
    return [(float(x), float(y)) for x, y in centres]


# ---- grouping and matching with the series ------------------------------------------------------

SOLID = 0.85                 # ink share above which a marker is filled
# (fill ratio, pointing) of each shape, measured on drawn markers of 10-25 px with lines through them
SHAPE_PROTOTYPES = {"circle": (0.77, 0.0), "square": (1.0, 0.0), "triangle": (0.64, 0.12),
                    "down triangle": (0.64, -0.12), "diamond": (0.56, 0.0)}


def shape_of(f: Found) -> str:
    if abs(f.pointing) >= 0.05:
        return "triangle" if f.pointing > 0 else "down triangle"
    if abs(f.sideways) >= 0.05:
        return "side triangle"                 # pointing left or right: arrowheads, rarely a marker
    return min(("circle", "square", "diamond"), key=lambda k: abs(SHAPE_PROTOTYPES[k][0] - f.fill_ratio))


def _colour_distance(a, b) -> float:
    return float(np.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))))


def group_by_appearance(found: List[Found]) -> List[List[Found]]:
    """Markers (or bars) that look alike -- same shape, filled or open, colour, size -- largest group
    first; sets Found.group."""
    groups: List[List[Found]] = []
    for f in sorted(found, key=lambda f: (f.y, f.x)):
        for g in groups:
            ref = g[0]
            same = _colour_distance(f.color, tuple(np.mean([q.color for q in g], axis=0))) < 70
            if f.kind == "marker":
                same = same and shape_of(f) == shape_of(ref) and (f.filled > SOLID) == (ref.filled > SOLID) \
                    and max(f.size, ref.size) < 1.35 * min(f.size, ref.size)
            if same:
                g.append(f)
                break
        else:
            groups.append([f])
    groups.sort(key=len, reverse=True)
    for k, g in enumerate(groups):
        for f in g:
            f.group = k
    return groups


COLOURS = {"black": (20, 20, 20), "grey": (128, 128, 128), "gray": (128, 128, 128), "red": (220, 30, 30),
           "blue": (40, 90, 210), "green": (40, 160, 60), "orange": (240, 140, 20), "purple": (130, 50, 160),
           "violet": (130, 50, 160), "magenta": (210, 40, 180), "pink": (240, 120, 170), "yellow": (230, 210, 30),
           "brown": (140, 80, 30), "cyan": (30, 190, 210)}
SHAPE_WORDS = {"circle": "circle", "round": "circle", "dot": "circle", "disc": "circle", "disk": "circle",
               "square": "square", "box": "square", "rectangle": "square",
               "triangle": "triangle", "diamond": "diamond", "rhombus": "diamond", "lozenge": "diamond"}
SYMBOLS = {"○": "open circle", "●": "filled circle", "□": "open square", "■": "filled square",
           "△": "open triangle", "▲": "filled triangle", "▽": "open down triangle", "▼": "filled down triangle",
           "◇": "open diamond", "◆": "filled diamond", "◊": "open diamond"}


def describe(text: str) -> dict:
    """What a marker description says: {'filled': bool, 'shape': name, 'color': rgb} -- only what it says
    ('open diamond', 'filled red triangles', '▽')."""
    for sym, words in SYMBOLS.items():
        text = text.replace(sym, f" {words} ")
    low = text.lower()
    known = set(SHAPE_WORDS) | set(COLOURS) | {"cross", "plus", "star", "asterisk", "line", "open", "filled"}
    words = [next((c for c in (w, w[:-1], w[:-2]) if c in known), w) for w in re.findall(r"[a-z]+", low)]
    out: dict = {}
    if any(w in ("open", "hollow", "empty", "unfilled", "white") for w in words):
        out["filled"] = False
    elif any(w in ("filled", "solid", "closed", "full", "black") for w in words):
        out["filled"] = True
    for w in words:
        if w in SHAPE_WORDS:
            out["shape"] = SHAPE_WORDS[w]
            if out["shape"] == "triangle" and re.search(r"down|invert|upside", low):
                out["shape"] = "down triangle"
            break
    if any(w in ("cross", "plus", "x", "star", "asterisk", "line", "dashed", "dotted") for w in words) \
            and "shape" not in out:
        out["shape"] = "stroke"              # drawn with lines only: not findable here
    colours = [w for w in words if w in COLOURS]
    if colours:
        out["color"] = COLOURS[colours[0]]
    return out


def _fits(desc: dict, g: List[Found]) -> Optional[float]:
    """How well a group fits a description (lower is better); None when it contradicts it."""
    ref = g[0]
    cost = 0.0
    if ref.kind == "marker":
        if "filled" in desc:
            solid = float(np.median([f.filled for f in g]))
            if desc["filled"] != (solid > SOLID):
                return None
        if "shape" in desc:
            if desc["shape"] == "stroke":
                return None
            counts: Dict[str, int] = {}
            for f in g:
                counts[shape_of(f)] = counts.get(shape_of(f), 0) + 1
            if max(counts, key=counts.get) != desc["shape"]:
                return None
    if "color" in desc:
        mean = tuple(np.mean([f.color for f in g], axis=0))
        d = _colour_distance(mean, desc["color"]) / 255
        if d > 0.55:
            return None
        cost += d
    return cost - 0.01 * len(desc)          # the more a description says, the better a fit counts


def assign_to_series(groups: List[List[Found]], series_text: Sequence[str]) -> Tuple[Dict[int, List[Found]], str]:
    """{series index: points} for the series (their label + marker text) and a note on what wasn't
    assigned. One series: everything goes to it. Bars of a category chart (one series per bar) go to the
    series in order, left to right; grouped bars by colour, in the order the colours first appear.
    Markers: each kind goes to the series whose marker description it fits; a kind several series fit
    equally, or none, is left out (and said so)."""
    out: Dict[int, List[Found]] = {}
    if not groups or not series_text:
        return out, ""
    everything = [f for g in groups for f in g]
    if len(series_text) == 1:
        out[0] = everything
        return out, ("" if len(groups) == 1 else
                     f"{len(groups)} kinds of marker found; all went to the one series -- check them")
    if everything[0].kind == "bar":
        bars = sorted(everything, key=lambda f: f.x)
        if len(bars) == len(series_text):
            return {i: [b] for i, b in enumerate(bars)}, ""
        if len(groups) == len(series_text):
            ordered = sorted(groups, key=lambda g: min(f.x for f in g))
            return {i: sorted(g, key=lambda f: f.x) for i, g in enumerate(ordered)}, ""
        return {}, (f"{len(bars)} bars found but {len(series_text)} series here -- nothing added; "
                    f"adjust the series or place the points by hand")
    descs = [describe(t) for t in series_text]
    left: List[List[Found]] = []
    for g in groups:
        fits = sorted((c, si) for si, d in enumerate(descs) if d for c in [_fits(d, g)] if c is not None)
        if not fits or (len(fits) > 1 and abs(fits[0][0] - fits[1][0]) < 1e-6 and
                        descs[fits[0][1]] == descs[fits[1][1]]):
            left.append(g)
            continue
        out.setdefault(fits[0][1], []).extend(g)
    # one kind left and one series without a description or points: they belong together
    empty = [si for si in range(len(series_text)) if si not in out]
    if len(left) == 1 and len(empty) == 1:
        out[empty[0]] = left.pop()
    note = ""
    if left:
        note = (f"{sum(len(g) for g in left)} marker(s) of {len(left)} kind(s) not matched to a series "
                f"({'; '.join(_appearance(g) for g in left[:3])}) -- 'Find similar points' adds them to one")
    return out, note


def _appearance(g: List[Found]) -> str:
    f = g[0]
    name = min(COLOURS, key=lambda c: _colour_distance(COLOURS[c], f.color))
    fill = "filled" if f.filled > SOLID else "open"
    return f"{len(g)} {fill} {name} {shape_of(f)}" + ("s" if len(g) > 1 else "")


# ---- error bars (Mickey, 2026-11-03) ------------------------------------------------------------------------------
# From a marker's top / bottom edge (a bar's top), follow a thin vertical line of ink; its end counts as an error
# bar only where a short horizontal cap crosses it -- so a gridline, a connecting line or a neighbouring marker
# isn't taken for one. Bars: the upper whisker only (the lower one is hidden in, or drawn over, the bar).

MIN_WHISKER = 3              # pixels beyond the marker / bar edge
MAX_LINE_WIDTH = 4           # the whisker itself: a thin line
MIN_CAP, MAX_CAP_FACTOR = 4, 4.0


def _cap_at(mask: np.ndarray, x: int, y: int, size: float) -> bool:
    """A short horizontal line through (x, y): ink to both sides, not a long gridline."""
    h, w = mask.shape
    for yy in (y - 1, y, y + 1):
        if not 0 <= yy < h or not mask[yy, x]:
            continue
        left = right = 0
        while x - left - 1 >= 0 and mask[yy, x - left - 1]:
            left += 1
        while x + right + 1 < w and mask[yy, x + right + 1]:
            right += 1
        if left >= 2 and right >= 2 and MIN_CAP <= left + right + 1 <= max(MAX_CAP_FACTOR * max(size, 6), 12):
            return True
    return False


def _whisker(mask: np.ndarray, x: int, start: int, step: int, limit: Tuple[int, int], size: float) -> Optional[int]:
    """The end (pixel y) of a capped whisker going from `start` in direction `step`, or None."""
    return _whisker_from(mask, x, start, step, limit, size)


def _whisker_from(mask, x, start, step, limit, size):
    lo, hi = limit
    # the whisker's column: the inked one nearest the centre within 3 px (a bar's centre can be a pixel or two off)
    probe = [start + step * k for k in range(1, 5) if lo <= start + step * k <= hi]
    if probe:
        hits = [(abs(dx), x + dx) for dx in range(-3, 4) if 0 <= x + dx < mask.shape[1]
                and sum(mask[yy, x + dx] for yy in probe) >= len(probe) - 1]
        if hits:
            x = min(hits)[1]
    y, last, gap, rows, wide = start, None, 0, 0, 0
    while lo <= y <= hi:
        if mask[y, max(x - 1, 0):x + 2].any():
            last, gap = y, 0
            rows += 1
            wide += int(mask[y, max(x - 5, 0):x + 6].sum() > MAX_LINE_WIDTH)
        else:
            gap += 1
            if gap > 1:              # a whisker is continuous; a gridline two rows past its cap isn't part of it
                break
        y += step
    if last is None or abs(last - start) < MIN_WHISKER:
        return None
    if wide > 0.4 * rows + 2:          # mostly wide ink: a filled shape, not a line (the cap rows are allowed)
        return None
    return last if _cap_at(mask, x, last, size) else None


WHISKER_LUMINANCE = 215      # error bars are often thin grey lines (Riggi2023 Fig. 2: ~199), lighter than ink


def whisker_mask(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(np.int16)
    lum = 0.299 * c[..., 0] + 0.587 * c[..., 1] + 0.114 * c[..., 2]
    chroma = c.max(axis=2) - c.min(axis=2)
    return (lum < WHISKER_LUMINANCE) | ((chroma > INK_CHROMA) & (lum < 235))


def find_error_bars(rgb: np.ndarray, frame: Box, found: Sequence[Found]) -> Dict[int, Tuple[Optional[float], Optional[float]]]:
    """{index in `found`: (upper end y, lower end y)} for the points that have a capped error bar (either end may
    be None)."""
    mask = whisker_mask(rgb)
    x0, y0, x1, y1 = (int(round(v)) for v in frame)
    top, bottom = max(y0 - 6, 0), min(y1 + 6, mask.shape[0] - 1)
    out = {}
    for i, f in enumerate(found):
        x = int(round(f.x))
        if not 0 <= x < mask.shape[1]:
            continue
        bx0, by0, bx1, by1 = f.box if any(f.box) else (f.x - f.size / 2, f.y - f.size / 2, f.x + f.size / 2,
                                                         f.y + f.size / 2)
        start_up = int(round(f.y if f.kind == "bar" else by0)) - 1
        up = _whisker(mask, x, start_up, -1, (top, bottom), f.size)
        down = None
        if f.kind != "bar":
            down = _whisker(mask, x, int(round(by1)) + 1, 1, (top, bottom), f.size)
        if up is not None or down is not None:
            out[i] = (float(up) if up is not None else None, float(down) if down is not None else None)
    return out
