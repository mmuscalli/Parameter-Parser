"""
Offline tests for resume and rebuild (W1, 2026-11-11): a run's saved answers reused by a new run in a new folder.
Uses the eder1994 replay (no API calls).

Run with: python tests/test_resume.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client, errors, resume  # noqa: E402
from parameter_extractor.pipeline import run_pipeline  # noqa: E402
from test_pipeline_offline import PDF, REPLAY_DIR, _config, _have_inputs, _replay_send  # noqa: E402

COMMITTED = REPLAY_DIR / "eder1994_auto_extracted.csv"


def _asking(log: list, fail_on: str = ""):
    """A replay that records which answer formats were asked for (and fails on one, like a dropped network)."""
    def send(ctx, **kw):
        name = kw["response_model"].__name__
        log.append(name)
        if name == fail_on:
            raise errors.NetworkError()
        return _replay_send(ctx, **kw)
    return send


def _settled(folder: Path, timeout: float = 30.0) -> None:
    """Steps in flight when another step failed finish in the background (pipeline._collect) and save their
    answers a moment later: wait for the pipeline's worker threads to end, as a person reading the error would."""
    import threading
    import time
    end = time.time() + timeout
    while time.time() < end and any(t.is_alive() and t.name.startswith(("stage", "queue"))
                                    for t in threading.enumerate()):
        time.sleep(0.1)


def _no_send(ctx, **kw):
    raise AssertionError(f"asked the model for {kw['response_model'].__name__}")


def _finished(out: Path):
    with patch.object(api_client, "_send", _replay_send):
        return run_pipeline(PDF, _config(out))


def _files(folder: Path) -> dict:
    return {p.relative_to(folder): p.stat().st_mtime for p in folder.rglob("*") if p.is_file()}


def test_rebuild_asks_nothing_and_reproduces_the_dataset():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        first = _finished(Path(tmp))
        before = _files(first.run_dir)
        with patch.object(api_client, "_send", _no_send):
            again = resume.resume_run(first.run_dir, _config(Path(tmp)), rebuild=True)
        assert again.run_dir != first.run_dir and again.run_dir.parent == first.run_dir.parent
        assert again.csv_path.read_text() == first.csv_path.read_text() == COMMITTED.read_text()
        assert _files(first.run_dir) == before                      # the old folder is never written to
        summary = json.loads((again.run_dir / "run_summary.json").read_text())
        assert summary["resumed_from"] == str(first.run_dir) and summary["rebuilt"] is True
        assert summary["reused_steps"] and summary["estimated_cost_usd"] == 0
        assert all(u.reused and u.cost_usd == 0 for u in again.usage)
        audit = json.loads((again.run_dir / "chemistry.audit.json").read_text())
        assert audit["reused_from"] == str(first.run_dir) and audit["request_changed"] is False
        reuse = [f.message for f in again.paper_flags if f.kind == "reused_answer"]
        assert len(reuse) == 1 and reuse[0].startswith("Rebuilt from the earlier run") and "nothing was asked" in reuse[0]


def test_resume_after_a_failure_asks_only_the_missing_step():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        failed_log = []
        with patch.object(api_client, "_send", _asking(failed_log, fail_on="ChemistryExtraction")):
            try:
                run_pipeline(PDF, _config(Path(tmp)))
                raise AssertionError("the run should have failed")
            except errors.PipelineError:
                pass
        old = next(Path(tmp).iterdir())
        _settled(old)
        assert (old / resume.CONFIG_FILE).is_file() and not (old / "run_summary.json").is_file()
        assert not (old / "chemistry.output.json").is_file()
        # steps that hadn't started when chemistry failed were cancelled (which ones depends on timing): resume asks
        # for exactly the steps without a saved answer, and nothing else
        saved = {p.name[: -len(".output.json")] for p in old.glob("*.output.json")}
        assert {"structure_planner", "metadata"} <= saved and "chemistry" not in saved
        log = []
        with patch.object(api_client, "_send", _asking(log)):
            again = resume.resume_run(old, _config(Path(tmp)))
        asked = {u.stage for u in again.usage if not u.reused}
        reused = {u.stage for u in again.usage if u.reused}
        assert "chemistry" in asked and reused == saved and not asked & saved, (asked, saved)
        assert "ChemistryExtraction" in log and "StructurePlan" not in log and "PaperMetadata" not in log
        assert again.csv_path.read_text() == COMMITTED.read_text()
        reuse = [f.message for f in again.paper_flags if f.kind == "reused_answer"]
        assert reuse and reuse[0].startswith("Resumed from") and "asked again:" in reuse[0] and "chemistry" in reuse[0]


def test_audits_from_before_fingerprints_still_match():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        first = _finished(Path(tmp))
        for audit in first.run_dir.glob("*.audit.json"):          # as an older version wrote them
            d = json.loads(audit.read_text())
            d.pop("request_fingerprint", None)
            audit.write_text(json.dumps(d))
        with patch.object(api_client, "_send", _no_send):
            again = resume.resume_run(first.run_dir, _config(Path(tmp)))
        assert again.csv_path.read_text() == COMMITTED.read_text()


