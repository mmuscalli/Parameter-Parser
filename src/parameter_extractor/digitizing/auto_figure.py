"""
Digitizing a figure without the editor (Mickey, 2026-11-03): the model's suggestions (a FigurePlan) applied to a
DigitizedFigure, its axes calibrated (auto_axes.py), its bar tops / markers found and sorted into the series
(auto_detect.py), error bars included -- the same steps the digitizer's buttons run (gui/digitizer.py calls these).

`auto_digitize` does all of it and says whether the figure was EASY: only then may it go into the dataset without
the user opening it ("Digitize easy figures automatically"). Easy means: a numeric data plot of bars or markers,
not a duplicate of a table, every coordinate system's axes calibrated (y always; x unless categories), every series
given points, every point found assigned to a series, and no series left ambiguous. Anything else is reported with
its reason, and the figure is left for the user.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from parameter_extractor.digitizing.calibration import snap
from parameter_extractor.schemas.figures import (AxisCalibration, AxisVariable, CalibrationPoint, DigitizedFigure,
                                                 DigitizedPanel, DigitizedPoint, DigitizedSeries, FigurePlan,
                                                 SpeciesAmount)

# automatic points snap to whole numbers within this many pixels, else to 2 decimals (2026-11-03: Riggi2023's bars
# ending on whole lengths read 2.07 / 4.03 with the axis line a few pixels off; averages like 3.5 stay)
AUTO_WHOLE_WITHIN_PX = 3.0
AUTO_DECIMALS = 2


# ---- the model's suggestions -> the figure's coordinate systems and series ------------------------------------

def fill_concentrations(series: List[DigitizedSeries], found) -> None:
    """Fill each series' species that have no concentration from the plan's list of
    concentrations found in the paper (converted to mM here, never by the model);
    adds the species if the series doesn't list it yet."""
    from parameter_extractor.units import to_column_unit
    for c in found:
        conv = to_column_unit(c.value, None, "mM")
        if conv is None:
            continue
        labels = {l.strip().lower() for l in c.series}
        for s in series:
            base = re.sub(r"\s*\[[^\]]*\]$", "", s.label).strip().lower()   # label without " [marker]"
            if labels and base not in labels and s.label.strip().lower() not in labels:
                continue
            source = f"{'indirect -- ' if c.basis == 'indirect' else ''}{c.source or 'stated in the paper'} " \
                     f"('{c.value}')"
            for i, sp in enumerate(s.initial_species):
                if sp.name.strip().lower() == c.species.strip().lower():
                    if sp.concentration_mM is None:
                        s.initial_species[i] = sp.model_copy(update=dict(
                            concentration_mM=conv.value, basis=c.basis, source=source))
                    break
            else:
                s.initial_species.append(SpeciesAmount(name=c.species, concentration_mM=conv.value,
                                                       basis=c.basis, source=source))


def with_shared(own: list, shared: list) -> list:
    """A series' conditions: its own, plus the figure's shared ones it doesn't set itself."""
    columns = {c.column for c in own}
    return [c.model_copy() for c in own] + [c.model_copy() for c in shared if c.column not in columns]


def with_new_column(var: AxisVariable) -> AxisVariable:
    """A suggested axis with the NEW column the model proposed when none fits, loaded into the column field
    (averaged values: '_avg' added) -- the user sees it while digitizing, and the review asks to accept it."""
    if var.column or not var.new_column or var.categorical:
        return var.model_copy()
    from parameter_extractor.ingestion.flatten_to_template import with_average
    return var.model_copy(update={"column": with_average(var.new_column) if var.average else var.new_column})


def apply_plan(fig: DigitizedFigure, plan: FigurePlan) -> bool:
    """The plan's coordinate systems and series into the figure (points already clicked are kept, by position in
    the list). False when the plan has no coordinate systems."""
    old_panels, old_series = fig.panels, fig.series
    panels, series = [], []
    for i, pp in enumerate(plan.panels or []):
        base = old_panels[i] if i < len(old_panels) else DigitizedPanel()
        x_cal = base.x_cal.model_copy(update={"log": pp.x.scale == "log"})
        y_cal = base.y_cal.model_copy(update={"log": pp.y.scale == "log"})
        panels.append(DigitizedPanel(name=pp.name, x_cal=x_cal, y_cal=y_cal, x=with_new_column(pp.x),
                                     y=with_new_column(pp.y)))
        for ps in pp.series:
            label = ps.label + (f" [{ps.marker}]" if ps.marker and ps.marker not in ps.label else "")
            series.append(DigitizedSeries(
                label=label, panel=i, initial_species=list(ps.initial_species),
                initial_temperature_C=ps.initial_temperature_C, initial_pH=ps.initial_pH,
                conditions=with_shared(ps.conditions, plan.shared_conditions), y_column=ps.y_column,
                notes=ps.notes))
    if not panels:
        return False
    fill_concentrations(series, plan.concentrations)
    for i, s in enumerate(old_series):
        if s.points:
            if i < len(series):
                series[i].points = s.points
            else:
                series.append(s.model_copy(update={"panel": min(s.panel, len(panels) - 1)}))
    fig.plan = plan
    fig.panels, fig.series = panels, series
    if getattr(plan, "rows_by_x", False):          # one row per x value, the series its columns (2026-11-12)
        fig.rows_by_x = True
    return True


