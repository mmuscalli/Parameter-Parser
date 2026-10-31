"""
Optional automatic axis calibration: find a plot's frame in the rendered page
image, find where the tick numbers are printed along an axis (blocks of ink
just outside the axis line -- plots without tick marks have them too; a tick
mark nearby refines the position), pair them with their values, and place
the two calibration markers on the outermost labelled positions.

Where the tick numbers come from:
  - the PDF's text layer, when the figure is vector graphics with real text
    (exact positions, read directly);
  - otherwise the numbers the figure-suggestion step read off the image
    (AxisVariable.tick_labels) -- many papers' plots are embedded images
    with no text at all (alargov2002). These are paired with the detected
    ticks in order.

Never guesses: the result is used only if the ticks are evenly spaced (or
evenly spaced in log10 for a log axis) and the pairing is unambiguous;
otherwise it says why and the user calibrates by hand. The user sees the
markers placed and can move them -- this only does the first pass.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

DARK = 140                  # grey level below which a pixel is "ink"
MIN_LINE_FRACTION = 0.2     # an axis line spans at least this share of the search region
# spreadsheet-style charts (mizuuchi2019, Riggi2023): pale grey axis lines (~205) and gridlines (~185),
# often several small panels in one figure -- a second, fainter pass with shorter lines
FAINT = 232
FAINT_LINE_FRACTION = 0.08
MIN_LINE_PX = 60
CORNER_TOL = 8              # pixels: how close an axis line's end must be to the frame corner
TICK_MIN, TICK_MAX = 4, 40  # pixels: tick mark length range
SPACING_TOL = 0.04          # ticks evenly spaced to within 4% of the step


class AutoAxisError(ValueError):
    """Why the automatic calibration didn't work, in words for the user."""


@dataclass
class Line:
    pos: float      # y of a horizontal line, x of a vertical one (centre of its thickness)
    start: int
    end: int
    thick: int


@dataclass
class Frame:
    left: float
    right: float
    top: float
    bottom: float
    has_right_axis: bool
    has_top_axis: bool
    gridlines: Tuple[float, ...] = ()     # y of horizontal gridlines (frames found from a grid alone)

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


GAP_FILL = 7                # pixels: gaps this short in a scanned line are bridged


def _close(mask_1d: np.ndarray, gap: int) -> np.ndarray:
    """Bridge gaps of up to `gap` pixels (scanned lines are broken)."""
    if gap <= 0 or not mask_1d.any():
        return mask_1d
    grown = np.convolve(mask_1d.astype(int), np.ones(gap), mode="same") > 0
    return np.convolve(grown.astype(int), np.ones(gap), mode="same") >= gap


def _runs(mask_1d: np.ndarray) -> List[Tuple[int, int]]:
    """(start, end) of the True runs in a 1-D boolean array."""
    padded = np.concatenate(([False], mask_1d, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[::2], edges[1::2]))


def _lines(dark: np.ndarray, horizontal: bool, min_len: int) -> List[Line]:
    """Long straight runs of ink, merged across the rows (columns) of a thick line."""
    arr = dark if horizontal else dark.T
    found: List[Line] = []
    for i, row in enumerate(arr):
        for a, b in _runs(_close(row, GAP_FILL)):
            if b - a < min_len:
                continue
            for ln in found:   # continue a line from the previous row/column
                if i - (ln.pos + ln.thick / 2) <= 1.5 and abs(ln.start - a) <= 4 and abs(ln.end - b) <= 4:
                    ln.pos = (ln.pos * ln.thick + i) / (ln.thick + 1)
                    ln.thick += 1
                    ln.start, ln.end = min(ln.start, a), max(ln.end, b)
                    break
            else:
                found.append(Line(float(i), int(a), int(b), 1))
    return _merge([ln for ln in found if ln.thick <= 8])  # thicker: a filled area, not a line


def _merge(lines: List[Line]) -> List[Line]:
    """Join pieces of one line: a slightly rotated scan splits an axis into segments a
    pixel or two apart (alargov2002 Fig. 3b's bottom axis: y = 1695 and 1696)."""
    merged: List[Line] = []
    for ln in sorted(lines, key=lambda l: (l.pos, l.start)):
        for m in merged:
            if abs(m.pos - ln.pos) <= 3 and ln.start <= m.end + GAP_FILL * 3 and ln.end >= m.start - GAP_FILL * 3:
                m.start, m.end = min(m.start, ln.start), max(m.end, ln.end)
                m.thick = max(m.thick, ln.thick)
                break
        else:
            merged.append(Line(ln.pos, ln.start, ln.end, ln.thick))
    return merged


