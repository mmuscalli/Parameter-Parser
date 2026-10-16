"""
Offline tests for the optional digitizer automation on alargov2002 Fig. 3 (a
scanned plot: no text layer, slightly rotated, two panels with left and
right y-axes, x axis without tick marks, a legend box): automatic axis
calibration and finding markers like a clicked example. No API calls.

Run with: python tests/test_auto_digitize.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from PIL import Image

from parameter_extractor.digitizing.auto_axes import (AutoAxisError, calibrate_axis, find_boxes_inside,
                                                      find_frames)
from parameter_extractor.digitizing.auto_points import centre_marker, find_similar_points
from parameter_extractor.ingestion.figure_finder import find_figures

PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Alargov2002" / "alargov2002.pdf"
TICKS = {0: {"bottom": [200, 250, 300, 350, 400, 450], "left": [0, 0.5, 1.0, 1.5, 2.0],
             "right": [0, 10, 20, 30, 40, 50, 60, 70]},
         1: {"bottom": [200, 250, 300, 350, 400, 450], "left": [0, 1, 2, 3, 4, 5, 6, 7],
             "right": [0, 50, 100, 150, 200, 250]}}


def _figure3(tmp):
    fig = next(f for f in find_figures(str(PDF), Path(tmp)) if f.number == 3)
    gray = np.asarray(Image.open(fig.page_image).convert("L"))
    s = fig.render_scale
    region = tuple(int(v * s) for v in fig.figure_bbox)
    return fig, gray, region


def test_frames_and_axes_are_found():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp:
        fig, gray, region = _figure3(tmp)
        frames = find_frames(gray, region)
        assert len(frames) == 2 and all(f.has_right_axis for f in frames)
        for i, frame in enumerate(frames):
            for side, labels in TICKS[i].items():
                (x1, y1, v1), (x2, y2, v2), is_log = calibrate_axis(gray, frame, side, labels)
                assert (v1, v2, is_log) == (labels[0], labels[-1], False)
                span = (x2 - x1) if side == "bottom" else (y1 - y2)
                assert span > 200                         # low end at left / bottom
        # panel (a): x 200..450 runs from the frame's left edge to its right edge
        (x1, _, _), (x2, _, _), _ = calibrate_axis(gray, frames[0], "bottom", TICKS[0]["bottom"])
        assert abs(x1 - frames[0].left) < 4 and abs(x2 - frames[0].right) < 4
        try:
            calibrate_axis(gray, frames[0], "left", [0, 1, 2])     # wrong count: refused, not guessed
        except AutoAxisError as e:
            assert "expected 3" in str(e)
        else:
            raise AssertionError("a mismatched set of numbers must not calibrate")


def test_markers_like_an_example_are_found():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp:
        fig, gray, region = _figure3(tmp)
        frame = find_frames(gray, region)[0]
        legend = find_boxes_inside(gray, frame)
        assert len(legend) == 1
        (xa, _, _), (xb, _, _), _ = calibrate_axis(gray, frame, "bottom", TICKS[0]["bottom"])
        (_, ya, _), (_, yb, _), _ = calibrate_axis(gray, frame, "left", TICKS[0]["left"])
        X = lambda v: xa + (v - 200) / 250 * (xb - xa)
        Y = lambda v: ya + v / 2.0 * (yb - ya)
        example = centre_marker(gray, X(250) + 4, Y(0.0) - 3)          # a click a few pixels off
        assert abs(example[0] - X(250)) < 3 and abs(example[1] - Y(0.0)) < 3
        area = (frame.left, frame.top, frame.right, frame.bottom)
        found = find_similar_points(gray, example, area, exclude=legend)
        temps = sorted(round(200 + (x - xa) / (xb - xa) * 250) for x, _, _ in found)
        assert len(temps) == 5 and [t // 5 * 5 for t in temps] == [250, 300, 345, 370, 395], temps
        again = find_similar_points(gray, example, area, existing=[(x, y) for x, y, _ in found], exclude=legend)
        assert again == []                                              # nothing twice


def test_digitizer_calibrates_on_suggestions():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("SKIP: PySide6 not installed"); return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.digitizer import DigitizerWidget
    from parameter_extractor.schemas.figures import (AxisVariable, DigitizedFigure, FigurePlan, PlannedPanel,
                                                     PlannedSeries)
    with tempfile.TemporaryDirectory() as tmp:
        f, _, _ = _figure3(tmp)
        fig = DigitizedFigure(figure_id=f.figure_id, number=f.number, page=f.page, caption=f.caption,
                              render_scale=f.render_scale, page_image=f.page_image, figure_bbox=f.figure_bbox)
        panels = []
        for name, idx, side in (("(a) left y-axis", 0, "left"), ("(a) right y-axis", 0, "right"),
                                ("(b) left y-axis", 1, "left"), ("(b) right y-axis", 1, "right")):
            panels.append(PlannedPanel(
                name=name, x=AxisVariable(label="T", column="sampled_temperature_C",
                                          tick_labels=TICKS[idx]["bottom"]),
                y=AxisVariable(label="c", column="sampled_Gly_mM", tick_labels=TICKS[idx][side]),
                series=[PlannedSeries(label=f"s{len(panels)}")]))
        plan = FigurePlan(figure_id="Fig. 3", is_data_plot=True, plot_kind="scatter", panels=panels,
                          duplicates_tabulated_data=False)
        w = DigitizerWidget(fig, ["sampled_temperature_C", "sampled_Gly_mM"])
        w.auto_axes_box.setChecked(True)
        w.apply_plan(plan)
        assert all(p.x_cal.complete() and p.y_cal.complete() for p in fig.panels), w.auto_status.text()
        assert [p.y_cal.p2.value for p in fig.panels] == [2.0, 70, 7, 250]
        w.close()


def test_panel_names_are_read_by_whole_words():
    """The planner named a panel '(a) left y-axis (Gly-Gly and diketopiperazine, 22.2 MPa)':
    'diketopiperazine' contains 'top', which used to make it a top x-axis."""
    try:
        from parameter_extractor.gui.digitizer import DigitizerWidget
    except ImportError:
        print("SKIP: PySide6 not installed"); return
    sides = DigitizerWidget._panel_sides
    assert sides("(a) left y-axis (Gly-Gly and diketopiperazine, 22.2 MPa)")[:2] == ("bottom", "left")
    assert sides("(a) right y-axis (Gly, 22.2 MPa)")[:2] == ("bottom", "right")
    assert sides("top x-axis")[:2] == ("top", "left")
    assert sides("(b) left y-axis")[2] == sides("(b) right y-axis")[2]


def test_composition_passages_reach_the_methods():
    """alargov2002's glycine concentrations are only in Methods, which never mentions Fig. 3."""
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    from parameter_extractor.ingestion.pdf_parser import parse_pdf
    from parameter_extractor.stages.figure_planner import composition_passages, figure_passages
    pages = parse_pdf(str(PDF)).page_texts
    figure = figure_passages(pages, 3)
    assert "0.065 M" not in figure
    extra = composition_passages(pages, exclude=figure)
    assert "0.065 M" in extra and "0.22 M" in extra and "former case" in extra   # with its context
    assert "Origins Life Evol" not in extra                               # not the reference list


