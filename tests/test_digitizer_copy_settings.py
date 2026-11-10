"""'Use in every coordinate system' in the digitizer (2026-11-08): one coordinate system's rounding / columns / log
scales copied to all the others, points re-snapped, one undo step. No API calls."""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_copy_rounding_and_columns_to_every_panel():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.digitizer import DigitizerWidget, ROUND_CHOICES
    from parameter_extractor.schemas.figures import (AxisCalibration, CalibrationPoint, DigitizedFigure,
                                                     DigitizedPanel, DigitizedPoint, DigitizedSeries)

    def panel(name):
        cal = AxisCalibration(p1=CalibrationPoint(px=0, py=100, value=0), p2=CalibrationPoint(px=100, py=100, value=10))
        ycal = AxisCalibration(p1=CalibrationPoint(px=0, py=100, value=0), p2=CalibrationPoint(px=0, py=0, value=10))
        return DigitizedPanel(name=name, x_cal=cal, y_cal=ycal)
    fig = DigitizedFigure(figure_id="f", number=1, page=1, caption="", render_scale=1.0, page_image="",
                          panels=[panel("a"), panel("b"), panel("c")],
                          series=[DigitizedSeries(label="s", panel=2, points=[DigitizedPoint(px=50, py=34.0)])])
    w = DigitizerWidget(fig, ["max_linear_oligomer_length_nt"])
    w.cal_edits[("y", "round")].setCurrentIndex(1)                     # whole numbers on panel a
    w.var_widgets["y"][0].setCurrentText("max_linear_oligomer_length_nt")
    assert fig.panels[2].y.decimals is None
    assert w.apply_to_all_panels("rounding") == 2
    assert all(p.y.decimals == 0 for p in fig.panels) and fig.panels[1].y.column is None
    assert abs(fig.series[0].points[0].py - 30.0) < 1e-6                # 6.6 snapped to 7 (pixel 30)
    w.apply_to_all_panels("columns")
    assert all(p.y.column == "max_linear_oligomer_length_nt" for p in fig.panels)
    w.undo()                                                             # columns back
    assert fig.panels[1].y.column is None and fig.panels[1].y.decimals == 0
    w.undo()                                                             # rounding and the snapped point back
    assert fig.panels[1].y.decimals is None and abs(fig.series[0].points[0].py - 34.0) < 1e-6
    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == ["Axes", "Series", "Points"]
    assert not w.suggestion_label.isVisibleTo(w)                        # hidden until there is a note
    w.suggestion_label.setText("Suggestions applied")
    assert w.suggestion_label.isVisibleTo(w)
    assert ROUND_CHOICES[1][0] == "whole numbers"
    # a point with only an upper error bar (a bar's whisker) -- selecting its series broke the points table
    fig.series[0].points[0] = fig.series[0].points[0].model_copy(update={"err_hi_py": 20.0})
    w.series_list.setCurrentRow(-1)
    w.series_list.setCurrentRow(0)
    assert w.points_table.item(0, 1).text() == "6.6 (+1.4)"


if __name__ == "__main__":
    test_copy_rounding_and_columns_to_every_panel()
    print("ok")