def find_frames(gray: np.ndarray, region: Tuple[int, int, int, int]) -> List[Frame]:
    """Plot frames in the region (x0, y0, x1, y1) of a greyscale page image: a bottom
    axis line meeting a left axis line at a corner. Coordinates are page pixels.
    If none: the same with faint ink and shorter lines (pale axes, small panels), then
    plot areas marked only by evenly spaced horizontal gridlines (bar charts without axis
    lines)."""
    frames = _corner_frames(gray, region, DARK, MIN_LINE_FRACTION)
    if not frames:
        grids = _grid_frames(gray, region)
        # a faint "corner" inside a photo (mizuuchi2019's gel) or among bars isn't a plot
        frames = [f for f in _corner_frames(gray, region, FAINT, FAINT_LINE_FRACTION)
                  if _mostly_blank(gray, f) and not any(_overlap(f, g) for g in grids)] + grids
    # the same frame found twice (thick lines): keep one
    unique: List[Frame] = []
    for f in sorted(frames, key=lambda f: (f.top, f.left)):
        if not any(abs(f.left - u.left) < 10 and abs(f.bottom - u.bottom) < 10 for u in unique):
            unique.append(f)
    return unique


def _corner_frames(gray: np.ndarray, region: Tuple[int, int, int, int], ink: int,
                   fraction: float) -> List[Frame]:
    x0, y0, x1, y1 = region
    sub = gray[y0:y1, x0:x1] < ink
    h_lines = _lines(sub, True, max(MIN_LINE_PX, int(fraction * (x1 - x0))))
    v_lines = _lines(sub, False, max(MIN_LINE_PX, int(fraction * (y1 - y0) * 0.5)))
    frames: List[Frame] = []
    for h in h_lines:
        for v in v_lines:
            # bottom-left corner: the vertical line ends at the horizontal one, at its left end
            if abs(v.end - h.pos) <= CORNER_TOL and abs(v.pos - h.start) <= CORNER_TOL * 3:
                # the right side: a vertical line ending at this bottom line, near its right end
                # (outward tick marks can extend the bottom line past the right axis)
                right = [w for w in v_lines if w is not v and abs(w.end - h.pos) <= CORNER_TOL
                         and h.end - 40 <= w.pos <= h.end + CORNER_TOL]
                top = [t for t in h_lines if abs(t.pos - v.start) <= CORNER_TOL and t.start <= v.pos + CORNER_TOL * 3]
                frames.append(Frame(left=x0 + v.pos, right=x0 + (max(w.pos for w in right) if right else h.end),
                                    top=y0 + v.start, bottom=y0 + h.pos,
                                    has_right_axis=bool(right), has_top_axis=bool(top)))
    return frames


def _mostly_blank(gray: np.ndarray, f: Frame) -> bool:
    inside = gray[int(f.top) + 3:int(f.bottom) - 2, int(f.left) + 3:int(f.right) - 2]
    return inside.size > 0 and float((inside < FAINT).mean()) < 0.3


def _overlap(a: Frame, b: Frame) -> bool:
    return a.left < b.right and b.left < a.right and a.top < b.bottom and b.top < a.bottom


def _grid_frames(gray: np.ndarray, region: Tuple[int, int, int, int]) -> List[Frame]:
    """Plot areas drawn only as horizontal gridlines (Riggi2023 Fig. 2): 3 or more lines with
    the same ends, evenly spaced. The lowest is the bottom axis; the gridlines are the y ticks."""
    x0, y0, x1, y1 = region
    sub = gray[y0:y1, x0:x1] < FAINT
    h_lines = _lines(sub, True, max(MIN_LINE_PX, int(FAINT_LINE_FRACTION * (x1 - x0))))
    # grouped by the right end: the tick numbers next to the left end merge into some lines
    groups: List[List[Line]] = []
    for ln in sorted(h_lines, key=lambda l: l.pos):
        for g in groups:
            if abs(g[0].end - ln.end) <= CORNER_TOL and abs(g[0].start - ln.start) <= 4 * CORNER_TOL:
                g.append(ln)
                break
        else:
            groups.append([ln])
    frames = []
    for g in groups:
        left, right = max(ln.start for ln in g), max(ln.end for ln in g)
        # a gridline is inked all along (a legend entry or a line of text isn't), and gridlines are
        # well apart
        covered = lambda y: float(sub[max(int(round(y)) - 1, 0):int(round(y)) + 2, left:right].mean(axis=1).max(initial=0))
        pos = [ln.pos for ln in g if ln.thick <= 3 and covered(ln.pos) >= 0.9]
        # the longest evenly spaced runs of lines -- panels stacked in a column share their ends
        # (Riggi2023 Fig. 2a/2c); a stray line of the same width, e.g. a panel divider, doesn't count
        while len(pos) >= 3:
            best: List[float] = []
            for i in range(len(pos)):
                for j in range(i + 2, len(pos)):
                    if j - i + 1 > len(best) and _even(pos[i:j + 1]) and pos[i + 1] - pos[i] >= 12:
                        best = pos[i:j + 1]
            if not best:
                break
            # the lower gridlines can be hidden in the bars: continue down at the same spacing
            # while the row is still inked all across (gridline or bars); below the axis are labels
            step = (best[-1] - best[0]) / (len(best) - 1)
            y = best[-1] + step
            while y + 2 < sub.shape[0] and covered(y) >= 0.9:
                best.append(y)
                y += step
            frames.append(Frame(left=x0 + left, right=x0 + right, top=y0 + best[0], bottom=y0 + best[-1],
                                has_right_axis=False, has_top_axis=False,
                                gridlines=tuple(y0 + q for q in best)))
            pos = [q for q in pos if not best[0] - 2 <= q <= best[-1] + 2]
    return frames


