"""
Offline test of the desktop window -- no API calls, no visible window.

Drives MainWindow like a user (fill in the fields, click "Extract data", wait)
with Qt's offscreen platform, replaying the saved eder1994_auto responses
through the real pipeline (same replay as test_pipeline_offline.py). The
system keychain and the user's saved preferences are never touched.

Set GUI_SCREENSHOT_DIR to also save PNGs of each tab for a visual check.

Run with: python tests/test_gui_offline.py   (needs: pip install -e ".[gui]")
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication
except ImportError:
    print("SKIP: PySide6 not installed (pip install -e \".[gui]\")")
    raise SystemExit(0)

from parameter_extractor import api_client
from parameter_extractor.gui import key_store, main_window
from parameter_extractor.gui.figure_dialog import FigureReviewDialog
from parameter_extractor.ingestion.figure_finder import find_figures
from parameter_extractor.ingestion.figure_rows import build_figure_rows
from parameter_extractor.schemas.figures import (AxisVariable, FigurePlan, PlannedPanel, PlannedSeries,
                                                 SpeciesAmount)
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from test_pipeline_offline import PDF, REPLAY_DIR, _replay_send


from PySide6.QtCore import QObject, QTimer, Signal


class SkipAllFigures(QObject):
    """Stands in for FigureReviewDialog in the end-to-end test (a human would
    choose): opens, notes whether the extraction was still running at that
    point, then skips every figure a moment later."""
    finished = Signal(int)
    seen, opened_while_extracting, statuses = [], None, []
    close_after_ms = 300

    def __init__(self, figures, columns, plan_bridge=None, parent=None):
        super().__init__()
        SkipAllFigures.seen = [f.figure_id for f in figures]
        SkipAllFigures.statuses = []
        self.window, self.digitized, self.skipped = parent, [], [f.figure_id for f in figures]
        self._visible = False
    def set_background_status(self, text): SkipAllFigures.statuses.append(text)
    def isVisible(self): return self._visible
    def show(self):
        self._visible = True
        SkipAllFigures.opened_while_extracting = self.window._running
        QTimer.singleShot(SkipAllFigures.close_after_ms, self.reject)
    def reject(self):
        if self._visible:
            self._visible = False
            self.finished.emit(0)

APP = QApplication.instance() or QApplication([])
QCoreApplication.setOrganizationName("ParameterExtractorTests")  # keep the user's prefs untouched
QCoreApplication.setApplicationName("ParameterExtractorTests")


class FakeKeyStore:
    def __init__(self, stored=""):
        self.stored, self.saved, self.deleted = stored, [], 0
    def load_key(self): return self.stored
    def save_key(self, key): self.saved.append(key); return True
    def delete_key(self): self.deleted += 1


def _window(keys: FakeKeyStore, out: Path):
    QSettings().clear()
    with patch.object(main_window, "key_store", keys):
        w = main_window.MainWindow()
    w.out_edit.setText(str(out))
    w.registry_path = out / "test_registry.json"     # never the user's real variable registry
    w.terms_edit.setPlainText("")
    return w


def _pump(seconds=0.05):
    """Let Qt deliver events. NOT QTest.qWait: it keeps holding Python's GIL,
    so the worker thread never runs (the real app's app.exec() releases it)."""
    APP.processEvents()
    time.sleep(seconds)
    APP.processEvents()


def _wait_until_idle(w, timeout_s=60):
    for _ in range(timeout_s * 20):
        if not w._running:
            return
        _pump()
    raise AssertionError("run did not finish in time")


def _screenshot(w, name):
    d = os.environ.get("GUI_SCREENSHOT_DIR")
    if d:
        w.grab().save(str(Path(d) / f"{name}.png"))


def test_full_run_fills_results():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    keys = FakeKeyStore()
    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(api_client, "_send", _replay_send), \
            patch.object(main_window, "key_store", keys), \
            patch.object(main_window, "FigureReviewDialog", SkipAllFigures):
        w = _window(keys, Path(tmp))
        w.show()
        assert not w.run_btn.isEnabled(), "Extract should be disabled until inputs are filled"
        _screenshot(w, "0_empty")

        w.pdf_edit.setText(str(PDF))
        w.key_edit.setText("replay-not-a-real-key")
        assert w.run_btn.isEnabled()
        assert w.key_edit.echoMode() == w.key_edit.EchoMode.Password

        progress = []
        w.progress.valueChanged.connect(progress.append)
        w.run_btn.click()
        assert w._running and not w.run_btn.isEnabled() and w.cancel_btn.isEnabled()
        _wait_until_idle(w)

        assert "Done: 42 rows" in w.status.text(), w.status.text()
        assert SkipAllFigures.seen == ["Fig. 1", "Fig. 2", "Fig. 3", "Fig. 4", "Fig. 5"]
        assert SkipAllFigures.opened_while_extracting, "figure review should open during extraction"
        assert any("step" in t for t in SkipAllFigures.statuses), SkipAllFigures.statuses
        assert "Fig. 3: skipped" in w.summary_text.toPlainText()
        assert w.rows_table.rowCount() == 42
        headers = [w.rows_table.horizontalHeaderItem(i).text() for i in range(w.rows_table.columnCount())]
        assert "sampled_2peptide_Gly_%yield" in headers and "full_id" in headers
        assert w.flags_tree.topLevelItemCount() >= 1
        assert headers[0] == "full_id" and headers.index("sampled_2peptide_Gly_%yield") < headers.index("paper_title")
        first_flag = w.flags_tree.topLevelItem(0).child(0)
        w.flags_tree.setCurrentItem(first_flag)
        assert "confidence" in w.flag_details.toPlainText()
        assert "Quote from the paper" in w.flag_details.toPlainText()
        assert w.tabs.isEnabled() and w.open_folder_btn.isEnabled()
        assert progress and max(progress) == w.progress.maximum()
        assert keys.saved == [] and keys.deleted == 0, "keychain touched without 'remember' ticked"
        assert w.run_btn.isEnabled() and not w.cancel_btn.isEnabled()

        for i, name in enumerate(["1_rows", "2_flags", "3_summary"]):
            w.tabs.setCurrentIndex(i); _pump(); _screenshot(w, name)
        w.close()


def test_errors_are_shown_to_the_user():
    keys = FakeKeyStore()
    shown = []
    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(main_window, "key_store", keys), \
            patch.object(main_window.QMessageBox, "critical",
                         lambda parent, title, msg: shown.append((title, msg))):
        w = _window(keys, Path(tmp))
        bad_pdf = Path(tmp) / "not-a-pdf.pdf"
        bad_pdf.write_text("this is not a PDF")
        w.pdf_edit.setText(str(bad_pdf))
        w.key_edit.setText("replay-not-a-real-key")
        w.run_btn.click()
        _wait_until_idle(w)
        assert shown and "not-a-pdf.pdf" in shown[0][1], shown
        assert "error" in w.status.text().lower()
        w.close()


def test_remember_key_uses_keychain_and_unticking_forgets_it():
    keys = FakeKeyStore(stored="sk-ant-stored")
    with tempfile.TemporaryDirectory() as tmp, patch.object(main_window, "key_store", keys):
        w = _window(keys, Path(tmp))
        assert w.key_edit.text() == "sk-ant-stored" and w.remember_key_box.isChecked()
        w._save_preferences()
        assert keys.saved == ["sk-ant-stored"]
        w.remember_key_box.setChecked(False)
        w._save_preferences()
        assert keys.deleted == 1
        w.close()


def test_review_still_open_when_extraction_finishes():
    """The other ordering: extraction done first, dataset built only once the review closes."""
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    keys = FakeKeyStore()
    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(api_client, "_send", _replay_send), \
            patch.object(main_window, "key_store", keys), \
            patch.object(main_window, "FigureReviewDialog", SkipAllFigures), \
            patch.object(SkipAllFigures, "close_after_ms", 8000):
        w = _window(keys, Path(tmp))
        w.pdf_edit.setText(str(PDF)); w.key_edit.setText("replay-not-a-real-key")
        w.run_btn.click()
        for _ in range(400):                        # until the extraction thread is done
            _pump()
            if not w._running:
                break
        assert w._review is not None and w._review.isVisible()
        assert "finish reviewing the figures" in w.status.text(), w.status.text()
        assert not w.run_btn.isEnabled() and not w.tabs.isEnabled()
        for _ in range(400):                        # until the review closes and the dataset is built
            _pump()
            if "Done:" in w.status.text():
                break
        assert "Done: 42 rows" in w.status.text(), w.status.text()
        assert w.run_btn.isEnabled()
        w.close()


def test_new_variables_shown_separately():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.pipeline import extract, finish
    from test_new_variables import _add_extras
    keys = FakeKeyStore()
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", _replay_send), \
            patch.object(main_window, "key_store", keys):
        ex = extract(PDF, RunConfig.from_settings(api_key="replay", output_dir=Path(tmp)))
        _add_extras(ex)
        result = finish(ex)
        w = _window(keys, Path(tmp))
        w.show_result(result)
        top = [w.flags_tree.topLevelItem(i).text(0) for i in range(w.flags_tree.topLevelItemCount())]
        assert top[0] == "New variables not added to the CSV (3)", top
        assert "Not added: Foo, RbCl, stirring rate" in w.summary_text.toPlainText(), w.summary_text.toPlainText()
        assert "RbCl" in w.summary_text.toPlainText()
        w.close()


def test_variable_review_window():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.gui.variable_review import VariableReviewDialog
    from parameter_extractor.ingestion.new_variables import collect_new_variables, group_new_variables
    from parameter_extractor.pipeline import extract
    from parameter_extractor.registry import VariableRegistry
    from test_new_variables import _add_extras
    shown = []
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", _replay_send), \
            patch.object(main_window.QMessageBox, "warning", lambda parent, title, msg: shown.append(msg)):
        ex = extract(PDF, RunConfig.from_settings(api_key="replay", output_dir=Path(tmp)))
        _add_extras(ex)
        groups = group_new_variables(collect_new_variables(ex.methodology, ex.chemistry))
        dlg = VariableReviewDialog(groups, ["flowthrough recirculation time"], VariableRegistry(Path(tmp) / "r.json"))
        dlg.show(); _pump()
        names = [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())]
        assert names == ["RbCl", "Foo", "stirring rate"], names
        assert [d.action for d in dlg.decisions()] == ["ignore"] * 3          # nothing added by default

        dlg.set_action(0, "new_column")                                       # proposed name pre-filled
        dlg.set_action(1, "existing_column", "not_a_column")                  # invalid -> blocked
        dlg.table.selectRow(2); dlg._show_values(2)
        dlg.values_table.item(0, 1).setText("300")                            # edit "300 rpm" -> 300
        dlg.set_action(2, "new_column", "stirring_rate_rpm")
        dlg._finish()
        assert shown and "isn't an existing column" in shown[0] and dlg.isVisible()
        dlg.set_action(1, "existing_column", "sampled_DKP_Gly_%yield")
        _pump(); _screenshot(dlg, "6_variable_review")
        dlg._finish()
        assert dlg.result() == dlg.DialogCode.Accepted
        d = {x.alias_name: (x.action, x.column) for x in dlg.decisions()}
        assert d == {"initial RbCl": ("new_column", "initial_RbCl_aq_mM"),
                     "sampled Foo %": ("existing_column", "sampled_DKP_Gly_%yield"),
                     "stirring rate": ("new_column", "stirring_rate_rpm")}
        assert groups[2].values[0].value == 300.0

        # closing the window = add nothing
        dlg2 = VariableReviewDialog(groups, [], VariableRegistry(None))
        dlg2.set_action(0, "new_column"); dlg2.reject()
        assert all(x.action == "ignore" for x in dlg2.decisions())


