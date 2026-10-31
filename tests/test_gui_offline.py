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
from parameter_extractor.gui import error_log

# failures provoked by these tests must not land in the user's real errors.log
_ERROR_LOG_DIR = tempfile.mkdtemp()
error_log.error_log_path = lambda: Path(_ERROR_LOG_DIR) / "errors.log"
from parameter_extractor.gui.figure_dialog import FigureReviewDialog
from parameter_extractor.ingestion.figure_finder import find_figures
from parameter_extractor.ingestion.figure_rows import build_figure_rows
from parameter_extractor.schemas.figures import (AxisVariable, FigurePlan, PlannedPanel, PlannedSeries,
                                                 SpeciesAmount)
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from test_pipeline_offline import PDF, REPLAY_DIR, _replay_send


from PySide6.QtCore import QObject, Qt, QTimer, Signal


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
    """The API key (default account) plus other secrets by account (the ADS token)."""
    ACCOUNT, ADS_ACCOUNT = "anthropic-api-key", "ads-api-token"
    def __init__(self, stored="", ads=""):
        self.stored, self.saved, self.deleted = stored, [], 0
        self.other = {self.ADS_ACCOUNT: ads} if ads else {}
    def load_key(self, account=ACCOUNT):
        return self.stored if account == self.ACCOUNT else self.other.get(account, "")
    def save_key(self, key, account=ACCOUNT):
        if account == self.ACCOUNT:
            self.saved.append(key)
        else:
            self.other[account] = key
        return True
    def delete_key(self, account=ACCOUNT):
        if account == self.ACCOUNT:
            self.deleted += 1
        else:
            self.other.pop(account, None)


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
        tip = w.rows_table.item(0, headers.index("sampled_2peptide_Gly_%yield")).toolTip()
        assert tip.startswith("From: chemistry (high confidence)") and "Table 1" in tip, tip
        groups = [w.flags_tree.topLevelItem(i) for i in range(w.flags_tree.topLevelItemCount())]
        assert not any(g.isExpanded() for g in groups)                   # categories start collapsed
        whole_paper = next(g for g in groups if g.text(0).startswith("Whole paper"))
        w.flags_tree.setCurrentItem(whole_paper.child(0))
        assert "confidence" in w.flag_details.toPlainText()
        details = w.flag_details.toPlainText()
        assert "Quote from the paper" in details or "not found word for word" in details, details
        assert w.tabs.isEnabled() and w.open_folder_btn.isEnabled()
        assert progress and max(progress) == w.progress.maximum()
        assert keys.saved == [] and keys.deleted == 0, "keychain touched without 'remember' ticked"
        assert w.run_btn.isEnabled() and not w.cancel_btn.isEnabled()

        figures_tab = w.tabs.indexOf(w.figures_view)
        assert w.tabs.tabText(figures_tab) == "Figures (5)"
        assert "Fig. 3" in w.figures_view.toPlainText() and "skipped" in w.figures_view.toPlainText()
        assert "image not kept" in w.figures_view.toPlainText()          # skipped figures' images removed
        assert w.tabs.tabText(w.tabs.indexOf(w.tables_view)) == "Tables (3)"          # eder1994's Tables 1-3
        assert "Table 2" in w.tables_view.toPlainText()
        assert w.tabs.tabText(w.tabs.indexOf(w.equations_view)) == "Equations (1)"   # eder1994's rate law
        for i, name in enumerate(["1_rows", "2_flags", "3_figures", "4_tables", "5_equations", "6_summary"]):
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
        names = [dlg.table.item(dlg._table_row[i], 0).text() for i in range(len(groups))]
        assert names == ["RbCl", "Foo", "stirring rate"], names
        headers = dlg.category_headers()                                      # grouped by category
        assert [h.split("  (")[0] for h in headers] == ["Starting Species", "Products", "Reaction Conditions"], headers
        assert "format: one number with its unit" in headers[2]
        assert groups[2].proposed_column == "stirring_rate_rpm"               # unit suffix from the format
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


def test_expanding_text_fields():
    from PySide6.QtCore import QTimer
    from parameter_extractor.gui.widgets import ExpandingLineEdit
    text = "Campbell, T.D. et al., Prebiotic condensation through wet-dry cycling regulated by " \
           "deliquescence, Nat. Commun. 10:4508, 2019 (ref. 15; Supplementary table 8)"
    w = ExpandingLineEdit("Data reproduced from", hint="a hint")
    w.setText(text)
    assert w.toolTip().startswith("<qt>") and "Supplementary table 8" in w.toolTip()
    edits = []
    w.editingFinished.connect(lambda: edits.append(w.text()))
    QTimer.singleShot(0, lambda: (w._editor.setPlainText("New ref\nline two"), w._editor.parent().accept()))
    w.open_editor()
    assert w.text() == "New ref line two" and edits == ["New ref line two"]


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