def find_ticks(gray: np.ndarray, frame: Frame, side: str) -> List[float]:
    """Positions (page pixels) of the major tick marks on one side of a frame:
    'bottom'/'top' -> x positions, 'left'/'right' -> y positions. Ticks may point
    out of the frame or into it; the side with the clearer set is used."""
    dark = gray < DARK
    horizontal_axis = side in ("bottom", "top")
    if horizontal_axis:
        line_pos, a, b = (frame.bottom if side == "bottom" else frame.top), frame.left, frame.right
    else:
        line_pos, a, b = (frame.left if side == "left" else frame.right), frame.top, frame.bottom
    a, b, line_pos = int(round(a)), int(round(b)), int(round(line_pos))
    best: List[float] = []
    for direction in (1, -1):                      # away from the line on either side
        lengths = []
        for t in range(a + 3, b - 2):              # skip the corners
            n = 0
            for d in range(3, TICK_MAX + 3):       # start just past the line's own thickness
                y, x = (line_pos + direction * d, t) if horizontal_axis else (t, line_pos + direction * d)
                if not (0 <= y < dark.shape[0] and 0 <= x < dark.shape[1]) or not dark[y, x]:
                    break
                n += 1
            lengths.append(n)
        lengths = np.array(lengths)
        is_tick = (lengths >= TICK_MIN) & (lengths < TICK_MAX)
        groups = _runs(is_tick)
        if not groups:
            continue
        centres = [a + 3 + (s + e - 1) / 2 for s, e in groups if e - s <= 8]   # a tick is thin
        tick_len = [lengths[s:e].max() for s, e in groups if e - s <= 8]
        if len(centres) < 2:
            continue
        major = max(tick_len)
        keep = [c for c, ln in zip(centres, tick_len) if ln >= 0.75 * major]   # minor ticks are shorter
        if len(keep) > len(best):
            best = keep
    return best


def find_label_positions(gray: np.ndarray, frame: Frame, side: str) -> List[float]:
    """Centres of the tick numbers printed outside one side of the frame, in page
    pixels along the axis (x for 'bottom'/'top', y for 'left'/'right'). The first band
    of ink beyond the axis line (past any tick marks) is the row/column of numbers;
    the axis title further out is ignored."""
    dark = gray < DARK
    h, w = dark.shape
    horizontal_axis = side in ("bottom", "top")
    span = (frame.right - frame.left) if horizontal_axis else (frame.bottom - frame.top)
    margin = int(0.06 * span)
    if horizontal_axis:
        a, b = int(frame.left) - margin, int(frame.right) + margin
        line = int(round(frame.bottom if side == "bottom" else frame.top))
        step = 1 if side == "bottom" else -1
        band = lambda d: dark[line + step * d, max(a, 0):min(b, w)] if 0 <= line + step * d < h else None
    else:
        a, b = int(frame.top) - margin, int(frame.bottom) + margin
        line = int(round(frame.left if side == "left" else frame.right))
        step = -1 if side == "left" else 1
        band = lambda d: dark[max(a, 0):min(b, h), line + step * d] if 0 <= line + step * d < w else None
    # walk outwards: skip the line and ticks (ink attached to the line), then collect the
    # first band of ink -- the numbers -- until a blank gap
    d, profile, started, blank = 3, [], False, 0
    limit = int(0.25 * span)
    while d < limit:
        strip = band(d)
        if strip is None:
            break
        ink = strip.any()
        if started:
            if ink:
                profile.append(strip)
                blank = 0
            else:
                blank += 1
                if blank >= 3:
                    break
        elif ink and d > TICK_MAX + 3 or (ink and not _touches_line(band, d)):
            started = True
            profile.append(strip)
        d += 1
    if not profile:
        return []
    occupied = np.any(np.array(profile), axis=0)
    # characters of one number are close together; numbers are further apart
    groups = _runs(_close(occupied, max(5, int(0.012 * span))))
    centres = [max(a, 0) + (s + e - 1) / 2 for s, e in groups if e - s >= 3]
    return centres


