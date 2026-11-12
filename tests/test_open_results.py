"""
Offline tests for opening an earlier run (W3, 2026-11-11): run_folder.load_result reads a run folder back into the
same RunResult the window shows after a run, and File > Open a results folder… shows it. Uses the eder1994 replay
(no API calls) and the older recorded fixtures in runs/.

Run with: python tests/test_open_results.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client, run_folder  # noqa: E402
from parameter_extractor.errors import PipelineError  # noqa: E402
from parameter_extractor.pipeline import run_pipeline  # noqa: E402
from test_pipeline_offline import PDF, ROOT, _config, _have_inputs, _replay_send  # noqa: E402


def _fresh_run(out: Path):
    with patch.object(api_client, "_send", _replay_send):
        return run_pipeline(PDF, _config(out))


def _same_result(a, b) -> None:
    """Everything the results tabs show is read back unchanged."""
    assert a.paper_id == b.paper_id and a.csv_path == b.csv_path and a.run_dir == b.run_dir
    assert [r.full_id for r in a.rows] == [r.full_id for r in b.rows]
    for ra, rb in zip(a.rows, b.rows):
        for col, src in rb.provenance.items():                  # every cell with a value (the ones a hover shows)
            if not ra.values.get(col):
                continue
            got = ra.provenance.get(col)
            assert got is not None, (ra.full_id, col)
            assert (got.origin, got.quote, got.source, got.confidence, got.quote_check, str(got.page or "")) == \
                   (src.origin, src.quote, src.source, src.confidence, src.quote_check, str(src.page or "")), \
                   (ra.full_id, col)
        assert (ra.original_data_reference or None) == (rb.original_data_reference or None)
    assert [f.to_dict() for f in a.paper_flags] == [f.to_dict() for f in b.paper_flags]
    assert {k: [f.to_dict() for f in v] for k, v in a.row_flags.items()} == \
           {k: [f.to_dict() for f in v] for k, v in b.row_flags.items()}
    assert [(u.stage, u.model, u.input_tokens, u.output_tokens) for u in a.usage] == \
           [(u.stage, u.model, u.input_tokens, u.output_tokens) for u in b.usage]
    assert a.cost_usd == b.cost_usd and a.input_tokens == b.input_tokens
    assert [f["figure_id"] for f in a.figures] == [f["figure_id"] for f in b.figures]
    assert [t["table_id"] for t in a.tables] == [t["table_id"] for t in b.tables]
    assert [e.label for e in a.equations] == [e.label for e in b.equations]
    assert [v.name for v in a.new_variables] == [v.name for v in b.new_variables]
    assert a.accepted_variables == b.accepted_variables and a.unfound_terms == b.unfound_terms


def test_a_run_reads_back_as_it_finished():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        result = _fresh_run(Path(tmp))
        opened = run_folder.load_result(result.run_dir)
        assert opened.opened and not opened.opened_notes and opened.pack == "prebiotic_chemistry"
        assert opened.app_version
        assert not result.opened                                # a run that just finished isn't marked
        # rows: provenance for cells with a source (the run's rows also hold cells with none)
        for r in result.rows:
            r.provenance = {c: s for c, s in r.provenance.items() if s.origin or s.quote or s.source}
        _same_result(opened, result)


def test_a_moved_folder_finds_its_images_and_a_queue_folder_lists_its_runs():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        result = _fresh_run(Path(tmp) / "first")
        queue = Path(tmp) / "queue_20261111-120000"
        queue.mkdir()
        a = queue / "001_eder1994_20261111-120000"
        b = queue / "002_eder1994_20261111-120100"
        shutil.copytree(result.run_dir, a)
        shutil.copytree(result.run_dir, b)
        shutil.rmtree(Path(tmp) / "first")                     # the absolute paths in its summary are gone now
        assert run_folder.runs_in(queue) == [a, b] and run_folder.runs_in(a) == [a]
        opened = run_folder.load_result(a)
        images = [t["image"] for t in opened.tables if t.get("image")]
        assert images and all(Path(p).is_file() and Path(p).parent == a / "tables" for p in images)
        assert opened.run_dir == a and opened.csv_path.parent == a


def test_folders_that_are_not_finished_runs():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        assert run_folder.runs_in(tmp) == []
        try:
            run_folder.load_result(tmp)
            raise AssertionError("not a run folder: should be refused")
        except PipelineError as e:
            assert "run_summary.json" in str(e)
        (tmp / "run_summary.json").write_text("{}")
        (tmp / "error.txt").write_text("Your credit balance is too low.\nmore")
        try:
            run_folder.load_result(tmp)
            raise AssertionError("no dataset: should be refused")
        except PipelineError as e:
            assert "didn't finish" in str(e) and "credit balance" in str(e)


def test_older_folders_open_with_what_they_have():
    for name in ("kim2019_auto", "truman2024_auto", "teng2023_auto", "nielsen2019_auto"):
        folder = ROOT / "runs" / name
        if not folder.is_dir():
            print(f"SKIP: needs {folder}")
            return
        opened = run_folder.load_result(folder)
        assert opened.rows and opened.usage and all(r.full_id for r in opened.rows), name
        assert sum(len(r.provenance) for r in opened.rows) > 0, name


def test_the_window_shows_an_opened_run():
    if not _have_inputs():
        return
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setOrganizationName("ParameterExtractorTests")
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui import main_window
    with tempfile.TemporaryDirectory() as tmp:
        result = _fresh_run(Path(tmp) / "runs")
        queue = Path(tmp) / "queue"
        queue.mkdir()
        shutil.copytree(result.run_dir, queue / "001_eder1994_a")
        shutil.copytree(result.run_dir, queue / "002_eder1994_b")
        QSettings().clear()
        w = main_window.MainWindow()
        w.registry_path = Path(tmp) / "registry.json"
        assert w.open_results_action.isEnabled()
        # the way a user opens it: the File menu item (its `checked` flag must not reach the method as the folder --
        # 2026-11-12, 'argument should be a str ... not bool')
        from unittest.mock import patch
        with patch.object(main_window.QFileDialog, "getExistingDirectory", lambda *a, **k: str(result.run_dir)):
            w.open_results_action.trigger()
        app.processEvents()
        n_flags = len(result.paper_flags) + sum(len(f) for f in result.row_flags.values())
        assert w.rows_table.rowCount() == len(result.rows)
        assert w.tabs.tabText(1) == f"Things to check ({n_flags})"
        assert "opened from its folder (data pack: Prebiotic chemistry; made by version" in w.summary_text.toPlainText()
        assert "Showing an earlier run" in w.status.text()
        # a hover shows where a value came from
        header = [w.rows_table.horizontalHeaderItem(c).text() for c in range(w.rows_table.columnCount())]
        cell = w.rows_table.item(0, header.index("initial_temperature_C"))
        assert cell.toolTip()
        w._open_results_folder(queue, pick="002_eder1994_b")          # a queue folder: the chosen paper
        app.processEvents()
        assert w._last_run_dir == queue / "002_eder1994_b"
        w._set_inputs_enabled(False)                                 # locked while something runs
        assert not w.open_results_action.isEnabled()
        w.close()
        time.sleep(0.05)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All open-results tests passed.")
