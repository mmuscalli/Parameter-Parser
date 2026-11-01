"""
Offline tests for the digitizer's suggested new columns, category (bar chart) axes and rounding to a
chosen precision (Mickey, 2026-10-31, from Riggi2023 Fig. 2). No API calls; the GUI part runs offscreen.

Run with: python tests/test_digitizer_columns_rounding.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs
from parameter_extractor.digitizing.calibration import pixel_to_data, pixel_to_y, snap
from parameter_extractor.schemas.figures import (AxisCalibration, AxisVariable, CalibrationPoint, DigitizedFigure,
                                                 DigitizedPanel, DigitizedPoint, DigitizedSeries, FigurePlan,
                                                 PlannedPanel, PlannedSeries, SeriesCondition)


def _cal(a, b):
    return AxisCalibration(p1=CalibrationPoint(px=a[0], py=a[1], value=a[2]),
                           p2=CalibrationPoint(px=b[0], py=b[1], value=b[2]))


def _panel(**axes):
    return DigitizedPanel(x_cal=_cal((0, 100, 0), (100, 100, 10)), y_cal=_cal((0, 100, 0), (0, 0, 10)), **axes)


def test_points_snap_to_each_axis_precision():
    panel = _panel(x=AxisVariable(label="n", column="duration_hr", decimals=0),
                   y=AxisVariable(label="y", column="sampled_Gly_mM", decimals=1))
    px, py = snap(panel, 10.18, 100 - 33.37)                       # x = 1.018, y = 3.337
    x, y = pixel_to_data(panel, px, py)
    assert (round(x, 9), round(y, 9)) == (1.0, 3.3)
    panel.y.decimals = None                                         # x only: y is left where it was
    x, y = pixel_to_data(panel, *snap(panel, 10.18, 100 - 33.37))
    assert round(x, 9) == 1.0 and abs(y - 3.337) < 1e-9
    # a slightly rotated scan: both projections are solved together
    rot = DigitizedPanel(x_cal=_cal((0, 100, 0), (100, 98, 10)), y_cal=_cal((0, 100, 0), (2, 0, 10)),
                         x=AxisVariable(label="n", column=None, decimals=0), y=AxisVariable(label="y", column=None, decimals=0))
    x, y = pixel_to_data(rot, *snap(rot, 47.3, 61.2))
    assert (round(x, 9), round(y, 9)) == (round(x), round(y))
    # a category axis (no x calibration): only y is rounded
    bars = DigitizedPanel(y_cal=_cal((0, 100, 0), (0, 0, 6)),
                          x=AxisVariable(label="mineral", column="solid_material_name", categorical=True),
                          y=AxisVariable(label="avg. length", column=None, decimals=0))
    px, py = snap(bars, 50, 100 - 100 * 2.94 / 6)
    assert px == 50 and round(pixel_to_y(bars, px, py), 9) == 3.0


def test_bars_with_categories_and_a_suggested_column():
    """Riggi2023 Fig. 2: the x axis holds categories (the mineral goes in solid_material_name -- from the
    series' condition, or its name), the y axis a suggested new column; values are rounded."""
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.figure_rows import build_figure_rows
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.methodology import empty_methodology
    from parameter_extractor.schemas.paper_metadata import PaperMetadata
    panel = DigitizedPanel(
        y_cal=_cal((0, 100, 0), (0, 0, 6)),
        x=AxisVariable(label="mineral", column="solid_material_name", categorical=True),
        y=AxisVariable(label="avg. max. linear oligomer length", column=None, average=True, decimals=2,
                       new_column="max_linear_oligomer_length_avg_nt"))
    fig = DigitizedFigure(figure_id="Fig. 2", number=2, page=7, caption="c", render_scale=1.0, page_image="",
                          panels=[panel], series=[
        DigitizedSeries(label="kaolinite [blue bar]", points=[DigitizedPoint(px=50, py=100 - 100 * 3.3333 / 6)]),
        DigitizedSeries(label="pyrite [blue bar]", points=[DigitizedPoint(px=60, py=50)],
                        conditions=[SeriesCondition(column="solid_material_name", value="pyrite (FeS2)", source="")])])
    meta = PaperMetadata(paper_id="p", paper_title="t", authors=["A"], year_published=2023, journal_published="j")
    rows, problems, new_vars = build_figure_rows([fig], meta, empty_methodology("p"), "001", 1, 1,
                                                 registry=VariableRegistry(None))
    assert not problems and [r.set_type for r in rows] == ["Average", "Average"]
    assert [r.extra.get("solid_material_name") for r in rows] == ["kaolinite", "pyrite (FeS2)"]
    assert {(v.proposed_column, v.value) for v in new_vars} == {("max_linear_oligomer_length_avg_nt", 3.33),
                                                              ("max_linear_oligomer_length_avg_nt", 3.0)}
    assert not any(v.proposed_column.startswith("mineral") for v in new_vars)   # no number for a category
    # the user chose '(none -- not stored)' for y: nothing is made up for it
    panel.y = panel.y.model_copy(update={"store": False, "new_column": ""})
    rows, problems, new_vars = build_figure_rows([fig], meta, empty_methodology("p"), "001", 1, 1,
                                                 registry=VariableRegistry(None))
    assert rows and not new_vars


def test_typed_average_columns_get_no_second_avg():
    from parameter_extractor.ingestion.flatten_to_template import with_average
    assert with_average("avg_max_linear_oligomer_length_n") == "avg_max_linear_oligomer_length_n"
    assert with_average("max_length_nt") == "max_length_avg_nt"


def test_digitizer_loads_suggested_columns_and_rounds_points():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("SKIP: PySide6 not installed"); return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from PIL import Image
    from parameter_extractor.gui.digitizer import DigitizerWidget, read_values
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.png"
        Image.new("RGB", (200, 200), "white").save(page)
        fig = DigitizedFigure(figure_id="Fig. 2", number=2, page=7, caption="c", render_scale=1.0,
                              page_image=str(page))
        plan = FigurePlan(figure_id="Fig. 2", is_data_plot=True, plot_kind="bar", duplicates_tabulated_data=False,
                          panels=[PlannedPanel(
                              name="(a) Clays",
                              x=AxisVariable(label="mineral", column="solid_material_name", categorical=True),
                              y=AxisVariable(label="avg. max. linear oligomer length", column=None, average=True,
                                             new_column="max_linear_oligomer_length_nt"),
                              series=[PlannedSeries(label="kaolinite")])])
        w = DigitizerWidget(fig, ["solid_material_name", "duration_hr"])
        w.apply_plan(plan)
        y_combo, _ = w.var_widgets["y"]
        assert y_combo.currentText() == "max_linear_oligomer_length_avg_nt"            # loaded, with its average
        assert "New variable" in w.var_hints["y"].text()
        assert w.cal_edits[("x", "categories")].isChecked() and "Categories" in w.var_hints["x"].text()
        fig.panels[0].y_cal = _cal((0, 100, 0), (0, 0, 6))
        w.cal_edits[("y", "round")].setCurrentIndex(1)                                   # whole numbers
        w.add_point(50, 100 - 100 * 2.9 / 6)
        x, y = read_values(fig.panels[0], fig.series[0].points[0].px, fig.series[0].points[0].py)
        assert x is None and round(y, 9) == 3.0
        y_combo.setCurrentText("(none -- not stored)")
        assert fig.panels[0].y.store is False and fig.panels[0].y.column is None
        w.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All digitizer column / rounding tests passed.")