# ---- the page image ---------------------------------------------------------------------------------------------

class FigureImage:
    """The figure's page render, as greyscale and RGB arrays, and its plot frames (computed once)."""

    def __init__(self, fig: DigitizedFigure):
        self.fig = fig
        self._gray = self._rgb = self._frames = None

    @property
    def gray(self):
        if self._gray is None:
            import numpy as np
            from PIL import Image
            self._gray = np.asarray(Image.open(self.fig.page_image).convert("L"))
        return self._gray

    @property
    def rgb(self):
        if self._rgb is None:
            import numpy as np
            from PIL import Image
            self._rgb = np.asarray(Image.open(self.fig.page_image).convert("RGB"))
        return self._rgb

    def region(self) -> Tuple[int, int, int, int]:
        g = self.gray
        if self.fig.figure_bbox:
            s = self.fig.render_scale
            x0, y0, x1, y1 = (v * s for v in self.fig.figure_bbox)
            pad = 30
            return (max(int(x0) - pad, 0), max(int(y0) - pad, 0), min(int(x1) + pad, g.shape[1]),
                    min(int(y1) + pad, g.shape[0]))
        return 0, 0, g.shape[1], g.shape[0]

    @property
    def frames(self):
        if self._frames is None:
            from parameter_extractor.digitizing.auto_axes import find_frames
            self._frames = find_frames(self.gray, self.region())
        return self._frames


def panel_sides(name: str):
    """Which frame sides a coordinate system reads from, and its base name: '(a) right
    y-axis' -> ('bottom', 'right', '(a)')."""
    low = name.lower()
    # whole words: "diketopiperazine" contains "top" (a planner panel name, alargov2002)
    y_side = "right" if re.search(r"\bright\b", low) else "left"
    x_side = "top" if re.search(r"\btop\b", low) else "bottom"
    base = re.sub(r"\b(left|right|top|bottom|secondary|primary)\b|\b[xy][- ]?axis\b|\baxis\b", "", low)
    return x_side, y_side, re.sub(r"[\s,;:-]+", " ", base).strip()


# ---- calibration --------------------------------------------------------------------------------------------------

def calibrate_panel(fig: DigitizedFigure, image: FigureImage, panel_idx: int,
                    view_centre: Optional[Tuple[float, float]] = None) -> Tuple[str, Dict[str, bool]]:
    """Place a coordinate system's calibration markers automatically: (message, {'x': ok, 'y': ok}); a category x
    axis counts as ok (nothing to calibrate)."""
    from parameter_extractor.digitizing.auto_axes import AutoAxisError, calibrate_axis, choose_frame
    panel = fig.panels[panel_idx]
    x_side, y_side, base = panel_sides(panel.name)
    bases = list(dict.fromkeys(panel_sides(p.name)[2] for p in fig.panels))
    notes, ok = [], {"x": False, "y": False}
    try:
        frame = choose_frame(image.frames, view_centre, bases.index(base))
    except AutoAxisError as e:
        notes.append(str(e))
    else:
        for axis, side, var in (("x", x_side, panel.x), ("y", y_side, panel.y)):
            if axis == "x" and (var.categorical or not var.column and not var.tick_labels):
                notes.append("X: categories (bars), no calibration needed")
                ok["x"] = True
                continue
            try:
                (ax, ay, av), (bx, by, bv), is_log = calibrate_axis(
                    image.gray, frame, side, list(var.tick_labels), fig.tick_numbers)
            except AutoAxisError as e:
                notes.append(f"{axis.upper()}: {e}")
                continue
            cal: AxisCalibration = getattr(panel, f"{axis}_cal")
            setattr(panel, f"{axis}_cal", AxisCalibration(
                p1=CalibrationPoint(px=float(ax), py=float(ay), value=float(av)),
                p2=CalibrationPoint(px=float(bx), py=float(by), value=float(bv)), log=cal.log or is_log))
            notes.append(f"{axis.upper()}: {av:g} to {bv:g} placed")
            ok[axis] = True
    return f"{panel.name}: " + "; ".join(notes) + " -- check the markers.", ok