def test_choose_every_figure_first_then_digitize():
    """Skip/Digitize is decided for every figure before any digitizer opens; the
    chosen ones then open in order, their suggestions requested when chosen."""
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    plan = FigurePlan(figure_id="x", is_data_plot=True, plot_kind="scatter", duplicates_tabulated_data=False,
                      panels=[])
    with tempfile.TemporaryDirectory() as tmp:
        figures = [f for f in find_figures(str(PDF), Path(tmp)) if f.number in (1, 3, 5)]
        bridge = InstantPlans(plan)
        dlg = FigureReviewDialog(figures, ["duration_hr"], plan_bridge=bridge)
        dlg.show(); _pump()
        dlg.digitize_btn.click()                              # Fig. 1: digitize
        assert dlg.editor is None and "Fig. 3" in dlg.header.text() and dlg.stack.currentIndex() == 0
        assert "so far: Fig. 1" in dlg.choose_hint.text()
        dlg.skip_btn.click()                                  # Fig. 3: skip
        dlg.digitize_btn.click()                              # Fig. 5: digitize -> now the digitizer opens
        assert bridge.requests == ["Fig. 1", "Fig. 5"]       # prefetched when chosen
        assert dlg.stack.currentIndex() == 1 and dlg.editor.fig.figure_id == "Fig. 1"
        assert "1 of 2 chosen" in dlg.header.text()
        dlg.cancel_digitizing_btn.click()                     # changed my mind about Fig. 1
        assert dlg.editor.fig.figure_id == "Fig. 5" and "2 of 2 chosen" in dlg.header.text()
        dlg.reject()                                          # closing: Fig. 5 not done -> skipped
        assert sorted(dlg.skipped) == ["Fig. 1", "Fig. 3", "Fig. 5"] and dlg.digitized == []


def test_equations_tab_shows_found_equations():
    pdf = PDF.parents[1] / "Truman2024" / "truman2024.pdf"
    if not pdf.is_file():
        print(f"SKIP: needs {pdf}"); return
    from types import SimpleNamespace
    from parameter_extractor.ingestion.equation_finder import find_equations
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        eqs = find_equations(str(pdf), Path(tmp))
        assert [e.label for e in eqs] == ["1", "2", "3"]
        eqs[2].latex = "K_{eq} = k_{cond} / k_{hyd}"
        w = main_window.MainWindow()
        w._fill_equations(SimpleNamespace(equations=eqs))
        text = w.equations_view.toPlainText()
        assert w.tabs.tabText(w.tabs.indexOf(w.equations_view)) == "Equations (3)"
        assert "Equation (1)" in text and "page 2" in text and "K_{eq} = k_{cond} / k_{hyd}" in text
        w.close()


def test_conditions_table_and_additional_options():
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.digitizer import DigitizerWidget
    from parameter_extractor.schemas.figures import DigitizedFigure, DigitizedSeries, SeriesCondition
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "p.png"
        from PIL import Image
        Image.new("RGB", (400, 300), "white").save(img)
        fig = DigitizedFigure(figure_id="Fig. 1", number=1, page=1, caption="c", render_scale=3.0,
                              page_image=str(img), series=[DigitizedSeries(
                                  label="s", initial_temperature_C=80.0,
                                  conditions=[SeriesCondition(column="initial_pressure_bar", value="22.2 MPa")])])
        w = DigitizerWidget(fig, ["initial_pressure_bar"])
        w._on_series_selected(0)
        t = w.conditions_table
        assert [t.item(r, 0).text() for r in range(t.rowCount())] == ["Temperature (°C)", "pH", "initial_pressure_bar"]
        assert t.item(0, 1).text() == "80"
        t.item(0, 1).setText("353.15 K")                       # units understood
        assert abs(fig.series[0].initial_temperature_C - 80.0) < 1e-6
        t.item(1, 1).setText("2.6")
        assert fig.series[0].initial_pH == 2.6
        t.setCurrentCell(0, 0); w._remove_condition_row()      # temperature/pH rows can't be removed
        assert len(fig.series[0].conditions) == 1
        t.setCurrentCell(2, 0); w._remove_condition_row()
        assert fig.series[0].conditions == []
        assert not w.more_btn.isChecked() and w.more_options.isHidden()       # closed by default
        w.more_btn.click()
        assert not w.more_options.isHidden()
        assert not w.auto_axes_box.isChecked() or main_window.QSettings().contains("digitizer/auto_axes")
        w.close()


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


