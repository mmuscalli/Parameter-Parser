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


def try_pixel_to_data(panel: DigitizedPanel, px: float, py: float) -> Optional[Tuple[float, float]]:
    try:
        return pixel_to_data(panel, px, py)
    except CalibrationError:
        return None