class InstantPlans:
    """Stands in for PlanBridge: delivers a fixed plan immediately."""
    def __init__(self, plan): self.plan, self.requests = plan, []
    def request(self, figure, on_success, on_error):
        self.requests.append(figure.figure_id); on_success(self.plan); return 1
    def cancel(self, rid): pass


def test_digitize_a_figure_by_clicking():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    plan = FigurePlan(figure_id="Fig. 5", is_data_plot=True, plot_kind="scatter",
                      duplicates_tabulated_data=False, panels=[PlannedPanel(
                          name="main",
                          x=AxisVariable(label="t/h", column="duration_hr"),
                          y=AxisVariable(label="% Gly-Gly", column="sampled_2peptide_Gly_%yield"),
                          series=[PlannedSeries(label="Na+", marker="plus", initial_temperature_C=80,
                                                initial_species=[SpeciesAmount(name="NaCl", concentration_mM=3000)]),
                                  PlannedSeries(label="K+", marker="open circle", initial_temperature_C=80,
                                                initial_species=[SpeciesAmount(name="KCl", concentration_mM=3000)])])])
    with tempfile.TemporaryDirectory() as tmp:
        figures = [f for f in find_figures(str(PDF), Path(tmp)) if f.number in (3, 5)]
        bridge = InstantPlans(plan)
        dlg = FigureReviewDialog(figures, ["duration_hr", "sampled_2peptide_Gly_%yield"], plan_bridge=bridge)
        dlg.show(); _pump()
        assert "Fig. 3" in dlg.header.text()
        dlg.skip_btn.click()                                  # skip Fig. 3
        assert "Fig. 5" in dlg.header.text()
        dlg.digitize_btn.click()
        ed = dlg.editor
        assert bridge.requests == ["Fig. 5"]
        assert [s.label for s in ed.fig.series] == ["Na+ [plus]", "K+ [open circle]"]   # suggestions applied
        assert ed.panel.x.column == "duration_hr"

        # calibrate like a user: two clicks per axis + typed values
        s = ed.fig.render_scale
        for axis, pts, vals in (("x", [(60, 200), (240, 200)], ("0", "40")),
                                ("y", [(60, 200), (60, 40)], ("0", "0.8"))):
            ed.set_mode(axis)
            for (px, py), v, k in zip(pts, vals, (1, 2)):
                ed.place_calibration(axis, px * s, py * s)
                edit = ed.cal_edits[(axis, k)][1]
                edit.setText(v); ed._on_cal_value(axis, k)
        ed.set_mode("points")
        ed.series_list.setCurrentRow(1)                       # K+
        ed.add_point(150 * s, 120 * s)                        # -> t = 20 h, yield = 0.4 %
        ed.add_point(195 * s, 100 * s)
        ed.undo()                                             # removes the second point
        assert len(ed.fig.series[1].points) == 1
        assert ed.points_table.item(0, 0).text() == "20" and ed.points_table.item(0, 1).text() == "0.4"
        _pump(); _screenshot(dlg, "4_digitizer")

        dlg._save(confirm=False)
        assert dlg.result() == dlg.DialogCode.Accepted
        assert dlg.skipped == ["Fig. 3"] and [d.figure_id for d in dlg.digitized] == ["Fig. 5"]

        meta = PaperMetadata.model_validate_json((REPLAY_DIR / "metadata.output.json").read_text())
        meth = Methodology.model_validate_json((REPLAY_DIR / "methodology.output.json").read_text())
        rows, problems, new_vars = build_figure_rows(dlg.digitized, meta, meth, "001", 14, 43)
        assert problems == [] and len(rows) == 1
        r = rows[0]
        assert (round(r.duration_hr, 6), round(r.sampled_2peptide_Gly_pct_yield, 6)) == (20.0, 0.4)
        assert r.species_mM == {"initial_KCl_aq_mM": 3000} and "K+" in r.source_notes


