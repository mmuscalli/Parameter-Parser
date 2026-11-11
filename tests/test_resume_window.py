"""
Offline window tests for resume and rebuild (W1, 2026-11-11): File > Resume a stopped run… / Rebuild a run's
dataset…, the Resume link after a stopped run, and a queue folder resumed in the window. eder1994 replay, no API.

Run with: python tests/test_resume_window.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_gui_offline import APP, FakeKeyStore, _pump, _wait_until_idle, _window  # noqa: E402
from parameter_extractor import api_client, errors  # noqa: E402
from parameter_extractor.gui import main_window  # noqa: E402
from parameter_extractor.pipeline import run_pipeline  # noqa: E402
from test_pipeline_offline import PDF, REPLAY_DIR, _config, _have_inputs, _replay_send  # noqa: E402
from test_resume import _asking, _no_send, _settled  # noqa: E402

COMMITTED = REPLAY_DIR / "eder1994_auto_extracted.csv"


def _failed_run(out: Path) -> Path:
    with patch.object(api_client, "_send", _asking([], fail_on="ChemistryExtraction")):
        try:
            run_pipeline(PDF, _config(out))
        except errors.PipelineError:
            pass
    _settled(out)
    return next(p for p in out.iterdir() if p.is_dir() and p.name.startswith("eder1994_"))


def _quiet(w):
    """No dialogs a test would have to click: no new-variable review, no figure review."""
    w._review_new_variables = lambda groups, unfound, registry: []
    w.review_figures_box.setChecked(False)
    w.review_variables_box.setChecked(False)


def test_resume_a_failed_run_from_the_menu():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        old = _failed_run(tmp / "runs")
        w = _window(FakeKeyStore(stored="sk-ant-test"), tmp / "elsewhere")
        _quiet(w)
        log = []
        with patch.object(api_client, "_send", _asking(log)):
            w.resume_run(old)
            _wait_until_idle(w)
            _pump()
        assert "ChemistryExtraction" in log and "StructurePlan" not in log, log
        new = w._last_run_dir
        assert new != old and new.parent == old.parent                  # next to the old folder
        assert (new / "eder1994_extracted.csv").read_text() == COMMITTED.read_text()
        assert w.rows_table.rowCount() == 42 and w.resume_action.isEnabled()
        summary = json.loads((new / "run_summary.json").read_text())
        assert summary["resumed_from"] == str(old) and summary["rebuilt"] is False
        groups = [w.flags_tree.topLevelItem(i).text(0) for i in range(w.flags_tree.topLevelItemCount())]
        assert any("Reused from an earlier run" in g for g in groups), groups
        w.close()


def test_rebuild_needs_no_key_and_asks_nothing():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with patch.object(api_client, "_send", _replay_send):
            first = run_pipeline(PDF, _config(tmp / "runs"))
        w = _window(FakeKeyStore(stored=""), tmp / "elsewhere")           # no API key set
        _quiet(w)
        with patch.object(api_client, "_send", _no_send):
            w.resume_run(first.run_dir, rebuild=True)
            _wait_until_idle(w)
            _pump()
        assert w._last_run_dir != first.run_dir
        assert (w._last_run_dir / "eder1994_extracted.csv").read_text() == COMMITTED.read_text()
        assert "Done:" in w.status.text()
        w.close()


def test_the_resume_link_after_a_stopped_run():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        old = _failed_run(tmp / "runs")
        w = _window(FakeKeyStore(stored="sk-ant-test"), tmp / "runs")
        _quiet(w)
        w._stopped_dir = old                    # as _on_cancelled leaves it (its status line has the link)
        with patch.object(api_client, "_send", _replay_send):
            w._status_link("resume")
            _wait_until_idle(w)
            _pump()
        assert w._last_run_dir not in (None, old) and w.rows_table.rowCount() == 42
        w.close()


def test_a_queue_folder_rebuilt_in_the_window():
    if not _have_inputs():
        return
    from parameter_extractor.paper_queue import run_queue
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with patch.object(api_client, "_send", _replay_send):
            old = run_queue([PDF], _config(tmp / "runs"))
        w = _window(FakeKeyStore(stored=""), tmp / "elsewhere")
        _quiet(w)
        with patch.object(api_client, "_send", _no_send):
            w.resume_run(old.out_dir, rebuild=True)
            for _ in range(1200):
                if not w.queue_run.running:
                    break
                _pump()
            _pump()
        queue = w.queue_run.queue
        assert queue.out_dir != old.out_dir and queue.papers[0].status == "finished"
        assert w.papers.count() == 1 and w.resume_action.isEnabled()
        w.close()


def test_resume_offered_when_a_run_fails():
    """A run that fails after some answers were saved offers Resume; choosing it starts the resumed run once the
    failed one has ended, in a new folder."""
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        w = _window(FakeKeyStore(stored="sk-ant-test"), tmp / "runs")
        _quiet(w)
        offered = []
        w._ask_resume = lambda message: offered.append(message) or True
        failures = []

        def once(ctx, **kw):                    # the chemistry step fails the first time only
            if kw["response_model"].__name__ == "ChemistryExtraction" and not failures:
                failures.append(1)
                raise errors.NetworkError()
            return _replay_send(ctx, **kw)
        with patch.object(api_client, "_send", once):
            w.pdf_edit.setText(str(PDF))
            w.run_btn.click()
            _wait_until_idle(w)
            for _ in range(200):                # the resume starts from a timer, then runs on the worker
                _pump()
                if w._running:
                    break
            _wait_until_idle(w)
            _pump()
        assert offered and failures
        runs = sorted(p for p in (tmp / "runs").iterdir() if p.name.startswith("eder1994_"))
        assert len(runs) == 2 and w._last_run_dir == runs[1]
        summary = json.loads((runs[1] / "run_summary.json").read_text())
        assert summary["resumed_from"] == str(runs[0])
        assert (runs[1] / "eder1994_extracted.csv").read_text() == COMMITTED.read_text()
        w.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All resume window tests passed.")
    APP.processEvents()
