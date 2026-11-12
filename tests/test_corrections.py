"""
Offline tests for corrections and checked marks (W2, corrections.py, 2026-11-11): a value corrected in the results
window is saved with the run and in its files (the wide CSV, the observations CSV with the extracted value kept, a
queue's combined files), checked against its column, reverted, carried over by a rebuild; entries of "Things to
check" ticked, counted and filtered; all of it again after the run is reopened. eder1994 replay, no API.

Run with: python tests/test_corrections.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import csv
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client, corrections as corr, resume, run_folder  # noqa: E402
from parameter_extractor.pipeline import run_pipeline  # noqa: E402
from test_pipeline_offline import PDF, _config, _have_inputs, _replay_send  # noqa: E402


def _run(out: Path):
    with patch.object(api_client, "_send", _replay_send):
        return run_pipeline(PDF, _config(out))


def _cell(path: Path, full_id: str, column: str) -> str:
    with open(path, newline="", encoding="utf-8") as f:
        return next(r for r in csv.DictReader(f) if r["full_id"] == full_id).get(column, "")


def _line(path: Path, full_id: str, column: str) -> dict:
    with open(path, newline="", encoding="utf-8") as f:
        return next((r for r in csv.DictReader(f) if r["full_id"] == full_id and r["column"] == column), {})


def _an_empty_column(result) -> str:
    """A column the dataset has for the paper's rows but left empty in the first row."""
    with open(result.csv_path, newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    return next(c for c, v in row.items() if not v and c.startswith("initial_") and c.endswith("_mM"))


def test_a_correction_updates_the_files_and_reverts():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp))
        run, fid = result.run_dir, result.rows[0].full_id
        obs = result.observations_path
        extracted = _cell(result.csv_path, fid, "initial_temperature_C")
        value, problem = corr.stored_value("initial_temperature_C", "363.15 K")     # a unit converts
        assert not problem and value == "90.0"
        assert corr.stored_value("initial_temperature_C", "hot")[1]                 # not a number: refused
        corr.correct(run, fid, "initial_temperature_C", extracted, value, note="Methods, p. 2")
        assert _cell(result.csv_path, fid, "initial_temperature_C") == "90.0"
        line = _line(obs, fid, "initial_temperature_C")
        assert line["value"] == "90.0" and line["extracted_value"] == extracted and line["corrected"].startswith("yes")
        saved = corr.load(run)[(fid, "initial_temperature_C")]
        assert saved.extracted == extracted and saved.note == "Methods, p. 2"
        corr.correct(run, fid, "initial_temperature_C", "90.0", "95.0")                  # a second change keeps the
        assert corr.load(run)[(fid, "initial_temperature_C")].extracted == extracted   # value as extracted
        empty = _an_empty_column(result)                                             # a value the extraction missed
        corr.correct(run, fid, empty, "", "12.5")
        assert _cell(result.csv_path, fid, empty) == "12.5" and _line(obs, fid, empty)["origin"] == "corrected"
        corr.revert(run, fid, empty)
        assert _cell(result.csv_path, fid, empty) == "" and not _line(obs, fid, empty)
        corr.correct(run, fid, "initial_temperature_C", "95.0", extracted)             # typing it back = reverting
        assert not corr.load(run) and not (run / corr.CORRECTIONS_FILE).exists()
        assert _cell(result.csv_path, fid, "initial_temperature_C") == extracted
        assert _line(obs, fid, "initial_temperature_C")["value"] == extracted
        try:
            corr.correct(run, fid, "full_id", fid, "x")
            raise AssertionError("row ids can't be corrected")
        except ValueError:
            pass


def test_a_queue_papers_correction_reaches_the_combined_files():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        queue = Path(tmp) / "queue_x"
        result = _run(queue)
        shutil.copy(result.csv_path, queue / "combined_extracted.csv")
        shutil.copy(result.observations_path, queue / "combined_observations.csv")
        fid = result.rows[1].full_id
        corr.correct(result.run_dir, fid, "duration_hr", _cell(result.csv_path, fid, "duration_hr"), "7")
        assert _cell(queue / "combined_extracted.csv", fid, "duration_hr") == "7"
        assert _line(queue / "combined_observations.csv", fid, "duration_hr")["value"] == "7"