def test_trackpad_zoom_and_overlapping_points():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QNativeGestureEvent, QPointingDevice, QWheelEvent
    from PySide6.QtTest import QTest
    from parameter_extractor.gui.digitizer import DigitizerWidget
    from parameter_extractor.schemas.figures import DigitizedFigure

    with tempfile.TemporaryDirectory() as tmp:
        f = next(f for f in find_figures(str(PDF), Path(tmp)) if f.number == 5)
        ed = DigitizerWidget(DigitizedFigure(figure_id=f.figure_id, number=5, page=5, caption="",
                                             render_scale=f.render_scale, page_image=f.page_image,
                                             figure_bbox=f.figure_bbox), ["duration_hr"])
        ed.resize(1200, 800); ed.show(); _pump()
        view, vp = ed.canvas, ed.canvas.viewport()
        centre = QPointF(vp.width() / 2, vp.height() / 2)

        z0 = view.transform().m11()
        pinch = QNativeGestureEvent(Qt.NativeGestureType.ZoomNativeGesture, QPointingDevice.primaryPointingDevice(),
                                    2, centre, centre, vp.mapToGlobal(centre), 0.25, QPointF(), 1)
        APP.sendEvent(vp, pinch)
        assert abs(view.transform().m11() / z0 - 1.25) < 1e-6, "pinch should zoom"

        z1, h0 = view.transform().m11(), view.horizontalScrollBar().value()
        two_finger = QWheelEvent(centre, vp.mapToGlobal(centre), QPoint(-40, 0), QPoint(-120, 0),
                                 Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                 Qt.ScrollPhase.ScrollUpdate, False)
        APP.sendEvent(vp, two_finger)
        assert view.transform().m11() == z1, "two-finger scroll must not zoom"
        assert view.horizontalScrollBar().value() != h0, "two-finger scroll should pan"
        wheel = QWheelEvent(centre, vp.mapToGlobal(centre), QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        APP.sendEvent(vp, wheel)
        assert view.transform().m11() > z1, "mouse wheel should zoom"

        # two series; a click right on top of series A's point, while B is selected, adds to B
        ed.set_mode("points")
        a = ed.add_series("A")
        target = view.mapToScene(centre.toPoint())
        ed.add_point(target.x(), target.y())
        ed.add_series("B"); ed.redraw(); _pump()
        QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre.toPoint())
        assert len(a.points) == 1 and len(ed.fig.series[1].points) == 1, "click on another series' point adds"

        # on the selected series' own point: plain click grabs it, Shift+click adds another
        QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre.toPoint())
        assert len(ed.fig.series[1].points) == 1, "plain click on own point should not add"
        QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, centre.toPoint())
        assert len(ed.fig.series[1].points) == 2, "Shift+click should add on top"

        # isolation hides other series; delete only touches the selected series
        ed.isolate_box.setChecked(True)
        shown = {i.series_idx for i in view.scene().items() if type(i).__name__ == "PointItem"}
        assert shown == {1}, shown
        ed.set_mode("delete")
        QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre.toPoint())
        assert len(a.points) == 1 and len(ed.fig.series[1].points) == 1
        _screenshot(ed, "5_isolated")
        ed.close()


if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
                print(f"PASS: {name}")
        print("All offline GUI tests passed.")
    finally:
        QSettings().clear()