def frame_of(fig: DigitizedFigure, image: FigureImage, panel_idx: int,
             view_centre: Optional[Tuple[float, float]] = None):
    """The plot frame a coordinate system reads from: the one holding its calibration markers, else the
    one in view, else by its place among the coordinate systems."""
    from parameter_extractor.digitizing.auto_axes import choose_frame
    frames = image.frames
    panel = fig.panels[panel_idx]
    marks = [(c.px, c.py) for cal in (panel.x_cal, panel.y_cal) for c in (cal.p1, cal.p2) if c]
    if marks and frames:
        mx = sum(x for x, _ in marks) / len(marks)
        my = sum(y for _, y in marks) / len(marks)
        near = lambda f: max(f.left - mx, 0, mx - f.right) + max(f.top - my, 0, my - f.bottom)
        best = min(frames, key=near)
        if near(best) < 40:
            return best
    bases = list(dict.fromkeys(panel_sides(p.name)[2] for p in fig.panels))
    return choose_frame(frames, view_centre, bases.index(panel_sides(panel.name)[2]))


def _frame_key(fig, image, panel_idx: int):
    try:
        f = frame_of(fig, image, panel_idx)
    except Exception:
        return None
    return (f.left, f.top, f.right, f.bottom)


# ---- points ---------------------------------------------------------------------------------------------------------

@dataclass
class PointsResult:
    added: List[Tuple[int, List[int]]] = field(default_factory=list)       # (series, point indexes) for undo
    error_bars: List[Tuple[int, int]] = field(default_factory=list)        # (series, point) that got one
    notes: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)                     # why it isn't 'easy'

    @property
    def message(self) -> str:
        return "\n".join(self.notes)


def find_points(fig: DigitizedFigure, image: FigureImage, panels: Sequence[int],
                view_centre: Optional[Tuple[float, float]] = None, error_bars: bool = True) -> PointsResult:
    """Find bar tops / marker centres (and their error bars) in the frames of the given coordinate systems and add
    them to the series there that have no points yet."""
    from parameter_extractor.digitizing.auto_axes import AutoAxisError, find_boxes_inside
    from parameter_extractor.digitizing.auto_detect import (assign_to_series, detect_points, find_error_bars,
                                                            group_by_appearance)
    out = PointsResult()
    by_frame = {}
    for pi in panels:
        try:
            frame = frame_of(fig, image, pi, view_centre)
        except AutoAxisError as e:
            out.notes.append(f"{fig.panels[pi].name}: {e}")
            out.problems.append(f"{fig.panels[pi].name}: no plot frame")
            continue
        key = (frame.left, frame.top, frame.right, frame.bottom)
        by_frame.setdefault(key, (frame, []))[1].append(pi)
    for key, (frame, group) in by_frame.items():
        # every coordinate system drawn in this frame (a second y axis shares it)
        group = sorted(set(group) | {i for i in range(len(fig.panels)) if i not in group
                                     and _frame_key(fig, image, i) == key})
        series = [i for i, s in enumerate(fig.series) if min(s.panel, len(fig.panels) - 1) in group]
        names = ", ".join(fig.panels[i].name for i in group)
        if not series:
            out.notes.append(f"{names}: no series to put points in")
            continue
        plot = fig.plan.plot_kind if fig.plan else ""
        kind = ("bars" if plot == "bar" or any(fig.panels[i].x.categorical for i in group)
                else "markers" if plot in ("scatter", "scatter_with_fit") else "auto")
        box = (frame.left, frame.top, frame.right, frame.bottom)
        found, used = detect_points(image.rgb, box, kind,
                                    exclude=find_boxes_inside(image.gray, frame) + list(fig.text_boxes),
                                    tick_numbers=fig.tick_numbers)
        if not found:
            out.notes.append(f"{names}: no {'bars' if used == 'bars' else 'markers'} found")
            out.problems.append(f"{names}: nothing found")
            continue
        bars = find_error_bars(image.rgb, box, found) if error_bars else {}
        index = {id(f): i for i, f in enumerate(found)}
        assigned, note = assign_to_series(group_by_appearance(found), [fig.series[i].label for i in series])
        if note:
            out.problems.append(f"{names}: {note}")
        existing = [(p.px, p.py) for i in series for p in fig.series[i].points]
        counts, with_bars = [], 0
        for k, pts in assigned.items():
            si = series[k]
            s = fig.series[si]
            if s.points:
                continue                          # the user's points are never touched
            panel = fig.panels[min(s.panel, len(fig.panels) - 1)]
            start = len(s.points)
            for f in sorted(pts, key=lambda f: (f.x, f.y)):
                if any((f.x - x) ** 2 + (f.y - y) ** 2 < max(f.size, 6) ** 2 for x, y in existing):
                    continue
                x, y = snap(panel, f.x, f.y)
                hi, lo = bars.get(index[id(f)], (None, None))
                s.points.append(DigitizedPoint(px=x, py=y, err_hi_py=hi, err_lo_py=lo))
                if hi is not None or lo is not None:
                    out.error_bars.append((si, len(s.points) - 1))
                    with_bars += 1
            if len(s.points) > start:
                out.added.append((si, list(range(start, len(s.points)))))
                counts.append(f"{len(s.points) - start} to '{s.label}'")
        for k, si in enumerate(series):
            if k not in assigned and not fig.series[si].points:
                out.problems.append(f"no points for '{fig.series[si].label}'")
        what = "bar tops" if used == "bars" else "markers"
        msg = f"{names}: {len(found)} {what} found" + (f"; added {', '.join(counts)}" if counts else
                                                       "; none added (series already have points)" if assigned
                                                       else "")
        if with_bars:
            msg += f"; {with_bars} with error bars"
        out.notes.append(msg + (f". {note}" if note else ""))
    return out