class NoClickReview(main_window.VariableReviewDialog):
    """The new-variable review, closed at once with its defaults (nothing added)."""
    def exec(self): return 0


def test_archive_adopted_rows():
    """Exoplanet runs: the rows the Exoplanet Archive took for the paper (not a planet's other solutions)."""
    import json as _json
    report = [{"pl_name": "HD 14067 b", "solution": "RV fit", "status": "compared", "matches": ["a"], "differs": [{"column": "pl_orbper", "extracted": 2725.8, "archive": 2744.0}],
               "archive_solution": "joint fit", "reference": "Teng et al. 2023", "default_flag": "1"},
              {"pl_name": "HD 14067 b", "solution": "joint fit", "status": "compared", "matches": ["a", "b"],
               "differs": [{"column": "pl_orbeccen", "extracted": 0.701, "archive": 0.65}],
               "reference": "Teng et al. 2023", "default_flag": "1"},
              {"pl_name": "11 Com b", "status": "compared", "matches": ["a"], "differs": [], "default_flag": "0",
               "reference": "Teng et al. 2023"},
              {"pl_name": "HD 5608 B", "status": "planet not in the archive"}]
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "archive_validation.json").write_text(_json.dumps(report))
        adopted, differing = main_window.MainWindow._archive_marks(tmp, "object model instance")
        assert set(adopted) == {("HD 14067 b", "joint fit"), ("11 Com b", "")}
        assert "the object model instance the archive took" in adopted[("HD 14067 b", "joint fit")]
        assert "2 of 3 values match" in adopted[("HD 14067 b", "joint fit")]
        assert "default parameter set for this planet is from another paper" in adopted[("11 Com b", "")]
        # only the adopted row's differing values are marked (the RV fit's are expected to differ)
        assert list(differing) == [("HD 14067 b", "joint fit")]
        assert "extracted 0.701, archive 0.65" in differing[("HD 14067 b", "joint fit")]["pl_orbeccen"]
        assert main_window.MainWindow._archive_marks(Path(tmp) / "none") == ({}, {})


def test_stage_toggles():
    """Research area -> its switchable stages; unticked stages are skipped (checked with a
    cycling paper, truman2024, whose wet-dry stage would otherwise run); choices are kept
    per area; area and stages are locked during a run. No API calls."""
    from test_pipeline_offline import make_replay
    root = Path(__file__).resolve().parents[1]
    truman = root.parent / "Paper Files" / "Paper Lists" / "Initial Easy Papers" / "Truman2024" / "truman2024.pdf"
    keys = FakeKeyStore()
    with tempfile.TemporaryDirectory() as tmp, patch.object(main_window, "key_store", keys):
        w = _window(keys, Path(tmp))
        w.pack_combo.setCurrentIndex(w.pack_combo.findData("exoplanets"))
        assert list(w.stage_boxes) == ["planet_parameters", "stellar_parameters", "system_and_discovery",
                                       "fit_models"]
        assert all(b.isChecked() for b in w.stage_boxes.values())
        assert "EXOFAST" in w.stage_boxes["fit_models"].toolTip()
        w.stage_boxes["fit_models"].setChecked(False)
        assert w.optional_stage_choices()["fit_models"] == "off"
        w.pack_combo.setCurrentIndex(w.pack_combo.findData("prebiotic_chemistry"))
        assert list(w.stage_boxes) == ["experimental_conditions", "wet_dry"]
        from PySide6.QtWidgets import QCheckBox
        assert len(w.stages_widget.findChildren(QCheckBox)) == 2          # the old area's boxes are gone
        assert "when the paper calls for it" in w.stage_boxes["wet_dry"].text()
        w.pack_combo.setCurrentIndex(w.pack_combo.findData("exoplanets"))
        assert not w.stage_boxes["fit_models"].isChecked()                  # remembered for this area
        w.pack_combo.setCurrentIndex(w.pack_combo.findData("prebiotic_chemistry"))
        w.close()
        w2 = main_window.MainWindow()                                       # and across restarts
        w2.pack_combo.setCurrentIndex(w2.pack_combo.findData("exoplanets"))
        assert not w2.stage_boxes["fit_models"].isChecked()
        w2.pack_combo.setCurrentIndex(w2.pack_combo.findData("prebiotic_chemistry"))
        w2.close()
        if not truman.is_file():
            print(f"SKIP (run part): needs {truman}"); return

    replay = make_replay(root / "runs" / "truman2024_auto")
    for ticked in (False, True):
        calls = []
        def send(ctx, **kw):
            calls.append(kw["response_model"].__name__)
            return replay(ctx, **kw)
        with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", send), \
                patch.object(main_window, "key_store", keys), \
                patch.object(main_window, "FigureReviewDialog", SkipAllFigures), \
                patch.object(main_window, "VariableReviewDialog", NoClickReview):
            w = _window(keys, Path(tmp))
            w.registry_path = None                                           # template + standard columns only
            w.pack_combo.setCurrentIndex(w.pack_combo.findData("prebiotic_chemistry"))
            w.stage_boxes["wet_dry"].setChecked(ticked)
            w.pdf_edit.setText(str(truman)); w.key_edit.setText("replay-not-a-real-key")
            w.run_btn.click()
            assert not w.pack_combo.isEnabled() and not w.stages_widget.isEnabled()   # locked while running
            for _ in range(1200):
                _pump()
                if "Done:" in w.status.text() or "failed" in w.status.text().lower():
                    break
            assert "Done:" in w.status.text(), w.status.text()
            assert ("WetDryConditions" in calls) == ticked, calls
            assert w.pack_combo.isEnabled() and w.stages_widget.isEnabled()
            summary = w.summary_text.toPlainText()
            assert ("Wet-dry" in summary) == ticked, summary
            w.close()



