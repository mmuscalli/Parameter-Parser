"""
Offline tests for optional stages defined as data (stages/specs/*.json): the
wet-dry spec builds the same models the hand-written stage had, and a new
stage needs only a spec -- trigger, schema, prompt, per-set values and
standard columns all follow from it. No API calls.

Run with: python tests/test_optional_stages.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor.registry import standard_columns
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.stages.optional import StageSpec, load_specs, optional_values, triggered_specs
from test_pipeline_offline import REPLAY_DIR

STRUCTURE = StructurePlan.model_validate_json((REPLAY_DIR / "structure_planner.output.json").read_text())


def test_wet_dry_spec():
    spec = load_specs()["wet_dry"]
    Item, Result = spec.models()
    assert Result.__name__ == "WetDryConditions"                     # what replays look up
    assert list(Item.model_fields) == ["set_label", "sample_label", "parameter", "value", "unit", "basis", "quote",
                                       "source", "confidence", "note"]          # per sample (cycle_number)
    assert not spec.triggered(STRUCTURE, "")                          # eder1994: no cycling
    truman = StructurePlan.model_validate_json(
        (ROOT / "runs" / "truman2024_auto" / "structure_planner.output.json").read_text())
    assert spec.triggered(truman, "") and len(spec.target_sets(truman)) == 4
    # the wet/dry phase columns are standard columns, in spec order, after any listed ones
    cols = standard_columns()
    assert cols[-7:] == ["cycle_number", "cycle_duration_hr", "wet_phase_temperature_C", "wet_phase_duration_hr",
                         "wet_phase_relative_humidity_pct", "dry_phase_temperature_C", "dry_phase_duration_hr"]
    # cycle number / duration: the wet-dry stage's own columns, not the main vocabulary (2026-10-22)
    from parameter_extractor import packs
    assert "cycle_number" not in packs.current().template_columns


def test_a_new_stage_needs_only_a_spec():
    spec = StageSpec.model_validate({
        "name": "uv_irradiation", "label": "UV irradiation conditions", "set_word": "irradiated",
        "trigger": {"keywords": ["UV", "ultraviolet"]},
        "intro": "This paper irradiates samples with UV light.",
        "parameters": [{"column": "uv_wavelength_nm", "unit": "nm", "description": "peak wavelength"},
                       {"column": "uv_flux_W_m2", "unit": "W m-2", "description": "irradiance at the sample"}],
        "rules": ["A lamp's nominal power is not the irradiance at the sample."]})
    assert spec.model_name == "UvIrradiationResult" and spec.origin_label == "uv irradiation conditions"
    assert not spec.triggered(STRUCTURE, "heated at 80 C")
    assert spec.triggered(STRUCTURE, "samples were exposed to ultraviolet light (254 nm)")
    assert not spec.triggered(STRUCTURE, "ultraviolets")                     # whole words only
    Item, Result = spec.models()
    prompt = spec.prompt(STRUCTURE, "PAPER")
    assert "- `uv_wavelength_nm` (nm): peak wavelength" in prompt and "nominal power" in prompt
    assert "every irradiated set" in prompt and "Return a UvIrradiationResult object." in prompt
    result = Result.model_validate({"parameters": [
        {"set_label": "", "parameter": "uv_wavelength_nm", "value": 254, "quote": "254 nm", "source": "Methods",
         "confidence": "high"},
        {"set_label": STRUCTURE.experiment_sets[0].set_label, "parameter": "uv_wavelength_nm", "value": 185,
         "quote": "185 nm", "source": "Table 1", "confidence": "high"},
        {"set_label": "", "parameter": "uv_flux_W_m2", "value": 5, "basis": "assumed", "quote": "", "source": "",
         "confidence": "low"}]})
    values = optional_values(spec, result, STRUCTURE)
    first, second = STRUCTURE.experiment_sets[0].set_label, STRUCTURE.experiment_sets[1].set_label
    assert values[(first, "", "uv_wavelength_nm")].value == 185                  # set-specific wins
    assert values[(second, "", "uv_wavelength_nm")].value == 254                 # keyword stage: every set
    assert not any(k[2] == "uv_flux_W_m2" for k in values)                  # assumed: left to the review
    # parameters are limited to the spec's columns: others (a pack dropped them, or a model slip) are
    # skipped, not written, and don't fail the step (2026-10-22)
    kept = Result.model_validate({"parameters": [
        {"set_label": "", "parameter": "not_a_column", "value": 1, "quote": "", "source": "", "confidence": "low"},
        {"set_label": "", "parameter": "uv_wavelength_nm", "value": 254, "quote": "", "source": "", "confidence": "low"}]})
    assert [v.parameter for v in kept.parameters] == ["uv_wavelength_nm"]


def test_user_choices():
    truman = StructurePlan.model_validate_json(
        (ROOT / "runs" / "truman2024_auto" / "structure_planner.output.json").read_text())
    names = lambda s, c=None: [x.name for x in triggered_specs(s, "", c)]
    assert names(truman) == ["experimental_conditions", "wet_dry"] and names(STRUCTURE) == ["experimental_conditions"]
    assert names(truman, {"wet_dry": "off"}) == ["experimental_conditions"]
    assert names(STRUCTURE, {"wet_dry": "on"}) == ["experimental_conditions", "wet_dry"]



def test_compact_answer_format():
    """The model answers in rows of values with short field names, empty fields left out (30% fewer
    output tokens); the code reads the usual names; old flat answers still load."""
    from parameter_extractor import packs
    from parameter_extractor.stages.optional import CORE_FIELDS, load_specs
    packs.activate("exoplanets")
    try:
        spec = load_specs()["planet_parameters"]
        Item, Result = spec.models()
        schema = Result.model_json_schema()
        item = schema["$defs"][f"{spec.model_name}Value"]
        assert item["required"] == CORE_FIELDS and "u" in CORE_FIELDS and "set_label" not in item["properties"]
        assert {"ep", "em", "lim", "mode", "meth", "n", "b"} <= set(item["properties"])
        row = schema["$defs"][f"{spec.model_name}Row"]
        assert row["required"] == ["set", "values"] and "sample" in row["properties"]
        assert set(schema["properties"]) == {"rows", "notes"}
        answer = Result.model_validate({"rows": [
            {"set": "HD 14067", "sample": "HD 14067 b [joint fit]", "values": [
                {"col": "pl_orbper", "v": 7.513, "u": "yr", "ep": 0.044, "em": -0.038, "q": "7.513", "src": "Table 4",
                 "c": "high"},
                {"col": "pl_orbincl", "v": 39, "mode": "i < 90 deg", "q": "39", "src": "Table 4", "c": "medium",
                 "b": "derived", "n": "from the prograde mode"}]},
            {"set": "HD 14067", "values": [{"col": "pl_rvamp", "v": 100.2, "q": "100.17", "src": "Table 3", "c": "high"}]}],
            "notes": ""})
        flat = answer.parameters
        assert [(v.set_label, v.sample_label, v.parameter) for v in flat] == [
            ("HD 14067", "HD 14067 b [joint fit]", "pl_orbper"), ("HD 14067", "HD 14067 b [joint fit]", "pl_orbincl"),
            ("HD 14067", "", "pl_rvamp")]
        assert (flat[0].unit, flat[0].err_plus, flat[1].mode, flat[1].basis, flat[2].note) == ("yr", 0.044, "i < 90 deg", "derived", "")
        assert Result.model_validate_json(answer.model_dump_json()).parameters == flat          # recordings replay
        old = Result.model_validate({"parameters": [{"set_label": "11 Com", "sample_label": "11 Com b",
                                                     "parameter": "pl_orbper", "value": 323.21, "quote": "323.21",
                                                     "source": "Table 3", "confidence": "high"}]})
        assert old.parameters[0].sample_label == "11 Com b"                                    # old flat format
    finally:
        packs.activate("prebiotic_chemistry")

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All optional-stage tests passed.")