def test_a_rebuild_keeps_corrections_and_checked_marks():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp))
        fid = result.rows[2].full_id
        corr.correct(result.run_dir, fid, "initial_temperature_C",
                     _cell(result.csv_path, fid, "initial_temperature_C"), "88", note="checked")
        key = corr.flag_key(result.paper_flags[0])
        corr.save_checked(result.run_dir, {key})

        def no_send(*a, **k):
            raise AssertionError("a rebuild asks nothing")
        with patch.object(api_client, "_send", no_send):
            again = resume.resume_run(result.run_dir, _config(Path(tmp)), rebuild=True)
        assert _cell(again.csv_path, fid, "initial_temperature_C") == "88"
        assert corr.load(again.run_dir)[(fid, "initial_temperature_C")].note == "checked"
        assert corr.load_checked(again.run_dir) == {key}
        assert corr.flag_key(again.paper_flags[0]) == key                         # the same flag, the same key
        summary = json.loads((again.run_dir / "run_summary.json").read_text())
        assert summary["corrections_carried_over"] == 1


def test_the_results_window():
    if not _have_inputs():
        return
    from PySide6.QtCore import QCoreApplication, QSettings, Qt
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setOrganizationName("ParameterExtractorTests")
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui import main_window
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp))
        QSettings().clear()
        w = main_window.MainWindow()
        w.registry_path = Path(tmp) / "registry.json"
        w.show_result(result)
        t = w.rows_table
        header = [t.horizontalHeaderItem(c).data(Qt.ItemDataRole.UserRole) for c in range(t.columnCount())]
        col = header.index("initial_temperature_C")
        assert not (t.item(0, header.index("full_id")).flags() & Qt.ItemFlag.ItemIsEditable)
        item = t.item(0, col)
        before = item.text()
        warned = []
        with patch.object(main_window.QMessageBox, "warning", lambda *a: warned.append(a[2])):
            t.item(0, col).setText("very hot")                                    # refused, the old value back
        assert warned and t.item(0, col).text() == before and not corr.load(result.run_dir)
        t.item(0, col).setText("91")
        app.processEvents()
        fid = t.item(0, header.index("full_id")).text()
        assert corr.load(result.run_dir)[(fid, "initial_temperature_C")].value == "91.0"
        cell = t.item(0, col)
        assert cell.text() == "91.0" and cell.background().color() == main_window.CORRECTED_COLOR
        assert "Corrected by you" in cell.toolTip() and repr(before) in cell.toolTip()
        assert "Corrected initial_temperature_C" in w.status.text()
        # Things to check: tick one, the count and the filter follow; saved with the run
        entries = [child for _g, child in w._flag_entries()]
        assert entries and w.tabs.tabText(1) == f"Things to check ({len(entries)})"
        entries[0].setCheckState(0, Qt.CheckState.Checked)
        assert w.tabs.tabText(1) == f"Things to check ({len(entries) - 1} of {len(entries)} left)"
        w.unchecked_only_box.setChecked(True)
        assert entries[0].isHidden() and (len(entries) == 1 or not entries[-1].isHidden())
        assert len(corr.load_checked(result.run_dir)) == 1
        w.unchecked_only_box.setChecked(False)
        # reopened later: the correction and the tick are still there
        w2 = main_window.MainWindow()
        w2.registry_path = Path(tmp) / "registry.json"
        w2.show_result(run_folder.load_result(result.run_dir))
        t2 = w2.rows_table
        assert t2.item(0, col).text() == "91.0" and t2.item(0, col).background().color() == main_window.CORRECTED_COLOR
        assert w2.tabs.tabText(1) == f"Things to check ({len(entries) - 1} of {len(entries)} left)"
        w.close()
        w2.close()
        app.processEvents()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All correction tests passed.")