def test_settings_and_run_options():
    """Mickey, 2026-10-24: set-once things in Settings, per-run choices in a collapsible section."""
    keys = FakeKeyStore(ads="ads-stored")
    with tempfile.TemporaryDirectory() as tmp, patch.object(main_window, "key_store", keys):
        w = _window(keys, Path(tmp))
        w.show()
        _pump()
        assert w.key_edit.window() is w.settings_dialog and w.out_edit.window() is w.settings_dialog
        assert w.ads_edit.text() == "ads-stored" and w.remember_ads_box.isChecked()   # from the keychain
        assert not w.options_widget.isVisible()                                         # collapsed at first
        assert "Standard models" in w.options_summary.text() and "stages" in w.options_summary.text()
        w.options_btn.click()
        assert w.options_widget.isVisible() and QSettings().value("options_shown", type=bool)
        assert w.suggest_box.isChecked() and w.current_config().suggest_new_variables   # on by default
        assert w.toggles_btn.text() == "Variable suggestions, SI, Images"            # the dropdown says what's on
        cfg = w.current_config()
        assert cfg.save_images and not cfg.save_all_figure_images                       # image defaults
        w.images_box.setChecked(False)
        assert not w.all_figures_box.isEnabled()
        w.images_box.setChecked(True)
        w.batch_box.setChecked(True)
        w.arxiv_box.setChecked(True)
        w.suggest_box.setChecked(False)
        assert "batch" in w.options_summary.text() and "arXiv text" in w.options_summary.text()
        assert "no new-variable suggestions" in w.options_summary.text()
        assert w.toggles_btn.text().startswith("Batch, arXiv text")
        assert len(w.toggles_btn.menu().actions()) == 7 and w.current_config().include_supplements
        assert w.settings_hint.isVisible() and "API key" in w.settings_hint.text()       # no key yet
        w.key_edit.setText("k")
        assert not w.settings_hint.isVisible()
        w.open_settings()
        assert w.settings_dialog.isVisible()
        w.settings_dialog.hide()
        config = w.current_config()
        assert config.prefer_arxiv and config.batch_mode and config.ads_token == "ads-stored"
        assert not config.suggest_new_variables
        w._save_preferences()
        assert QSettings().value("suggest_new_variables", type=bool) is False
        w.remember_ads_box.setChecked(False)
        w._save_preferences()
        assert keys.other == {}                                            # un-ticked: forgotten
        # the paper field also takes identifiers
        for text, expected in (("10.1093/pasj/psad056", "10.1093/pasj/psad056"), ("arXiv:2308.05343", "arXiv:2308.05343"),
                               (str(Path(tmp) / "missing.pdf"), None)):
            w.pdf_edit.setText(text)
            assert w.paper_item() == expected, text
        _screenshot(w, "settings_main")
        w.close()


