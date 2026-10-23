"""
Offline end-to-end test of pipeline.run_pipeline() -- no API calls, no cost.

api_client._send (the single network call) is replaced with a replay of the
saved model responses from runs/eder1994_auto/, so everything else runs for
real: PDF parsing, table rasterization, stage wiring, structured-output
handling, audit files, flattening, checks, progress events, run folders.
The replayed run must reproduce the committed eder1994_auto CSV exactly.

Needs eder1994.pdf at its usual place in the EORE Data Project folder;
skips the end-to-end tests otherwise.

Run with: python -m pytest tests/ -v   (or just: python tests/test_pipeline_offline.py)
"""
import json
import re
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client
from parameter_extractor import errors
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pipeline import run_pipeline

PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Initial Easy Papers" / "Eder1994" / "eder1994.pdf"
REPLAY_DIR = ROOT / "runs" / "eder1994_auto"
STAGE_FOR_MODEL = {"StructurePlan": "structure_planner", "PaperMetadata": "metadata",
                   "Methodology": "methodology", "ChemistryExtraction": "chemistry",
                   "WetDryConditions": "wet_dry", "TermSearch": "term_search"}


def make_replay(replay_dir: Path):
    """An api_client._send stand-in that returns the saved responses from a reference run."""
    def send(ctx, *, model, system_prompt, content, response_model, stop_reason="end_turn"):
        name = response_model.__name__        # optional stages: PlanetParametersResult -> planet_parameters
        stage = STAGE_FOR_MODEL.get(name) or re.sub(r"(?<!^)(?=[A-Z])", "_", name.removesuffix("Result")).lower()
        if stage == "experimental_conditions" and not (replay_dir / f"{stage}.output.json").is_file():
            # recorded before the methodology step became the experimental_conditions stage (2026-10-22)
            from parameter_extractor.stages.conditions_migration import conditions_from_methodology
            audit = json.loads((replay_dir / "methodology.audit.json").read_text())
            output = json.dumps(conditions_from_methodology(
                json.loads((replay_dir / "methodology.output.json").read_text())))
        else:
            audit = json.loads((replay_dir / f"{stage}.audit.json").read_text())
            output = (replay_dir / f"{stage}.output.json").read_text()
        return SimpleNamespace(
            id=f"replay-{stage}", stop_reason=stop_reason,
            parsed_output=response_model.model_validate_json(output),
            content=[SimpleNamespace(type="text", text=json.dumps(audit["raw_response"]))],
            usage=SimpleNamespace(input_tokens=audit["input_tokens"],
                                  output_tokens=audit["output_tokens"]),
        )
    return send


_replay_send = make_replay(REPLAY_DIR)


def _config(out: Path, **kw) -> RunConfig:
    return RunConfig.from_settings(api_key="replay-not-a-real-key", output_dir=out, **kw)


def _have_inputs() -> bool:
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}")
        return False
    return True


def test_replay_reproduces_committed_csv():
    if not _have_inputs():
        return
    events = []
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", _replay_send):
        result = run_pipeline(PDF, _config(Path(tmp)), on_progress=events.append)

        committed = (REPLAY_DIR / "eder1994_auto_extracted.csv").read_text()
        assert result.csv_path.read_text() == committed, "replayed CSV differs from committed run"
        assert len(result.rows) == 42

        # metadata runs alongside the structure step, then conditions and chemistry together;
        # each is reported as it finishes, so their order varies -- the step count doesn't
        steps = [e for e in events if e.stage != "parallel"]
        assert [e.step for e in steps] == [1, 2, 3, 4, 5, 6] and all(e.total_steps == 6 for e in events)
        assert [e.stage for e in steps][:2] == ["parse", "structure_planner"] and steps[-1].stage == "assemble"
        assert sorted(e.stage for e in steps[2:5]) == ["chemistry", "experimental_conditions", "metadata"]
        assert any(e.stage == "parallel" and "experimental conditions" in e.message for e in events)
        assert [u.stage for u in result.usage] == ["structure_planner", "metadata", "experimental_conditions",
                                               "chemistry"]

        audits = [json.loads((REPLAY_DIR / f"{s}.audit.json").read_text())
                  for s in STAGE_FOR_MODEL.values() if (REPLAY_DIR / f"{s}.audit.json").exists()]
        assert result.input_tokens == sum(a["input_tokens"] for a in audits)

        summary = json.loads((result.run_dir / "run_summary.json").read_text())
        assert "api_key" not in summary["config"] and "replay-not-a-real-key" not in json.dumps(summary)
        assert result.run_dir.name.startswith("eder1994_")
        assert (result.run_dir / "page_images").is_dir()
        assert {f.kind for f in result.paper_flags} == {"low_confidence", "derived_value", "assumed_default",
                                                          "identity_not_quoted"}   # + 'water' -> distilled   # + calculated totals
        # Table 2's unlabelled '2.50 mol dm-3 80 C' block (Ca2+ vs Ba2+ was settled by hand) and two unquoted
        # yields; the ion headers ('Na+ 3.33 mol dm-3') and bare table rows named by their column don't count
        unnamed = sorted(f.message.split(":")[0] for f in result.paper_flags if f.kind == "identity_not_quoted")
        assert unnamed == ["2peptide_Gly", "3peptide_Gly", "CaCl2"], unnamed
        total = next(f for f in result.paper_flags if f.kind == "derived_value")
        assert "total_sampled_peptides_yield calculated for 42 row(s)" in total.message


def test_runs_never_overwrite_each_other():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", _replay_send):
        a = run_pipeline(PDF, _config(Path(tmp)))
        b = run_pipeline(PDF, _config(Path(tmp)))
        assert a.run_dir != b.run_dir and a.csv_path.exists() and b.csv_path.exists()


def test_cancel_between_stages():
    if not _have_inputs():
        return
    cancel = threading.Event()

    def on_progress(event):
        if event.stage == "experimental_conditions":
            cancel.set()  # user presses cancel while metadata is running...

    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", _replay_send):
        try:
            run_pipeline(PDF, _config(Path(tmp)), on_progress=on_progress, cancel_event=cancel)
        except errors.RunCancelledError:
            pass  # ...and the run stops before the next stage starts
        else:
            raise AssertionError("expected RunCancelledError")


def test_refusal_and_truncation_become_named_errors():
    if not _have_inputs():
        return
    for stop_reason, expected in [("refusal", errors.ModelRefusedError),
                                  ("max_tokens", errors.OutputTruncatedError)]:
        send = lambda ctx, **kw: _replay_send(ctx, stop_reason=stop_reason, **kw)
        with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", send):
            try:
                run_pipeline(PDF, _config(Path(tmp)))
            except expected:
                pass
            else:
                raise AssertionError(f"stop_reason={stop_reason} should raise {expected.__name__}")


def test_missing_key_fails_before_creating_anything():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run_pipeline(PDF, RunConfig(api_key="", output_dir=Path(tmp)))
        except errors.ApiKeyMissingError:
            assert list(Path(tmp).iterdir()) == []
        else:
            raise AssertionError("expected ApiKeyMissingError")


def test_missing_pdf_is_a_readable_error():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run_pipeline(Path(tmp) / "nope.pdf", _config(Path(tmp)))
        except errors.PdfNotReadableError as e:
            assert "nope.pdf" in str(e)
        else:
            raise AssertionError("expected PdfNotReadableError")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All offline pipeline tests passed.")
