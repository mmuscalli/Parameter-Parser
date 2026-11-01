"""
Pixel -> data-value conversion for a digitized plot panel.

The user marks two points on the x axis (X1, X2) and two on the y axis
(Y1, Y2) and types their values, as in PlotDigitizer. Each axis is read
independently: the x value comes from projecting the point onto the line
X1->X2, the y value from projecting it onto Y1->Y2. That stays correct for
scans that are rotated (both axes turn together), and -- unlike treating the
two marker lines as a skewed coordinate system, which this replaced -- a Y
marker clicked a few pixels off the axis doesn't make x drift as the cursor
moves vertically (found by Mickey on truman2024). A log axis interpolates in
log10 space.
"""
from __future__ import annotations
import math
from typing import Optional, Tuple

from parameter_extractor.schemas.figures import AxisCalibration, DigitizedPanel


class CalibrationError(ValueError):
    pass


def _fraction_along(origin, direction, point) -> float:
    """How far `point` lies along origin->origin+direction (0 at origin, 1 at the
    end), by perpendicular projection onto that line."""
    dx, dy = direction
    return ((point[0] - origin[0]) * dx + (point[1] - origin[1]) * dy) / (dx * dx + dy * dy)


def _interp(frac: float, v1: float, v2: float, log: bool) -> float:
    if log:
        return 10 ** (math.log10(v1) + frac * (math.log10(v2) - math.log10(v1)))
    return v1 + frac * (v2 - v1)


def _check(cal: AxisCalibration, axis: str) -> None:
    if not cal.complete():
        if cal.log and cal.p1 and cal.p2 and ((cal.p1.value or 0) <= 0 or (cal.p2.value or 0) <= 0):
            raise CalibrationError(f"Log-scale {axis} axis needs positive reference values.")
        raise CalibrationError(f"The {axis} axis isn't calibrated yet: mark two points on it and "
                               f"enter two different values.")


def pixel_to_data(panel: DigitizedPanel, px: float, py: float) -> Tuple[float, float]:
    """Axis values (as read off the plot, before any multiplier) at a pixel."""
    xc, yc = panel.x_cal, panel.y_cal
    _check(xc, "x")
    _check(yc, "y")
    ex = (xc.p2.px - xc.p1.px, xc.p2.py - xc.p1.py)
    ey = (yc.p2.px - yc.p1.px, yc.p2.py - yc.p1.py)
    lx, ly = math.hypot(*ex), math.hypot(*ey)
    if lx < 1e-6 or ly < 1e-6:
        raise CalibrationError(f"The two {'X' if lx < 1e-6 else 'Y'} reference points are at the same "
                               f"place -- put them far apart on the axis.")
    if abs(ex[0] * ey[0] + ex[1] * ey[1]) / (lx * ly) > 0.9:
        raise CalibrationError("The x and y axis reference points run in the same direction -- set the "
                               "X points along the x axis and the Y points along the y axis.")
    s = _fraction_along((xc.p1.px, xc.p1.py), ex, (px, py))
    t = _fraction_along((yc.p1.px, yc.p1.py), ey, (px, py))
    return (_interp(s, xc.p1.value, xc.p2.value, xc.log),
            _interp(t, yc.p1.value, yc.p2.value, yc.log))


def pixel_to_y(panel: DigitizedPanel, px: float, py: float) -> float:
    """The y value alone, for a plot whose x axis isn't numeric (bars of categories: Riggi2023)."""
    yc = panel.y_cal
    _check(yc, "y")
    ey = (yc.p2.px - yc.p1.px, yc.p2.py - yc.p1.py)
    if math.hypot(*ey) < 1e-6:
        raise CalibrationError("The two Y reference points are at the same place -- put them far apart on the axis.")
    return _interp(_fraction_along((yc.p1.px, yc.p1.py), ey, (px, py)), yc.p1.value, yc.p2.value, yc.log)


def _fraction_of(value: float, v1: float, v2: float, log: bool) -> float:
    if log:
        return (math.log10(value) - math.log10(v1)) / (math.log10(v2) - math.log10(v1))
    return (value - v1) / (v2 - v1)


def is_categorical(panel: DigitizedPanel) -> bool:
    """An x axis of categories (bars): marked so, or with no column and no x calibration."""
    return bool(getattr(panel.x, "categorical", False)) or (not panel.x.column and not panel.x_cal.complete())


def rounded(value: float, decimals: Optional[int]) -> float:
    return value if decimals is None else round(value, decimals)


def snap(panel: DigitizedPanel, px: float, py: float) -> Tuple[float, float]:
    """The pixel whose axis values are this pixel's, rounded to each axis's `decimals` (Mickey, 2026-10-31:
    a click at x = 1.018 on an integer axis lands on 1). Unchanged where an axis has no rounding or isn't
    calibrated. Each axis is a projection, so the new pixel solves both projections at once; a category
    axis isn't rounded (the point only moves along y)."""
    xd, yd = panel.x.decimals, panel.y.decimals
    yc = panel.y_cal
    if yd is None and xd is None or not yc.complete():
        return px, py
    ey = (yc.p2.px - yc.p1.px, yc.p2.py - yc.p1.py)
    t = _fraction_along((yc.p1.px, yc.p1.py), ey, (px, py))
    t_new = t if yd is None else _fraction_of(round(_interp(t, yc.p1.value, yc.p2.value, yc.log), yd),
                                               yc.p1.value, yc.p2.value, yc.log)
    xc = panel.x_cal
    if is_categorical(panel) or not xc.complete():
        return px + (t_new - t) * ey[0], py + (t_new - t) * ey[1]
    ex = (xc.p2.px - xc.p1.px, xc.p2.py - xc.p1.py)
    s = _fraction_along((xc.p1.px, xc.p1.py), ex, (px, py))
    s_new = s if xd is None else _fraction_of(round(_interp(s, xc.p1.value, xc.p2.value, xc.log), xd),
                                               xc.p1.value, xc.p2.value, xc.log)
    # (q - X1).ex = s_new |ex|^2 and (q - Y1).ey = t_new |ey|^2: two linear equations for q
    a1, b1 = ex
    c1 = s_new * (a1 * a1 + b1 * b1) + a1 * xc.p1.px + b1 * xc.p1.py
    a2, b2 = ey
    c2 = t_new * (a2 * a2 + b2 * b2) + a2 * yc.p1.px + b2 * yc.p1.py
    det = a1 * b2 - a2 * b1
    if abs(det) < 1e-9:
        return px, py
    return (c1 * b2 - c2 * b1) / det, (a1 * c2 - a2 * c1) / det


def try_pixel_to_data(panel: DigitizedPanel, px: float, py: float) -> Optional[Tuple[float, float]]:
    try:
        return pixel_to_data(panel, px, py)
    except CalibrationError:
        return None