def test_tokens_are_remembered_without_a_run():
    """Mickey, 2026-10-29: the ADS token typed into Settings was gone after reopening the app --
    keys were only saved when an extraction started. Now: on closing Settings and on quitting."""
    keys = FakeKeyStore()
    with tempfile.TemporaryDirectory() as tmp, patch.object(main_window, "key_store", keys):
        w = _window(keys, Path(tmp))
        w.show(); _pump()
        w.open_settings(); _pump()
        w.ads_edit.setText("ads-new")
        w.remember_ads_box.setChecked(True)
        w.settings_dialog.hide(); _pump()                                 # closing Settings saves it
        assert keys.other == {keys.ADS_ACCOUNT: "ads-new"}
        w.ads_edit.setText("ads-changed")
        w.key_edit.setText("sk-typed"); w.remember_key_box.setChecked(True)
        w.close(); _pump()                                                # quitting saves too
        assert keys.other[keys.ADS_ACCOUNT] == "ads-changed" and keys.saved[-1] == "sk-typed"
        w2 = _window(keys, Path(tmp))                                     # "reopening the app"
        assert w2.ads_edit.text() == "ads-changed" and w2.remember_ads_box.isChecked()
        w2.ads_edit.setText("")                                           # emptied: forgotten
        w2.settings_dialog.show(); w2.settings_dialog.hide(); _pump()
        assert keys.ADS_ACCOUNT not in keys.other
        w2.close()


def test_a_paper_by_arxiv_id_from_the_window():
    from parameter_extractor import packs
    from parameter_extractor.ingestion import arxiv_source as ax
    from parameter_extractor.validation import exoplanet_archive
    from test_arxiv_source import FIX, fake_get
    from test_pipeline_offline import make_replay
    keys = FakeKeyStore()
    saved = __import__("json").loads((FIX / "archive_rows.json").read_text())
    try:
        with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", make_replay(FIX)), \
                patch.object(ax, "_get", fake_get()), patch.object(main_window, "key_store", keys), \
                patch.object(exoplanet_archive, "fetch_parameter_sets", lambda names, ref: saved):
            w = _window(keys, Path(tmp))
            w.pack_combo.setCurrentIndex(w.pack_combo.findData("exoplanets"))
            w.pdf_edit.setText("arXiv:1811.01882")
            w.key_edit.setText("replay-not-a-real-key")
            assert w.run_btn.isEnabled()
            w.run_btn.click()
            _wait_until_idle(w)
            assert "Done: 1 rows" in w.status.text(), w.status.text()
            groups = [w.flags_tree.topLevelItem(i).text(0) for i in range(w.flags_tree.topLevelItemCount())]
            assert any(g.startswith("Where the text came from") for g in groups), groups
            w.close()
    finally:
        packs.activate("prebiotic_chemistry")


