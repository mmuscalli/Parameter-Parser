"""
Offline tests: wet-dry cycling fields (per-set cycle conditions into the app's
standard wet/dry columns; cycle_number / cycle_duration_hr were removed, 2026-10-22) and
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
    return s


WET_DRY = WetDryConditions(parameters=[
    CycleParameter(set_label="", parameter="wet_phase_duration_hr", value=20, quote="20 h wet", source="Methods",
                   confidence="high"),
    CycleParameter(set_label="", parameter="dry_phase_temperature_C", value=130, quote="dried at 130 C",
                   source="Methods", confidence="high"),
    CycleParameter(set_label="", parameter="wet_phase_relative_humidity_pct", value=70, quote="70% RH",
                   source="Methods", confidence="medium"),
])


def _run(tmp: Path, structure: StructurePlan, wet_dry_calls: list):
    real_stage = pipeline.run_optional_stage

    def fake_wet_dry(ctx, spec, text, struct, table_images=None):
        if spec.name != "wet_dry":                 # the conditions stage: replayed as usual
            return real_stage(ctx, spec, text, struct, table_images)
        wet_dry_calls.append(struct.experiment_sets[0].set_label)
        return WET_DRY
    original_send = _replay_send

    def send(ctx, **kw):                       # replay, but with the modified structure plan
        resp = original_send(ctx, **kw)
        if kw["response_model"] is StructurePlan:
            resp.parsed_output = structure
        return resp
    with patch.object(api_client, "_send", send), patch.object(pipeline, "run_optional_stage", fake_wet_dry):
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
        n_template = 208
        # standard columns straight after the template block, then provenance; only filled ones
        assert header[n_template:n_template + 3] == ["wet_phase_duration_hr", "wet_phase_relative_humidity_pct",
                                                     "dry_phase_temperature_C"]
        assert "cycle_number" not in header and "cycle_duration_hr" not in header
        assert header[-1] == "original_data_reference"
        set1 = [r for r in rows if r["set_id"] == "001001"]
        assert all(r["wet_phase_duration_hr"] == "20.0" and r["dry_phase_temperature_C"] == "130.0"
                   and r["wet_phase_relative_humidity_pct"] == "70.0" for r in set1)
        assert all(r["original_data_reference"] == REF for r in set1)
        others = [r for r in rows if r["set_id"] != "001001"]
        assert all(r["wet_phase_duration_hr"] == r["original_data_reference"] == "" for r in others)

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
    assert rows[0].provenance["original_data_reference"].origin.startswith("Fig. 5")


def test_assumed_values_are_never_written_automatically():
    """truman2024's "perhaps 130 C": a value the paper doesn't state is flagged and offered
    in the review -- written only if the user chooses, and never remembered."""
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    from parameter_extractor.ingestion.new_variables import VariableDecision
    from parameter_extractor.schemas.methodology import SetOverride
    structure = _cycling_structure()
    set2 = structure.experiment_sets[1].set_label
    wet_dry = WetDryConditions(parameters=WET_DRY.parameters + [
        CycleParameter(set_label="", parameter="dry_phase_duration_hr", value=4, basis="assumed",
                       quote="", source="", confidence="low")])
    seen = {}

    def review(groups, unfound, registry):
        seen["groups"] = [(g.kind, g.alias_name) for g in groups]
        return [VariableDecision(f"initial_temperature_C @ {set2}", "assumed_value", "existing_column",
                                 "initial_temperature_C", remember=True)]

    def add_overrides(ex):
        ex.methodology.per_set_overrides = [o for o in ex.methodology.per_set_overrides if o.set_label != set2]
        ex.methodology.per_set_overrides += [
            SetOverride(set_label=set2, field_name="initial_temperature_C", value=130, basis="assumed",
                        confidence="low", quote="conditions not documented; perhaps 130 C", source="Table 2"),
            SetOverride(set_label=set2, field_name="initial_pH", value=2.5, basis="stated",
                        confidence="medium", quote="pH 2.5", source="Methods")]

    def send(ctx, **kw):
        resp = _replay_send(ctx, **kw)
        if kw["response_model"] is StructurePlan:
            resp.parsed_output = structure
        return resp

    real_stage = pipeline.run_optional_stage
    for decide in (None, review):
        with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", send), \
                patch.object(pipeline, "run_optional_stage",
                             lambda ctx, spec, *a: wet_dry if spec.name == "wet_dry" else real_stage(ctx, spec, *a)):
            config = RunConfig.from_settings(api_key="x", output_dir=Path(tmp), registry_path=Path(tmp) / "r.json")
            ex = pipeline.extract(PDF, config)
            add_overrides(ex)
            result = pipeline.finish(ex, review=decide)
            with open(result.csv_path, newline="") as f:
                rows = list(csv.DictReader(f))
            set2_rows = [r for r in rows if r["set_id"] == "001002"]
            set1_rows = [r for r in rows if r["set_id"] == "001001"]
            assert all(r.get("dry_phase_duration_hr", "") == "" for r in set1_rows)   # assumed: not written
            assert all(r["initial_pH"] == "2.5" for r in set2_rows)                  # stated: written...
            assert any(f.kind == "low_confidence" and "initial_pH" in f.message for f in result.paper_flags)  # ...flagged
            assumed_flags = [f for f in result.paper_flags if f.kind == "assumed_value"]
            if decide is None:
                # the assumed 130 C is never written (the paper's own per-set temperature may be)
                assert all(r["initial_temperature_C"] != "130.0" for r in set2_rows)
                assert len(assumed_flags) == 2 and all("NOT written" in f.message for f in assumed_flags)
            else:
                assert ("assumed_value", f"initial_temperature_C @ {set2}") in seen["groups"]
                assert ("assumed_value", "dry_phase_duration_hr @ " + structure.experiment_sets[0].set_label) in seen["groups"]
                assert all(r["initial_temperature_C"] == "130.0" for r in set2_rows)   # user chose to include it
                assert any("included because you chose" in f.message for f in assumed_flags)
                assert not (Path(tmp) / "r.json").exists()          # never remembered, even with remember=True


def test_review_window_never_auto_includes_assumed_values():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.variable_review import VariableReviewDialog
    from parameter_extractor.ingestion.new_variables import VariableGroup
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.variables import NewVariable
    g = VariableGroup(kind="assumed_value", name="initial_temperature_C", alias_name="t @ s",
                      proposed_column="initial_temperature_C",
                      values=[NewVariable(kind="assumed_value", name="initial_temperature_C", value=130,
                                          set_label="s", origin="methodology (assumed)")])
    dlg = VariableReviewDialog([g], [], VariableRegistry(None))
    dlg._accept_suggestions()
    assert dlg.decisions()[0].action == "ignore"
    assert not dlg.remember_boxes[0].isChecked()
    assert dlg.table.item(dlg._table_row[0], 1).text().startswith("ASSUMED")
    assert dlg.category_headers()[0].startswith("Assumed values")


def test_standard_columns_file():
    """The pack's own columns beyond the template: the conditions stage's uncertainties and other
    estimates, then the wet-dry stage's (cycle number and duration included -- not in the main
    vocabulary, 2026-10-22), in spec order."""
    cols = standard_columns()
    assert cols[-7:] == ["cycle_number", "cycle_duration_hr", "wet_phase_temperature_C", "wet_phase_duration_hr",
                         "wet_phase_relative_humidity_pct", "dry_phase_temperature_C", "dry_phase_duration_hr"]
    # the shared columns every pack gets come first (the metadata ones are in this pack's template)
    assert cols[:3] == ["paper_arxiv_id", "initial_pressure_bar_err_plus", "initial_pressure_bar_err_minus"]
    assert "initial_temperature_C_alt1_method" in cols and "solvent_name" not in cols     # template columns aren't


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All wet-dry / cited-data tests passed.")
