"""
Optional automatic point finding: the user clicks one marker of a series as an
example, and markers that look the same are found in the plot area by local
normalised cross-correlation (numpy FFT; no image libraries).

  - the example's size is estimated from the ink around the click (a filled
    or open marker; lines through it are tolerated);
  - matches above a similarity threshold, at least a marker's width apart,
    are returned best first; positions already clicked are skipped;
  - shape matters: filled circles, open circles and triangles score
    differently, so each series is found separately. Legend markers look
    the same as data markers and are returned too unless the legend is
    outside the search area -- the user removes them (right-click).

All found points are added as one undoable step; the user checks them.
"""
from __future__ import annotations
from typing import List, Optional, Sequence, Tuple

import numpy as np

DARK = 140
DEFAULT_THRESHOLD = 0.75
MIN_RADIUS, MAX_RADIUS = 4, 40


def marker_radius(gray: np.ndarray, x: float, y: float) -> int:
    """Half the size of the marker under (x, y): the radius beyond which the ink around
    the click thins out to lines or nothing."""
    dark = gray < DARK
    h, w = dark.shape
    cx, cy = int(round(x)), int(round(y))
    yy, xx = np.mgrid[-MAX_RADIUS - 1:MAX_RADIUS + 2, -MAX_RADIUS - 1:MAX_RADIUS + 2]
    dist = np.hypot(xx, yy)
    y0, x0 = cy - MAX_RADIUS - 1, cx - MAX_RADIUS - 1
    if y0 < 0 or x0 < 0 or y0 + dist.shape[0] > h or x0 + dist.shape[1] > w:
        return 10
    patch = dark[y0:y0 + dist.shape[0], x0:x0 + dist.shape[1]]
    seen_ink = False
    for r in range(MIN_RADIUS, MAX_RADIUS):
        ring = patch[(dist >= r - 0.5) & (dist < r + 0.5)]
        frac = ring.mean() if ring.size else 0
        if frac > 0.3:
            seen_ink = True
        elif seen_ink and frac < 0.15:      # left the marker: only lines (or nothing) cross here
            return r + 1
    return 10


def centre_marker(gray: np.ndarray, x: float, y: float, iterations: int = 3) -> Tuple[float, float]:
    """The marker's centre near a click: the centroid of the ink within the marker's
    radius, repeated a few times. A click a few pixels off would otherwise shift every
    match by the same amount."""
    for _ in range(iterations):
        r = marker_radius(gray, x, y)
        x0, y0 = int(round(x)) - r, int(round(y)) - r
        patch = gray[max(y0, 0):y0 + 2 * r + 1, max(x0, 0):x0 + 2 * r + 1] < DARK
        if not patch.any():
            break
        yy, xx = np.nonzero(patch)
        nx, ny = max(x0, 0) + xx.mean(), max(y0, 0) + yy.mean()
        if abs(nx - x) < 0.5 and abs(ny - y) < 0.5:
            break
        x, y = nx, ny
    return float(x), float(y)


def _box_sum(a: np.ndarray, kh: int, kw: int) -> np.ndarray:
    """Sum over every kh x kw window (valid positions), via an integral image."""
    s = np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    return s[kh:, kw:] - s[:-kh, kw:] - s[kh:, :-kw] + s[:-kh, :-kw]


def match_scores(region: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation of the template at every valid position of the region."""
    region = region.astype(np.float64)
    t = template.astype(np.float64)
    th, tw = t.shape
    t = t - t.mean()
    t_norm = np.sqrt((t ** 2).sum())
    if t_norm == 0:
        return np.zeros((region.shape[0] - th + 1, region.shape[1] - tw + 1))
    shape = (region.shape[0] + th - 1, region.shape[1] + tw - 1)
    corr = np.fft.irfft2(np.fft.rfft2(region, shape) * np.fft.rfft2(t[::-1, ::-1], shape), shape)
    corr = corr[th - 1:region.shape[0], tw - 1:region.shape[1]]
    n = th * tw
    s1 = _box_sum(region, th, tw)
    s2 = _box_sum(region ** 2, th, tw)
    var = np.maximum(s2 - s1 ** 2 / n, 1e-9)
    return corr / (np.sqrt(var) * t_norm)


def find_similar_points(gray: np.ndarray, example: Tuple[float, float], area: Tuple[float, float, float, float],
                        existing: Sequence[Tuple[float, float]] = (), threshold: float = DEFAULT_THRESHOLD,
                        radius: Optional[int] = None,
                        exclude: Sequence[Tuple[float, float, float, float]] = ()) -> List[Tuple[float, float, float]]:
    """(x, y, score) of markers like the one at `example`, inside `area` (x0, y0, x1, y1),
    page pixels; positions within a marker's width of `existing` points, and inside the
    `exclude` rectangles (legend boxes), are left out."""
    r = radius or marker_radius(gray, *example)
    ex, ey = int(round(example[0])), int(round(example[1]))
    template = gray[ey - r:ey + r + 1, ex - r:ex + r + 1]
    if template.shape != (2 * r + 1, 2 * r + 1):
        return []
    x0, y0, x1, y1 = (int(round(v)) for v in area)
    x0, y0 = max(x0 - r, 0), max(y0 - r, 0)
    x1, y1 = min(x1 + r + 1, gray.shape[1]), min(y1 + r + 1, gray.shape[0])
    region = gray[y0:y1, x0:x1]
    if region.shape[0] <= 2 * r + 1 or region.shape[1] <= 2 * r + 1:
        return []
    scores = match_scores(region, template)
    found: List[Tuple[float, float, float]] = []
    taken = [(float(px), float(py)) for px, py in existing]
    order = np.argsort(scores, axis=None)[::-1]
    for flat in order:
        score = scores.flat[flat]
        if score < threshold:
            break
        sy, sx = divmod(int(flat), scores.shape[1])
        cx, cy = x0 + sx + r, y0 + sy + r
        if any((cx - px) ** 2 + (cy - py) ** 2 < (1.5 * r) ** 2 for px, py in taken):
            continue
        if any(bx0 <= cx <= bx1 and by0 <= cy <= by1 for bx0, by0, bx1, by1 in exclude):
            continue
        taken.append((cx, cy))
        found.append((float(cx), float(cy), float(score)))
        if len(found) >= 500:
            break
    return found