def test_a_changed_request_is_asked_again_on_resume_and_flagged_on_rebuild():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        first = _finished(Path(tmp))
        audit = first.run_dir / "metadata.audit.json"               # as if the step's prompt had changed since
        d = json.loads(audit.read_text())
        d["request_fingerprint"] = "0" * 64
        audit.write_text(json.dumps(d))
        log = []
        with patch.object(api_client, "_send", _asking(log)):
            resume.resume_run(first.run_dir, _config(Path(tmp)))
        assert log == ["PaperMetadata"], log
        with patch.object(api_client, "_send", _no_send):
            rebuilt = resume.resume_run(first.run_dir, _config(Path(tmp)), rebuild=True)
        changed = [f.message for f in rebuilt.paper_flags if f.kind == "reused_answer" and "has changed" in f.message]
        assert changed and "metadata" in changed[0]


def test_rebuild_stops_when_a_step_has_no_saved_answer():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        first = _finished(Path(tmp))
        (first.run_dir / "experimental_conditions.output.json").unlink()
        with patch.object(api_client, "_send", _no_send):
            try:
                resume.resume_run(first.run_dir, _config(Path(tmp)), rebuild=True)
                raise AssertionError("should have stopped")
            except errors.PipelineError as e:
                assert "experimental_conditions" in str(e) and "Resume" in str(e)
        _settled(Path(tmp))                                       # the other steps finish in the background


def test_the_old_settings_are_used_and_the_key_is_the_current_one():
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp) / "old_run"
        old.mkdir()
        saved = _config(Path("/elsewhere"), pack="exoplanets", passes=3, model_profile="economy").to_public_dict()
        (old / resume.CONFIG_FILE).write_text(json.dumps({"item": "paper.pdf", "config": saved}))
        base = _config(Path(tmp) / "out")
        config = resume.config_for(old, base)
        assert (config.pack, config.passes, config.model_profile) == ("exoplanets", 3, "economy")
        assert config.api_key == base.api_key and config.output_dir == base.output_dir
        assert config.resume_from == old and not config.rebuild
        assert resume.original_item(old) == "paper.pdf"


def test_review_decisions_of_the_old_run_are_reused():
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp)
        (old / "new_variables.json").write_text(json.dumps({"decisions": [
            {"alias_name": "parameter:stirring", "kind": "parameter", "action": "new", "column": "stirring",
             "remember": False, "value_type": ""}]}))
        decided = SimpleNamespace(kind="parameter", alias_name="parameter:stirring")
        new = SimpleNamespace(kind="parameter", alias_name="parameter:light")
        asked = []
        review = resume.review_with_saved(old, lambda groups, unfound, reg: asked.append(groups) or [])
        out = review([decided, new], [], None)
        assert [d.column for d in out] == ["stirring"] and asked == [[new]]     # only the new one is asked
        assert [d.column for d in resume.review_with_saved(old)([decided, new], [], None)] == ["stirring"]


def test_a_stopped_queue_resumes_into_a_new_queue_folder():
    if not _have_inputs():
        return
    from parameter_extractor.paper_queue import run_queue
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(api_client, "_send", _asking([], fail_on="ChemistryExtraction")):
            old_queue = run_queue([PDF], _config(Path(tmp)))
        assert old_queue.papers[0].status == "failed" and (old_queue.out_dir / "queue.json").is_file()
        _settled(old_queue.papers[0].extraction.ctx.run_dir)
        log = []
        with patch.object(api_client, "_send", _asking(log)):
            queue = run_queue([], _config(Path(tmp)), resume_from=old_queue.out_dir)
        assert queue.out_dir != old_queue.out_dir and "ChemistryExtraction" in log and "StructurePlan" not in log, log
        paper = queue.papers[0]
        assert paper.status == "finished" and paper.prefix == "001" and paper.result.csv_path.read_text() == \
            COMMITTED.read_text()
        assert json.loads((queue.out_dir / "queue.json").read_text())["resumed_from"] == str(old_queue.out_dir)
        # an older queue folder (no queue.json): its papers.csv, else its paper folders
        (queue.out_dir / "queue.json").unlink()
        listed = resume.queue_papers(queue.out_dir)
        assert [p["prefix"] for p in listed] == ["001"] and listed[0]["run_dir"] == paper.result.run_dir
        (queue.out_dir / "papers.csv").unlink()
        assert resume.queue_papers(queue.out_dir)[0]["item"] == str(PDF)
        with patch.object(api_client, "_send", _no_send):
            rebuilt = run_queue([], _config(Path(tmp)), resume_from=queue.out_dir, rebuild=True)
        assert rebuilt.papers[0].status == "finished"


def test_command_line_rebuild_writes_next_to_the_old_folder():
    if not _have_inputs():
        return
    from parameter_extractor import cli
    with tempfile.TemporaryDirectory() as tmp:
        first = _finished(Path(tmp))
        argv = ["parameter-extract", "--rebuild", str(first.run_dir), "--no-pubchem"]
        with patch.object(api_client, "_send", _no_send), patch.object(sys, "argv", argv), \
                patch("parameter_extractor.registry.default_registry_path", lambda: Path(tmp) / "registry.json"):
            assert cli.main() == 0
        made = sorted(p for p in Path(tmp).iterdir() if (p / "run_summary.json").is_file() and p != first.run_dir)
        assert len(made) == 1, made
        assert json.loads((made[0] / "run_summary.json").read_text())["rebuilt"] is True


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All resume / rebuild tests passed.")
