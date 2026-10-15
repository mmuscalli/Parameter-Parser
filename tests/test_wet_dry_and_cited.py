"""
Offline tests: wet-dry cycling fields (per-sample cycle_number, per-set cycle
conditions into cycle_duration_hr + the app's standard wet/dry columns) and
data cited from other publications (original_data_reference + warning).
No API calls.

Run with: python tests/test_wet_dry_and_cited.py
"""
import csv
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client, pipeline
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.ingestion.figure_rows import build_figure_rows
from parameter_extractor.registry import standard_columns
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.schemas.wet_dry import CycleParameter, WetDryConditions
from test_figures import _figure, _meta_and_method
from test_pipeline_offline import PDF, REPLAY_DIR, _replay_send

REF = "Rodriguez-Garcia et al. 2015, Nat. Commun. 6:8385 (ref. 12)"


def _cycling_structure() -> StructurePlan:
    """eder1994's plan with set 1 turned into a cited wet-dry cycling set."""
    s = StructurePlan.model_validate_json((REPLAY_DIR / "structure_planner.output.json").read_text())
    s1 = s.experiment_sets[0]
    s1.set_type, s1.data_source = "Evaporation Cycle", REF
    for i, sample in enumerate(s1.samples, start=1):
        sample.cycle_number = i
    return s


WET_DRY = WetDryConditions(parameters=[
    CycleParameter(set_label="", parameter="cycle_duration_hr", value=24, quote="24 h cycles", source="Methods",
                   confidence="high"),
    CycleParameter(set_label="", parameter="dry_phase_temperature_C", value=130, quote="dried at 130 C",
                   source="Methods", confidence="high"),
    CycleParameter(set_label="", parameter="wet_phase_relative_humidity_pct", value=70, quote="70% RH",
                   source="Methods", confidence="medium"),
])


def _run(tmp: Path, structure: StructurePlan, wet_dry_calls: list):
    def fake_wet_dry(ctx, text, struct):
        wet_dry_calls.append(struct.experiment_sets[0].set_label)
        return WET_DRY
    original_send = _replay_send

    def send(ctx, **kw):                       # replay, but with the modified structure plan
        resp = original_send(ctx, **kw)
        if kw["response_model"] is StructurePlan:
            resp.parsed_output = structure
        return resp
    with patch.object(api_client, "_send", send), patch.object(pipeline, "run_wet_dry", fake_wet_dry):
        return pipeline.run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=tmp))


def test_cycling_fields_and_cited_data():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    calls = []
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp), _cycling_structure(), calls)
        assert len(calls) == 1, "wet-dry step should run once when there are cycling sets"
        with open(result.csv_path, newline="") as f:
            reader = csv.DictReader(f)
            header, rows = reader.fieldnames, list(reader)
        n_template = 280
        # standard columns straight after the template block, then provenance; only filled ones
        assert header[n_template:n_template + 2] == ["wet_phase_relative_humidity_pct", "dry_phase_temperature_C"]
        assert header[-1] == "original_data_reference"
        set1 = [r for r in rows if r["set_id"] == "001001"]
        assert [r["cycle_number"] for r in set1] == [str(i) for i in range(1, len(set1) + 1)]
        assert all(r["cycle_duration_hr"] == "24.0" and r["dry_phase_temperature_C"] == "130.0"
                   and r["wet_phase_relative_humidity_pct"] == "70.0" for r in set1)
        assert all(r["original_data_reference"] == REF for r in set1)
        others = [r for r in rows if r["set_id"] != "001001"]
        assert all(r["cycle_number"] == r["cycle_duration_hr"] == r["original_data_reference"] == "" for r in others)

        cited = [f for f in result.paper_flags if f.kind == "cited_data"]
        assert len(cited) == 1 and REF in cited[0].message
        obs = {(o["full_id"], o["column"]): o for o in csv.DictReader(open(result.observations_path))}
        rh = obs[("001001001", "wet_phase_relative_humidity_pct")]
        assert (rh["unit"], rh["origin"], rh["confidence"]) == ("%", "wet-dry cycling", "medium")


def test_no_cycling_no_extra_step_and_unchanged_csv():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    calls = []
    structure = StructurePlan.model_validate_json((REPLAY_DIR / "structure_planner.output.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(Path(tmp), structure, calls)
        assert calls == [] and [u.stage for u in result.usage].count("wet_dry") == 0
        assert result.csv_path.read_text() == (REPLAY_DIR / "eder1994_auto_extracted.csv").read_text()


def test_cited_figure():
    meta, meth = _meta_and_method()
    fig = _figure()
    fig.data_source = "Campbell et al. 2019, Nat. Commun. 10:4508 (ref. 15)"
    rows, _, _ = build_figure_rows([fig], meta, meth, "001", 14, 43)
    assert all(r.original_data_reference == fig.data_source for r in rows)
    assert rows[0].provenance["original_data_reference"].origin == "Fig. 5"


def test_standard_columns_file():
    assert standard_columns() == ["wet_phase_temperature_C", "wet_phase_duration_hr",
                                  "wet_phase_relative_humidity_pct", "dry_phase_temperature_C",
                                  "dry_phase_duration_hr"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All wet-dry / cited-data tests passed.")