def test_captions_keep_their_spaces_and_full_width():
    """alargov2002 sets its captions tightly: words ran together ('Figure3.Plotsofthe...'),
    which also hid Figs. 1, 2, 4-6 and made the figure areas half a page wide."""
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp:
        figs = find_figures(str(PDF), Path(tmp))
        assert [f.number for f in figs] == [1, 2, 3, 4, 5, 6, 7]
        f3 = figs[2]
        assert f3.caption.startswith("Figure 3. Plots of the concentrations of diglycine, diketopiperazine")
        assert all(f.figure_bbox[2] - f.figure_bbox[0] > 400 for f in figs)      # single-column page


def test_concentrations_found_fill_empty_species():
    from parameter_extractor.gui.digitizer import fill_concentrations
    from parameter_extractor.schemas.figures import ConcentrationFound, DigitizedSeries, SpeciesAmount
    series = [DigitizedSeries(label="Gly-Gly (22.2 MPa) [filled circle]",
                              initial_species=[SpeciesAmount(name="Gly", concentration_mM=None)]),
              DigitizedSeries(label="Gly-Gly (40.0 MPa) [filled circle]",
                              initial_species=[SpeciesAmount(name="Gly", concentration_mM=500.0)]),
              DigitizedSeries(label="Gly (40.0 MPa)")]
    fill_concentrations(series, [
        ConcentrationFound(species="Gly", value="0.065 M", series=["Gly-Gly (22.2 MPa)"], basis="indirect",
                           source="Methods: control outlet, hand-operated"),
        ConcentrationFound(species="Gly", value="0.22 M", series=["Gly-Gly (40.0 MPa)", "Gly (40.0 MPa)"],
                           basis="indirect", source="Methods: control outlet, HPLC pump")])
    a, b, c = (s.initial_species[0] for s in series)
    assert (a.concentration_mM, a.basis) == (65.0, "indirect") and "hand-operated" in a.source
    assert b.concentration_mM == 500.0                       # never overwrites a value already there
    assert (c.name, c.concentration_mM) == ("Gly", 220.0)    # added where the series lacked the species


def test_errors_are_recorded():
    import tempfile
    from unittest.mock import patch
    try:
        from parameter_extractor.gui import error_log
    except ImportError:
        print("SKIP: PySide6 not installed"); return
    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(error_log, "error_log_path", lambda: Path(tmp) / "errors.log"):
        run = Path(tmp) / "alargov2002_20261016-022152"
        run.mkdir()
        assert error_log.latest_run_dir(Path(tmp), Path("x/alargov2002.pdf"), 0) == run
        error_log.record("Traceback: boom", run)
        assert "boom" in (Path(tmp) / "errors.log").read_text() and "boom" in (run / "error.txt").read_text()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All auto-digitize tests passed.")
