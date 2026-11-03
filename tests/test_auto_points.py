"""
Offline tests for automatic data-point finding (digitizing/auto_detect.py: bar tops and marker centres) and
the digitizer's new controls -- 'Clear all axis markers', Tab / Shift+Tab to the next / previous series,
'Find points automatically' (Mickey, 2026-11-03). Synthetic charts with known positions, plus Riggi2023
Fig. 3 (bars) and alargov2002 Fig. 3 (markers on two y axes) when the PDFs are present. No API calls; the
GUI part runs offscreen.

Run with: python tests/test_auto_points.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from PIL import Image, ImageDraw

from parameter_extractor.digitizing.auto_detect import (assign_to_series, describe, detect_points, find_bars,
                                                        find_markers, group_by_appearance, shape_of)

PAPERS = ROOT.parent / "Paper Files"
RIGGI = PAPERS / "Test Paper List" / "Riggi2023.pdf"
ALARGOV = PAPERS / "Paper Lists" / "Alargov2002" / "alargov2002.pdf"
FRAME = (100, 80, 850, 600)
KIND = "bar"


def _canvas():
    im = Image.new("RGB", (900, 700), "white")
    d = ImageDraw.Draw(im)
    d.line([(100, 600), (850, 600)], fill="black", width=3)
    d.line([(100, 600), (100, 80)], fill="black", width=3)
    for y in range(100, 600, 100):
        d.line([(102, y), (850, y)], fill=(210, 210, 210), width=2)       # pale gridlines: not ink
    return im, d


def test_bar_tops_solid_hollow_and_grouped():
    im, d = _canvas()
    truth = []
    for i, (h, col) in enumerate([(200, (100, 100, 100)), (300, (50, 120, 205)), (340, (50, 120, 205))]):
        x0, top = 200 + i * 112, 600 - h
        d.rectangle([x0, top, x0 + 110, 598], fill=col)                    # touching bars, 2 px apart
        truth.append((x0 + 55, top))
    d.line([(479, 220), (479, 300)], fill=(60, 60, 60), width=2)            # an error bar on the third
    bars, kind = detect_points(np.asarray(im), FRAME)
    assert kind == "bars" and [(round(b.x), round(b.y)) for b in bars] == truth

    im, d = _canvas()
    for i, h in enumerate([150, 260]):
        d.rectangle([200 + i * 180, 600 - h, 290 + i * 180, 599], outline="black", width=2)
    assert [(round(b.x), round(b.y)) for b in find_bars(np.asarray(im), FRAME)] == [(245, 450), (425, 340)]

    im, d = _canvas()
    for g in range(3):
        for s, col in enumerate([(220, 40, 40), (40, 90, 210)]):
            x0, h = 180 + g * 220 + s * 70, 100 + 60 * g + 90 * s
            d.rectangle([x0, 600 - h, x0 + 60, 598], fill=col)
    bars, _ = detect_points(np.asarray(im), FRAME)
    out, note = assign_to_series(group_by_appearance(bars), ["control [red]", "treated [blue]"])
    assert not note and [round(b.x) for b in out[0]] == [210, 430, 650] and [round(b.x) for b in out[1]] == [280, 500, 720]
    # one bar per series (a category chart): left to right
    out, _ = assign_to_series(group_by_appearance(bars), [f"bar {i}" for i in range(6)])
    assert [round(out[i][0].x) for i in range(6)] == [210, 280, 430, 500, 650, 720]


def test_markers_on_lines_sorted_by_description():
    im, d = _canvas()
    rng = np.random.default_rng(1)
    shapes = {"filled circles": lambda x, y: d.ellipse([x - 8, y - 8, x + 8, y + 8], fill="black"),
              "open circles": lambda x, y: d.ellipse([x - 8, y - 8, x + 8, y + 8], outline="black", width=2),
              "▲": lambda x, y: d.polygon([(x, y - 10), (x - 10, y + 7), (x + 10, y + 7)], fill="black"),
              "open squares": lambda x, y: d.rectangle([x - 8, y - 8, x + 8, y + 8], outline="black", width=2)}
    truth = {}
    for k, (name, draw) in enumerate(shapes.items()):
        xs = np.linspace(150, 800, 9)
        ys = 550 - k * 100 - 40 * np.sin(xs / 120) + rng.normal(0, 10, 9)
        d.line(list(zip(xs, ys)), fill="black", width=2)                    # a line through the markers
        for x, y in zip(xs, ys):
            draw(x, y)
        truth[name] = [(x, y + (4 / 3 if name == "▲" else 0)) for x, y in zip(xs, ys)]
    found, kind = detect_points(np.asarray(im), FRAME)
    assert kind == "markers"
    out, note = assign_to_series(group_by_appearance(found), [f"pH {k} [{n}]" for k, n in enumerate(shapes)])
    for k, name in enumerate(shapes):
        got = out[k]
        assert len(got) == 9, (name, len(got))
        assert max(min(np.hypot(f.x - x, f.y - y) for f in got) for x, y in truth[name]) < 2.0, name


def test_shapes_and_descriptions():
    assert describe("open diamond") == {"filled": False, "shape": "diamond"}
    assert describe("filled red triangles") == {"filled": True, "shape": "triangle", "color": (220, 30, 30)}
    assert describe("▽")["shape"] == "down triangle" and describe("crosses (+)")["shape"] == "stroke"
    im = Image.new("RGB", (400, 120), "white")
    d = ImageDraw.Draw(im)
    d.polygon([(60, 72), (48, 51), (72, 51)], fill="black")                  # pointing down
    d.polygon([(160, 48), (172, 69), (148, 69)], fill="black")               # up
    d.polygon([(260, 45), (270, 60), (260, 75), (250, 60)], fill="black")    # diamond
    d.rectangle([340, 50, 360, 70], fill="black")
    found = sorted(find_markers(np.asarray(im), (10, 10, 390, 110)), key=lambda f: f.x)
    assert [shape_of(f) for f in found] == ["down triangle", "triangle", "diamond", "square"]


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _editor(pdf: Path, tag: str, tmp: str):
    from parameter_extractor.gui.digitizer import DigitizerWidget
    from parameter_extractor.ingestion.figure_finder import find_figures
    from parameter_extractor.schemas.figures import DigitizedFigure
    f = next(c for c in find_figures(str(pdf), Path(tmp)) if c.tag == tag)
    fig = DigitizedFigure(figure_id=f.figure_id, number=f.number, page=f.page, caption=f.caption,
                          render_scale=f.render_scale, page_image=f.page_image, figure_bbox=f.figure_bbox,
                          tick_numbers=list(f.tick_numbers), text_boxes=list(f.text_boxes))
    return DigitizerWidget(fig, ["solid_material_name", "max_linear_oligomer_length_nt"])


def test_digitizer_bars_clear_markers_and_tab():
    if not RIGGI.is_file():
        print(f"SKIP: needs {RIGGI}"); return
    _app()
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from parameter_extractor.digitizing.calibration import pixel_to_y
    from parameter_extractor.schemas.figures import AxisVariable, FigurePlan, PlannedPanel, PlannedSeries
    with tempfile.TemporaryDirectory() as tmp:
        ed = _editor(RIGGI, "3", tmp)
        ed.auto_axes_box.setChecked(True)
        ed.auto_points_box.setChecked(True)
        try:
            names = ["pure water negative control", "NaCl-saturated negative control", "halite"]
            ed.apply_plan(FigurePlan(figure_id="Fig. 3", is_data_plot=True, plot_kind=KIND, duplicates_tabulated_data=False, panels=[PlannedPanel(
                name="Fig. 3", x=AxisVariable(label="experiment", column="solid_material_name", categorical=True),
                y=AxisVariable(label="avg. max. linear oligomer length", column=None, tick_labels=[0, 1, 2, 3, 4, 5, 6]),
                series=[PlannedSeries(label=n) for n in names])]))
        finally:
            ed.auto_axes_box.setChecked(False)
            ed.auto_points_box.setChecked(False)
        panel = ed.fig.panels[0]
        values = [round(pixel_to_y(panel, s.points[0].px, s.points[0].py), 2) for s in ed.fig.series]
        # the bar tops sit on the 2 and 4 gridlines; the figure's axis line is ~3 px below where even gridline
        # spacing puts 0, so a 0-to-6 calibration reads 2.07 / 4.03 ('round: whole numbers' fixes that)
        assert all(abs(v - t) < 0.1 for v, t in zip(values, [2, 4, 4])), (values, ed.points_status.text())
        # a second run adds nothing (series have points); Ctrl+Z removes the whole batch
        ed.auto_find_points(use_view=False)
        assert [len(s.points) for s in ed.fig.series] == [1, 1, 1]
        ed.undo()
        assert [len(s.points) for s in ed.fig.series] == [0, 0, 0]

        # Clear all axis markers: every coordinate system, values too; Ctrl+Z restores
        ed._add_panel()
        ed.fig.panels[1].y_cal = panel.y_cal.model_copy()
        ed.clear_axis_markers()
        assert all(c.p1 is None and c.p2 is None for p in ed.fig.panels for c in (p.x_cal, p.y_cal))
        ed.undo()
        assert ed.fig.panels[0].y_cal.p1.value == 0 and ed.fig.panels[1].y_cal.p2 is not None

        # Tab on the figure: next series, wrapping; Shift+Tab back
        ed.series_list.setCurrentRow(0)
        tab = lambda key: ed.canvas.event(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
        tab(Qt.Key.Key_Tab)
        assert ed.series_idx == 1
        tab(Qt.Key.Key_Tab); tab(Qt.Key.Key_Tab)
        assert ed.series_idx == 0                                   # wrapped around
        tab(Qt.Key.Key_Backtab)
        assert ed.series_idx == 2
        ed.series_list.event(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier))
        ed.eventFilter(ed.series_list, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier))
        assert ed.series_idx == 0


def test_digitizer_markers_by_description_on_two_axes():
    """alargov2002 Fig. 3a: Gly-Gly (filled circles) and DKP (open circles) on the left axis, Gly (filled
    triangles) on the right one, all in one frame."""
    if not ALARGOV.is_file():
        print(f"SKIP: needs {ALARGOV}"); return
    _app()
    from parameter_extractor.schemas.figures import AxisVariable, FigurePlan, PlannedPanel, PlannedSeries
    with tempfile.TemporaryDirectory() as tmp:
        ed = _editor(ALARGOV, "3", tmp)
        ed.apply_plan(FigurePlan(figure_id="Fig. 3", is_data_plot=True, plot_kind="scatter_with_fit", duplicates_tabulated_data=False, panels=[
            PlannedPanel(name="(a) left y-axis", x=AxisVariable(label="T", column=None), y=AxisVariable(label="mM", column=None), series=[
                PlannedSeries(label="Gly-Gly", marker="filled circles"),
                PlannedSeries(label="Diketopiperazine", marker="open circles")]),
            PlannedPanel(name="(a) right y-axis", x=AxisVariable(label="T", column=None), y=AxisVariable(label="mM", column=None), series=[
                PlannedSeries(label="Gly", marker="filled triangles")])]))
        ed.auto_find_points([0, 1], use_view=False)
        counts = {s.label.split(" [")[0]: len(s.points) for s in ed.fig.series}
        assert counts == {"Gly-Gly": 5, "Diketopiperazine": 4, "Gly": 5}, (counts, ed.points_status.text())


def test_riggi_figure_2_five_bar_panels():
    """Riggi2023 Fig. 2: five category bar charts calibrated and read automatically, one series per bar;
    the paper's values (Results text and the bars) after rounding to 2 decimals."""
    if not RIGGI.is_file():
        print(f"SKIP: needs {RIGGI}"); return
    _app()
    from parameter_extractor.digitizing.calibration import pixel_to_y
    from parameter_extractor.schemas.figures import AxisVariable, FigurePlan, PlannedPanel, PlannedSeries
    expected = {"(a) Clays": [2, 3, 3.33, 5], "(b) Sulfides": [2, 3, 3, 5], "(c) Zeolites": [2, 2, 2, 2, 2.33, 3],
                "(d) Oxides": [2, 2, 2, 2], "(e) Others": [2] * 11}
    with tempfile.TemporaryDirectory() as tmp:
        ed = _editor(RIGGI, "2", tmp)
        ed.auto_axes_box.setChecked(True)
        ed.auto_points_box.setChecked(True)
        try:
            ed.apply_plan(FigurePlan(figure_id="Fig. 2", is_data_plot=True, plot_kind="bar",
                                     duplicates_tabulated_data=False, panels=[
                PlannedPanel(name=name, x=AxisVariable(label="mineral", column="solid_material_name", categorical=True),
                             y=AxisVariable(label="avg. length", column=None, tick_labels=[0, 1, 2, 3, 4, 5, 6]),
                             series=[PlannedSeries(label=f"{name} bar {k + 1}") for k in range(len(values))])
                for name, values in expected.items()]))
        finally:
            ed.auto_axes_box.setChecked(False)
            ed.auto_points_box.setChecked(False)
        for pi, (name, values) in enumerate(expected.items()):
            panel = ed.fig.panels[pi]
            got = [pixel_to_y(panel, s.points[0].px, s.points[0].py) for s in ed.fig.series if s.panel == pi and s.points]
            assert len(got) == len(values) and all(abs(g - v) < 0.12 for g, v in zip(got, values)), \
                (name, [round(g, 2) for g in got], ed.points_status.text())


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All automatic-point tests passed.")
