"""
Pixel -> data-value conversion for a digitized plot panel.

The user marks two points on the x axis (X1, X2) and two on the y axis
(Y1, Y2) and types their values, as in PlotDigitizer. Rather than assuming
the image is perfectly level, the two axis directions ex = X2 - X1 and
ey = Y2 - Y1 (in pixels) are used as a basis: any clicked point P is written
as P = origin + s*ex + t*ey, which stays correct for scans that are slightly
rotated or sheared. A log axis interpolates in log10 space.
"""
from __future__ import annotations
import math
from typing import Optional, Tuple

from parameter_extractor.schemas.figures import AxisCalibration, DigitizedPanel


class CalibrationError(ValueError):
    pass


def _solve(ex, ey, d) -> Tuple[float, float]:
    """Solve s*ex + t*ey = d for (s, t)."""
    det = ex[0] * ey[1] - ex[1] * ey[0]
    if abs(det) < 1e-9:
        raise CalibrationError("The x and y axis reference points are parallel -- set the x "
                               "points along the x axis and the y points along the y axis.")
    s = (d[0] * ey[1] - d[1] * ey[0]) / det
    t = (ex[0] * d[1] - ex[1] * d[0]) / det
    return s, t


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
    # fraction along the x axis: decompose P - X1 in the (ex, ey) basis
    s, _ = _solve(ex, ey, (px - xc.p1.px, py - xc.p1.py))
    # fraction along the y axis: decompose P - Y1 in the same basis
    _, t = _solve(ex, ey, (px - yc.p1.px, py - yc.p1.py))
    return (_interp(s, xc.p1.value, xc.p2.value, xc.log),
            _interp(t, yc.p1.value, yc.p2.value, yc.log))


def try_pixel_to_data(panel: DigitizedPanel, px: float, py: float) -> Optional[Tuple[float, float]]:
    try:
        return pixel_to_data(panel, px, py)
    except CalibrationError:
        return None