def _touches_line(band, d: int) -> bool:
    """Ink at distance d that continues ink at d-1 (a tick mark or the line itself)."""
    prev, cur = band(d - 1), band(d)
    return prev is not None and bool((prev & cur).any())


def _even(positions: Sequence[float]) -> bool:
    d = np.diff(positions)
    return len(d) >= 1 and bool(np.all(np.abs(d - d.mean()) <= SPACING_TOL * abs(d.mean()) + 1.5))


def pair_ticks(ticks: List[float], labels: List[float]) -> Optional[Tuple[List[float], List[float], bool]]:
    """Pair tick positions (in order along the axis, from its low end) with the printed
    numbers, also in order: (positions, values, is_log), or None if it isn't clear.
    Allows every k-th tick to be labelled and unlabelled ticks at either end."""
    if len(labels) < 2 or len(ticks) < 2:
        return None
    values = list(labels)
    linear = _even(values)
    logged = all(v > 0 for v in values) and _even(np.log10(values))
    if not (linear or logged):
        return None
    options = []
    for k in range(1, len(ticks)):
        for start in range(len(ticks)):
            idx = [start + j * k for j in range(len(values))]
            if idx[-1] >= len(ticks):
                break
            pos = [ticks[i] for i in idx]
            if _even(pos):
                options.append((k, start, pos))
    if not options:
        return None
    # prefer every tick labelled, then labels covering the axis from its start
    k, start, pos = min(options, key=lambda o: (o[0], o[1]))
    if sum(1 for o in options if o[0] == k) > 1 and len(ticks) != len(values):
        return None                      # more than one way to fit: ambiguous
    return pos, values, logged and not linear


def calibrate_axis(gray: np.ndarray, frame: Frame, side: str, labels: List[float],
                   text_numbers: Sequence[Tuple[float, float, float]] = ()) -> Tuple[Tuple, Tuple, bool]:
    """((px, py, value), (px, py, value), is_log) for the axis on `side` of `frame`.
    `text_numbers`: (centre_x, centre_y, value) of numbers in the PDF's text layer near
    the figure, page pixels -- used in preference to `labels` when they line up."""
    horizontal_axis = side in ("bottom", "top")
    line_pos = {"bottom": frame.bottom, "top": frame.top, "left": frame.left, "right": frame.right}[side]
    paired = _pair_with_text(horizontal_axis, line_pos, frame, text_numbers)
    if paired is None and not horizontal_axis and frame.gridlines and len(labels) >= 2:
        paired = _pair_with_gridlines(frame.gridlines, labels)
    if paired is None:
        if not labels:
            raise AutoAxisError(f"no tick numbers for the {side} axis (none in the PDF's text, and none read "
                                f"from the image) -- calibrate it by hand")
        found = find_label_positions(gray, frame, side)
        if len(found) < 2:
            raise AutoAxisError(f"couldn't find the tick numbers along the {side} axis")
        ticks = find_ticks(gray, frame, side)
        if not horizontal_axis:
            ticks = ticks + list(frame.gridlines)       # a gridline at a number is exact too
        # a tick mark right at a number is the exact spot
        found = [min(ticks, key=lambda t: abs(t - c)) if ticks and min(abs(t - c) for t in ticks) < 12 else c
                 for c in found]
        # bottom-left origin: order y positions from the bottom
        ordered = sorted(found) if horizontal_axis else sorted(found, reverse=True)
        values = sorted(labels)
        if len(ordered) != len(values):
            raise AutoAxisError(f"found {len(ordered)} tick numbers along the {side} axis but expected "
                                f"{len(values)} ({', '.join(f'{v:g}' for v in values)}) -- calibrate it by hand")
        if not _even(ordered):
            raise AutoAxisError(f"the tick numbers along the {side} axis aren't evenly spaced -- calibrate "
                                f"it by hand")
        linear = _even(values)
        logged = all(v > 0 for v in values) and _even(np.log10(values))
        if not (linear or logged):
            raise AutoAxisError(f"the {side} axis numbers aren't evenly spaced on a linear or log scale")
        paired = (ordered, values, logged and not linear)
    positions, values, is_log = paired
    # the lowest number printed level with the bottom axis (the usual 0): the numbers' centres sit a
    # few pixels off their ticks (mizuuchi2019, no tick marks) -- move them all onto the line
    if side == "left" and not frame.gridlines and 0 < abs(positions[0] - frame.bottom) <= 6:
        positions = [q + frame.bottom - positions[0] for q in positions]
    p1 = (positions[0], line_pos) if horizontal_axis else (line_pos, positions[0])
    p2 = (positions[-1], line_pos) if horizontal_axis else (line_pos, positions[-1])
    return (*p1, values[0]), (*p2, values[-1]), is_log


