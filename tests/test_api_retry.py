"""
Offline tests for answers that break off (aa57186-25, 2026-10-21: the system and
discovery step ran on for 7 minutes and 112K characters for a two-planet system
until it was cut off, failing the run). Now: each optional stage has an output
budget sized to what it can need, a broken or cut-off answer is retried once
with the full budget, the broken text is kept for diagnosis, and a second
failure says to run the paper again. Also: values the model marked "assumed"
keep their text (discoverymethod 'Transit') and their row. Replays nielsen2019's
recorded responses; no API calls.

Run with: python tests/test_api_retry.py
"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError

from parameter_extractor import api_client, errors, packs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pipeline import run_pipeline
from test_pipeline_offline import make_replay

PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Nielsen2019" / "nielsen2019.pdf"
REF = ROOT / "runs" / "nielsen2019_auto"


def _flaky(fail_times: int, how: str):
    """A replay whose system-and-discovery answer breaks off `fail_times` times first."""
    replay, seen = make_replay(REF), []

    def send(ctx, **kw):
        name = kw["response_model"].__name__
        if name == "SystemAndDiscoveryResult":
            seen.append(api_client._streamed.max_tokens)
            if len(seen) <= fail_times:
                if how == "cut off":
                    return SimpleNamespace(id="x", stop_reason="max_tokens", parsed_output=None, content=[],
                                           usage=SimpleNamespace(input_tokens=1000, output_tokens=9000))
                api_client._streamed.text = '{"parameters": [{"set_label": "HD 1397", "note": "' + "ab" * 50
                kw["response_model"].model_validate_json(api_client._streamed.text)      # raises
        return replay(ctx, **kw)
    return send, seen


def test_a_broken_answer_is_retried_once():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    try:
        for how in ("cut off", "broken JSON"):
            send, seen = _flaky(1, how)
            with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", send):
                result = run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp),
                                                                   pack="exoplanets"))
                assert result.csv_path.read_text() == (REF / "nielsen2019_extracted.csv").read_text()
                # first try: the stage's budget (1 system + 1 planet, 9 parameters); retry: the full maximum
                assert seen == [4000 + 250 * 2 * 9, RunConfig.from_settings(api_key="x").max_tokens], seen
                stages = [u.stage for u in result.usage]
                if how == "cut off":            # the cut-off try was paid for: it's in the usage
                    assert stages.count("system_and_discovery") == 2
                else:                           # the broken text is kept for diagnosis
                    kept = result.run_dir / "system_and_discovery.failed_output.txt"
                    assert kept.read_text().startswith('{"parameters"')
    finally:
        packs.activate("prebiotic_chemistry")


def test_twice_broken_says_run_again():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    try:
        send, seen = _flaky(2, "broken JSON")
        # stages still in flight finish in the background after the failure: tolerate their late files
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, patch.object(api_client, "_send", send):
            try:
                run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp), pack="exoplanets"))
            except errors.MalformedOutputError as e:
                assert "running the paper again usually works" in str(e) and "maximum output tokens" not in str(e)
            else:
                raise AssertionError("two broken answers must fail the run")
        assert len(seen) == 2
    finally:
        packs.activate("prebiotic_chemistry")


def test_assumed_text_values_keep_their_text_and_row():
    from parameter_extractor.ingestion.new_variables import collect_new_variables
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    from parameter_extractor.schemas.methodology import empty_methodology
    from parameter_extractor.schemas.structure_plan import StructurePlan
    from parameter_extractor.stages.optional import load_specs
    packs.activate("exoplanets")
    try:
        spec = load_specs()["system_and_discovery"]
        _, Result = spec.models()
        result = Result.model_validate({"parameters": [{
            "set_label": "TOI-3862", "sample_label": "TOI-3862 b", "parameter": "discoverymethod", "value": 0,
            "text": "Transit", "basis": "assumed", "quote": "TESS transiting planet candidate", "source": "Abstract",
            "confidence": "medium"}]})
        structure = StructurePlan.model_validate({"paper_id": "p", "total_planned_rows": 2, "experiment_sets": [
            {"set_label": "TOI-3862", "set_type": "Independent", "varying_condition_summary": "",
             "source_table_or_section": "", "data_source": "",
             "samples": [{"sample_label": "TOI-3862 b", "source": ""}, {"sample_label": "TOI-3862 c", "source": ""}]}]})
        index = ({"TOI-3862": ["001001001", "001001002"]},
                 {("TOI-3862", "TOI-3862 b"): "001001001", ("TOI-3862", "TOI-3862 c"): "001001002"},
                 ["001001001", "001001002"])
        found = collect_new_variables(empty_methodology("p"), ChemistryExtraction(paper_id="p", solutes=[]),
                                      index=index, structure=structure, optional=[(spec, result)])
        v = found[0]
        assert (v.kind, v.value, v.value_text, v.row_ids) == ("assumed_value", None, "Transit", ["001001001"])
    finally:
        packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All retry tests passed.")