# ---- the whole figure -------------------------------------------------------------------------------------------

def figure_for(candidate) -> DigitizedFigure:
    """An empty DigitizedFigure for a found figure (ingestion/figure_finder.FigureCandidate)."""
    f = candidate
    return DigitizedFigure(figure_id=f.figure_id, number=f.number, page=f.page, caption=f.caption,
                           render_scale=f.render_scale, page_image=f.page_image, figure_bbox=f.figure_bbox,
                           tick_numbers=list(f.tick_numbers), text_boxes=list(f.text_boxes),
                           supplement=f.supplement, page_label=f.page_label, prefix=f.prefix)


@dataclass
class AutoResult:
    figure: DigitizedFigure
    easy: bool
    reasons: List[str]
    summary: str


def auto_digitize(fig: DigitizedFigure, plan: Optional[FigurePlan]) -> AutoResult:
    """Suggestions applied, axes calibrated, points (and error bars) found; `easy` says whether the result may go
    into the dataset without the user checking it in the editor (see the module docstring)."""
    reasons: List[str] = []
    if plan is None:
        return AutoResult(fig, False, ["no suggestions for this figure"], "")
    if not plan.is_data_plot:
        reasons.append("not a numeric data plot")
    if plan.duplicates_tabulated_data:
        reasons.append("may repeat a table's data")
    if plan.plot_kind not in ("bar", "scatter", "scatter_with_fit"):
        reasons.append(f"a {plan.plot_kind or 'kind of'} plot (only bar charts and scatter plots are parsed "
                       f"automatically)")
    if reasons or not apply_plan(fig, plan):
        return AutoResult(fig, False, reasons or ["the suggestions have no coordinate systems"], "")
    for panel in fig.panels:                 # whole numbers when within a few pixels, else 2 decimals
        for var in (panel.x, panel.y):
            if var.decimals is None and not var.whole_within_px:
                var.decimals, var.whole_within_px = AUTO_DECIMALS, AUTO_WHOLE_WITHIN_PX
    image = FigureImage(fig)
    notes = []
    for i, panel in enumerate(fig.panels):
        msg, ok = calibrate_panel(fig, image, i)
        notes.append(msg)
        for axis, done in ok.items():
            if not done:
                reasons.append(f"{panel.name}: {axis} axis not calibrated")
    if not reasons:
        result = find_points(fig, image, list(range(len(fig.panels))))
        notes += result.notes
        reasons += result.problems
        if not any(s.points for s in fig.series):
            reasons.append("no points found")
    if not reasons:
        fig.auto_digitized, fig.auto_summary = True, "\n".join(notes)
    return AutoResult(fig, not reasons, reasons, "\n".join(notes))
