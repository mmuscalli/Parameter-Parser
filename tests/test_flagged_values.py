"""
Offline tests for which values a flag is about and the Flagged values window (flag_targets.py, gui/flagged_values.py;
Mickey, 2026-11-11, after an eder1994 review): flags about exactly the same values merged (different kinds, located
precisely), older run folders consolidated when opened, the window's rows / every-row flags / details / image / ticks /
corrections. eder1994 replay, no API.

Run with: python tests/test_flagged_values.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client, corrections as corr, flag_targets as ft, run_folder  # noqa: E402
from parameter_extractor.pipeline import run_pipeline  # noqa: E402
from parameter_extractor.validation.plausibility_checks import Flag  # noqa: E402
from test_pipeline_offline import PDF, _config, _have_inputs, _replay_send  # noqa: E402

SRC = "Table 2, Conditions (right block, third group)"


def _index():
    obs = [{"full_id": f"0010130{i}", "column": "initial_BaCl2_aq_mM", "value": "2500.0",
            "source": SRC + " [mM computed by the pipeline from 2.5 mol dm-3]", "quote": "2.50 mol dm-3 87 °C"}
           for i in (1, 2, 3)]
    obs += [{"full_id": f"0010120{i}", "column": "initial_CaCl2_aq_mM", "value": "2500.0", "source": "Table 2",
             "quote": ""} for i in (1, 2, 3)]
    obs += [{"full_id": f"0010120{i}", "column": "experiment_type", "value": "Batch", "source": "", "quote": ""}
            for i in (1, 2, 3)]
    return ft.Index(obs)


def test_flags_about_the_same_values_are_merged():
    idx = _index()
    ident = Flag("identity_not_quoted", "BaCl2: the quote for 1 value(s) doesn't name it", quote="2.50 mol dm-3 87 °C",
                 source=SRC)
    low = Flag("low_confidence", "initial BaCl2 = 2.5 mol dm-3 (set 'Ba2+') has confidence 'medium'.", source=SRC)
    cells, precise = ft.located(low, idx)
    assert precise and cells == {(f"0010130{i}", "initial_BaCl2_aq_mM") for i in (1, 2, 3)}
    merged, _ = ft.consolidate([low, ident], {}, idx)
    assert len(merged) == 1 and merged[0].kind == "identity_not_quoted"        # the stronger reason leads
    assert "Also flagged for the same value(s):\n- (low confidence) initial BaCl2" in merged[0].message
    # the same kind twice (one per species / planet): kept apart; a guess (every row of a column): not merged
    twin = Flag("identity_not_quoted", "BaCl2: a second, other note", source=SRC)
    assert len(ft.consolidate([ident, twin], {}, idx)[0]) == 2
    a = Flag("low_confidence", "experiment_type = 'Batch' for every experiment set has confidence 'medium'.")
    b = Flag("derived_value", "experiment_type filled from the setup.")
    assert not ft.located(a, idx)[1] and len(ft.consolidate([a, b], {}, idx)[0]) == 2
    # flags about the paper aren't about values
    assert ft.targets(Flag("reused_answer", "Resumed from ..."), idx) == set()


def test_the_flagged_values_window():
    if not _have_inputs():
        return
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setOrganizationName("ParameterExtractorTests")
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.flagged_values import FlaggedValuesWindow
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(api_client, "_send", _replay_send):
            result = run_pipeline(PDF, _config(Path(tmp)))
        opened = run_folder.load_result(result.run_dir)
        changes = []
        w = FlaggedValuesWindow(opened, on_changed=lambda: changes.append(1))
        t = w.table
        cols = [t.horizontalHeaderItem(c).text() for c in range(t.columnCount())]
        assert cols[:3] == ["full_id", "set_id", "sample_id"]
        flagged_rows = {fid for fid, _ in w.cell_flags}
        assert t.rowCount() == len(flagged_rows) and t.rowCount() < len(result.rows)  # only rows with a flagged value
        assert w.everywhere                                       # e.g. total_sampled_peptides_yield on every row
        r, c = next((r, c) for r in range(t.rowCount()) for c in range(t.columnCount())
                    if w._cell_of(r, c) in w.cell_flags)
        assert t.item(r, c).background().color().name() == "#ff9646"
        t.setCurrentCell(r, c)
        app.processEvents()
        assert w.flag_list.count() >= 1 and "Issue" in w.details.toPlainText()
        if w.image_caption.text():                                 # a table, figure or page image where there is one
            assert "Table" in w.image_caption.text() or "page" in w.image_caption.text()
        item = w.flag_list.item(0)
        key = item.data(Qt.ItemDataRole.UserRole)[1]
        item.setCheckState(Qt.CheckState.Checked)                  # ticked here = ticked in Things to check
        assert key in corr.load_checked(result.run_dir) and changes      # (the list is rebuilt after a tick)
        # correcting a flagged value from here
        full_id, column = w._cell_of(r, c)
        if column not in corr.FIXED_COLUMNS and "_mM" in column:
            t.item(r, c).setText("1.5")
            app.processEvents()
            assert corr.load(result.run_dir)[(full_id, column)].value == "1.5"
        w.close()
        app.processEvents()


def test_opened_from_things_to_check():
    """The way a user opens it: the button on Things to check (MainWindow.review_flagged_values), and the main tabs
    refreshed after a tick made in the window."""
    if not _have_inputs():
        return
    from PySide6.QtCore import QCoreApplication, QSettings, Qt
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setOrganizationName("ParameterExtractorTests")
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui import flagged_values, main_window
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(api_client, "_send", _replay_send):
            result = run_pipeline(PDF, _config(Path(tmp)))
        QSettings().clear()
        w = main_window.MainWindow()
        w.registry_path = Path(tmp) / "registry.json"
        w.show_result(result)
        total = len([c for _g, c in w._flag_entries()])

        def use(window):                    # stands in for the user: tick the first flag of the first flagged value
            r, c = next((r, c) for r in range(window.table.rowCount()) for c in range(window.table.columnCount())
                        if window._cell_of(r, c) in window.cell_flags)
            window.table.setCurrentCell(r, c)
            window.flag_list.item(0).setCheckState(Qt.CheckState.Checked)
            return 0
        with patch.object(flagged_values.FlaggedValuesWindow, "exec", use):
            assert w.review_flagged_btn.isEnabled()
            w.review_flagged_btn.click()
        app.processEvents()
        assert w.tabs.tabText(1) == f"Things to check ({total - 1} of {total} left)"
        w.close()
        app.processEvents()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All flagged-value tests passed.")