def test_focused_search_window():
    from parameter_extractor import packs
    from parameter_extractor.ingestion import arxiv_source as ax
    from test_arxiv_source import fake_get
    from test_focused_search import _fake_send
    keys = FakeKeyStore()
    calls = []
    try:
        with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", _fake_send(calls)), \
                patch.object(ax, "_get", fake_get()), patch.object(main_window, "key_store", keys):
            w = _window(keys, Path(tmp))
            w.key_edit.setText("x")
            w.pack_combo.setCurrentIndex(w.pack_combo.findData("exoplanets"))
            w.focused_btn.click()                                  # the button and File menu both open it
            f = w._focused_window
            assert f.isVisible() and not f.run_btn.isEnabled()
            groups = [f.params_tree.topLevelItem(i).text(0) for i in range(f.params_tree.topLevelItemCount())]
            assert groups[:3] == ["Planet parameters", "Stellar parameters", "System and discovery"]
            assert "Fitting models" in groups
            f.filter_edit.setText("exofast")
            visible = [f.params_tree.topLevelItem(i) for i in range(f.params_tree.topLevelItemCount())
                       if not f.params_tree.topLevelItem(i).isHidden()]
            assert [g.text(0) for g in visible] == ["Fitting models"]
            fit = visible[0]
            for j in range(fit.childCount()):
                if fit.child(j).text(0) in ("pl_fitsoftware", "pl_fitexofastver"):
                    fit.child(j).setCheckState(0, Qt.CheckState.Checked)
            assert f.checked_columns() == ["pl_fitsoftware", "pl_fitexofastver"]
            f.id_edit.setText("arXiv:1811.01882, not-an-id")
            f._add_typed()
            assert f.papers_list.count() == 1 and f.id_edit.text() == "not-an-id"
            f.add_items([PDF])
            f.words_edit.setText("EXOFAST")
            assert f.tables_box.isChecked() and f.tables_box.isEnabled()          # whole tables by default
            f.whole_box.setChecked(True)
            assert not f.tables_box.isEnabled()                                    # whole paper covers them
            f.whole_box.setChecked(False)
            assert f.run_btn.isEnabled()
            f.run_btn.click()
            assert not w.run_btn.isEnabled() and not w.pack_combo.isEnabled()      # main window locked
            for _ in range(600):
                if not f.running:
                    break
                _pump()
            assert not f.running and "Done:" in f.status.text(), f.status.text()
            assert f.results.rowCount() == 2 and len(calls) == 1
            headers = [f.results.horizontalHeaderItem(c).text() for c in range(f.results.columnCount())]
            assert headers == ["Paper", "Planetary system", "Planet", "Result", "pl_fitsoftware", "pl_fitexofastver",
                               "Read from"]                                    # the pack's row words
            by_result = {f.results.item(r, 3).text(): r for r in range(2)}
            found = by_result["Found"]
            assert (f.results.item(found, 4).text(), f.results.item(found, 5).text()) == ("EXOFASTv2", "2")
            assert "using EXOFASTv2" in f.results.item(found, 5).toolTip()          # the quote on hover
            assert "Not mentioned (no API call)" in by_result
            assert f.open_csv_btn.isEnabled() and w.pack_combo.isEnabled()
            assert not f.retry_btn.isEnabled()                                   # nothing failed
            _screenshot(f, "focused_search")
            f.close()
            w.close()
    finally:
        packs.activate("prebiotic_chemistry")


class SkipReview(QObject):
    """Stands in for FigureReviewDialog in the queue: opens, then skips every figure."""
    finished = Signal(int)
    opened = []
    def __init__(self, figures, columns, plan_bridge=None, parent=None):
        super().__init__()
        self.figures, self.digitized, self.skipped = figures, [], [f.figure_id for f in figures]
    def setWindowTitle(self, title): SkipReview.opened.append(title)
    def set_background_status(self, text): pass
    def show(self): QTimer.singleShot(50, lambda: self.finished.emit(0))


def test_paper_queue_window():
    """File > Paper queue: papers read first, each paper's figures reviewed as it's read, the rest
    without the user, then a combined CSV."""
    from parameter_extractor.gui import figure_dialog
    from test_paper_queue import EDER, TRUMAN, routed_send
    if not (EDER.is_file() and TRUMAN.is_file()):
        print("SKIP: needs eder1994.pdf and truman2024.pdf"); return
    keys = FakeKeyStore()
    SkipReview.opened = []
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", routed_send), \
            patch.object(main_window, "key_store", keys), patch.object(figure_dialog, "FigureReviewDialog", SkipReview):
        w = _window(keys, Path(tmp))
        w.key_edit.setText("x")
        w.queue_btn.click()
        q = w._queue_window
        assert q.isVisible() and not q.run_btn.isEnabled()
        q.paper_panel.add_items([EDER, TRUMAN])
        q.variables_box.setChecked(False)                     # unattended to the end
        q.run_btn.click()
        assert q.running and not w.run_btn.isEnabled() and not w.focused_btn.isEnabled()
        for _ in range(1200):
            if q._summary:
                break
            _pump()
        assert q._summary, q.status.text()
        assert SkipReview.opened == ["Figures -- eder1994 (001)", "Figures -- truman2024 (002)"]   # in list order
        statuses = [q.table.item(r, 1).text() for r in range(q.table.rowCount())]
        assert statuses == ["Done", "Done"], statuses
        assert q.table.item(0, 2).text() == "0 digitized / 5" and q.table.item(0, 4).text() == "42"
        assert q._summary["rows"] == 42 + int(q.table.item(1, 4).text())
        assert Path(q._summary["csv"]).is_file() and q.open_csv_btn.isEnabled()
        assert w.queue_btn.isEnabled() and w.pack_combo.isEnabled()        # the main window is free again
        _screenshot(q, "paper_queue")
        q.close()
        w.close()

if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
                print(f"PASS: {name}")
        print("All offline GUI tests passed.")
    finally:
        QSettings().clear()