def _pair_with_gridlines(gridlines: Sequence[float], labels: List[float]):
    """A frame found from its gridlines: the top gridline carries the highest number and each
    lower one the next (the lowest ones can be hidden by bars, so pairing starts at the top)."""
    values = sorted(labels, reverse=True)
    lines = sorted(gridlines)
    if len(lines) > len(values):
        # numbers on every k-th gridline; otherwise unclear which -- the numbers are located instead
        k, rest = divmod(len(lines) - 1, len(values) - 1) if len(values) > 1 else (0, 1)
        if rest:
            return None
        lines = lines[::k]
    n = min(len(values), len(lines))
    values, lines = values[:n], lines[:n]
    linear = _even(values)
    logged = all(v > 0 for v in values) and _even(np.log10(values))
    if n < 2 or not (linear or logged):
        return None
    return lines[::-1], values[::-1], logged and not linear


def _pair_with_text(horizontal_axis, line_pos, frame, text_numbers):
    """Numbers in the PDF's text layer printed just outside this axis, in order."""
    if horizontal_axis:
        near = [(cx, v) for cx, cy, v in text_numbers
                if 0 < (cy - line_pos) * (1 if line_pos >= frame.bottom - 1 else -1) < 0.15 * (frame.bottom - frame.top)
                and frame.left - 20 <= cx <= frame.right + 20]
        near.sort()
    else:
        near = [(cy, v) for cx, cy, v in text_numbers
                if 0 < (line_pos - cx) * (1 if line_pos <= frame.left + 1 else -1) < 0.25 * (frame.right - frame.left)
                and frame.top - 20 <= cy <= frame.bottom + 20]
        near.sort(reverse=True)
    if len(near) < 2:
        return None
    positions, values = [p for p, _ in near], [v for _, v in near]
    if not _even(positions):
        return None
    linear = _even(values)
    logged = all(v > 0 for v in values) and _even(np.log10(values))
    if not (linear or logged):
        return None
    return positions, values, logged and not linear


def choose_frame(frames: List[Frame], view_centre: Optional[Tuple[float, float]], index: int) -> Frame:
    """The frame the user is looking at, else the index-th (top to bottom, left to right)."""
    if not frames:
        raise AutoAxisError("couldn't find the plot's frame (its axis lines) in the figure")
    if view_centre is not None:
        inside = [f for f in frames if f.contains(*view_centre)]
        if inside:
            return inside[0]
    ordered = sorted(frames, key=lambda f: (round(f.top / 50), f.left))
    return ordered[min(index, len(ordered) - 1)]


def find_boxes_inside(gray: np.ndarray, frame: Frame) -> List[Tuple[float, float, float, float]]:
    """Bordered rectangles inside a plot frame -- legend boxes -- as (x0, y0, x1, y1) page
    pixels, so markers drawn in a legend aren't taken for data points."""
    pad = 6
    x0, y0 = int(frame.left) + pad, int(frame.top) + pad
    x1, y1 = int(frame.right) - pad, int(frame.bottom) - pad
    if x1 - x0 < 20 or y1 - y0 < 20:
        return []
    sub = gray[y0:y1, x0:x1] < DARK
    h_lines = _lines(sub, True, int(0.08 * (x1 - x0)))
    v_lines = _lines(sub, False, int(0.04 * (y1 - y0)))
    boxes = []
    for top in h_lines:
        for bottom in h_lines:
            if bottom.pos - top.pos < 15 or abs(top.start - bottom.start) > CORNER_TOL or abs(top.end - bottom.end) > CORNER_TOL:
                continue
            sides = [v for v in v_lines if v.start <= top.pos + CORNER_TOL and v.end >= bottom.pos - CORNER_TOL
                     and (abs(v.pos - top.start) <= CORNER_TOL or abs(v.pos - top.end) <= CORNER_TOL)]
            if len(sides) >= 2:
                boxes.append((x0 + top.start, y0 + top.pos, x0 + top.end, y0 + bottom.pos))
    return boxes
