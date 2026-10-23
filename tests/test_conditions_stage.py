"""
Offline tests for the prebiotic pack's configurable experimental-conditions stage
(was the built-in methodology step, 2026-10-22), water types, results-only-from-
tables/figures and the "no results" flag. Replays eder1994's recorded responses
(its methodology answer converted by stages/conditions_migration.py); no API calls.

Run with: python tests/test_conditions_stage.py
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client, pipeline
from parameter_extractor.calculators.water import water_type
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.stages.optional import load_specs, optional_values
from test_pipeline_offline import PDF, REPLAY_DIR, _replay_send


def test_water_types():
    named = {"water": ("distilled water", True), "H2O": ("distilled water", True), "Water": ("distilled water", True),
             "aqueous": ("distilled water", True), "distilled water": ("distilled water", False),
             "deionised water": ("deionized water", False), "DI water": ("deionized water", False),
             "Milli-Q water": ("Milli-Q water", False), "MilliQ H2O": ("Milli-Q water", False),
             "ultra-pure water (18.2 MΩ cm)": ("ultrapure water", False), "nanopure water": ("nanopure water", False),
             "tap water": ("tap water", False), "doubly distilled water": ("double-distilled water", False)}
    for given, expected in named.items():
        assert water_type(given) == expected, (given, water_type(given))
    for other in ("ethanol", "water/ethanol 1:1", "", "formamide"):
        assert water_type(other) == (None, False), other


def test_conditions_spec():
    spec = load_specs()["experimental_conditions"]
    assert spec.per == "sample" and spec.open_ended and spec.alternatives and spec.trigger.always
    Item, Result = spec.models()
    assert "other" in Result.model_fields
    structure = StructurePlan.model_validate_json((REPLAY_DIR / "structure_planner.output.json").read_text())
    first = structure.experiment_sets[0].set_label
    answer = Result.model_validate({"rows": [
        {"set": "", "values": [{"col": "experiment_type", "v": 0, "u": "", "txt": "batch", "q": "sealed", "src": "Exp.",
                                "c": "high"},
                               {"col": "solution_type", "v": 0, "u": "", "txt": "aqueous", "q": "in water",
                                "src": "Exp.", "c": "high"},
                               {"col": "initial_temperature_C", "v": 354.15, "u": "K", "ep": 1, "em": -1, "q": "354 K",
                                "src": "Table 1", "c": "high"}]},
        {"set": first, "values": [{"col": "initial_pH", "v": 7.2, "u": "", "q": "pH 7.2", "src": "Table 1",
                                   "c": "medium"}]}],
        "other": [{"nm": "stirring", "v": "none", "q": "without stirring", "src": "Exp.", "c": "high"}], "notes": ""})
    problems = []
    values = optional_values(spec, answer, structure, problems)
    assert values[(first, "", "experiment_type")].value == "Batch"                 # matched to its choices
    assert not any(k[2] == "solution_type" for k in values)                        # 'aqueous' isn't Wet/Dry
    assert any("solution_type 'aqueous'" in p and "Wet, Dry" in p for p in problems)
    assert abs(values[(first, "", "initial_temperature_C")].value - 81.0) < 1e-6     # K -> °C
    assert values[(first, "", "initial_temperature_C_err_plus")].value == 1
    assert values[(first, "", "initial_pH")].value == 7.2
    wet_dry = load_specs()["wet_dry"]
    _, WetDry = wet_dry.models()
    cycles = WetDry.model_validate({"rows": [{"set": first, "sample": "s1", "values": [
        {"col": "cycle_number", "v": 3, "u": "", "q": "Cycle 3", "src": "Table 1", "c": "high"}]}]})
    v = optional_values(wet_dry, cycles, structure)[(first, "s1", "cycle_number")].value
    assert v == 3 and isinstance(v, int)                                            # a count, not 3.0


def _run(tmp, structure=None, digitized=()):
    def send(ctx, **kw):
        resp = _replay_send(ctx, **kw)
        if structure is not None and kw["response_model"] is StructurePlan:
            resp.parsed_output = structure
        return resp
    with patch.object(api_client, "_send", send):
        ex = pipeline.extract(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp)))
        return ex, pipeline.finish(ex, list(digitized))


def test_water_and_other_conditions_in_a_run():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp:
        ex, result = _run(tmp)
        assert all(r.solvent_name == "distilled water" for r in result.rows)
        assert result.rows[0].provenance["solvent_name"].origin.endswith("assumed distilled")
        water = [f for f in result.paper_flags if f.kind == "assumed_default"]
        assert len(water) == 1 and "42 row(s)" in water[0].message and "deionized" in water[0].message
        assert not [f for f in result.paper_flags if f.kind == "no_results"]           # Table 1/2 have results
        # the conditions stage's open-ended `other` reach the review like methodology's did (eder1994's
        # recording predates them: add one)
        spec = load_specs()["experimental_conditions"]
        _, Result = spec.models()
        ex.optional = {"experimental_conditions": (spec, Result.model_validate({"rows": [], "other": [
            {"nm": "stirring", "v": "none", "q": "without stirring", "src": "Exp.", "c": "high"}]}))}
        pipeline._collect_other_parameters(ex)
        assert [(p.name, p.value) for p in ex.methodology.other_parameters][-1] == ("stirring", "none")


def test_no_results_flag_and_figure_rows_without_sets():
    """A paper whose results are all in figures: no sets planned; nothing digitized -> flagged; one
    figure digitized -> its rows get the paper-wide conditions and no flag."""
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    empty = StructurePlan.model_validate_json((REPLAY_DIR / "structure_planner.output.json").read_text())
    empty.experiment_sets, empty.total_planned_rows = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        ex, result = _run(tmp, empty)
        assert result.rows == []
        flags = [f for f in result.paper_flags if f.kind == "no_results"]
        assert len(flags) == 1 and "tables" in flags[0].message and "digitize" in flags[0].message
        view = pipeline._paper_wide_methodology(ex)                   # what a digitized figure would get
        assert view.experiment_type.value == "Batch" and view.experiment_type.status == "found"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All conditions-stage tests passed.")
