"""
The template pack (packs/_template/, 2026-11-05): hidden from every list, valid as it stands, and a pack created
from it (packs.create_pack) is a working research area -- found by the app, its example stage and rules used, one
paper run end to end with stand-in model answers. No API calls.

Run with: python tests/test_template_pack.py
"""
import csv
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from parameter_extractor import api_client, packs
from test_pipeline_offline import PDF, REPLAY_DIR


def test_template_is_hidden_and_valid():
    assert "_template" not in packs.available()                       # never in a list of research areas
    template = packs.template_pack()
    assert template.manifest.is_template and template.id in packs.available(include_template=True)
    from parameter_extractor.stages.optional import load_specs
    specs = load_specs(template)
    assert list(specs) == ["example_measurements"] and specs["example_measurements"].trigger.always
    assert set(template.template_columns) >= {p.column for p in specs["example_measurements"].parameters}
    assert (template.folder / "README.md").is_file()
    # every '_about' explains a key that exists (keeps the explanations in step with the files)
    for path in [template.folder / "pack.json", template.folder / "columns.json",
                 *sorted((template.folder / "stages").glob("*.json"))]:
        data = json.loads(path.read_text())
        for key in data:
            if key.startswith("_about_"):
                assert key[len("_about_"):] in data, (path.name, key)


def test_create_pack_checks_its_id():
    with tempfile.TemporaryDirectory() as tmp:
        for bad in ("My Area", "1area", "a", "prebiotic_chemistry", "_template"):
            try:
                packs.create_pack(bad, "X", base=Path(tmp))
            except ValueError:
                continue
            raise AssertionError(f"accepted {bad!r}")
        try:
            packs.create_pack("good_id", "  ", base=Path(tmp))
            raise AssertionError("accepted an empty name")
        except ValueError:
            pass


def test_a_pack_created_from_the_template_runs():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.pipeline import run_pipeline
    from parameter_extractor.schemas.paper_metadata import PaperMetadata
    with tempfile.TemporaryDirectory() as tmp:
        packs.add_search_dir(Path(tmp))
        pack = packs.create_pack("demo_area", "Demo area", "A pack made from the template.", base=Path(tmp))
        assert pack.label == "Demo area" and not pack.manifest.is_template
        assert "demo_area" in packs.available() and "_template" not in packs.available()
        seen = {}
        meta = PaperMetadata.model_validate_json((REPLAY_DIR / "metadata.output.json").read_text())

        def send(ctx, *, model, system_prompt, content, response_model, **kw):
            name = response_model.__name__
            seen[name] = content if isinstance(content, str) else content[-1]["text"]
            if name == "StructurePlan":
                out = response_model.model_validate({"kind": "experimental", "n_rows": 2, "sets": [
                    {"set": "Run A", "type": "Time Series", "varies": "time", "src": "Table 1",
                     "samples": [{"label": "1 h", "hr": 1, "src": "Table 1"}, {"label": "2 h", "hr": 2, "src": "Table 1"}]}]})
            elif name == "PaperMetadata":
                out = meta
            else:                                                       # the example stage
                v = lambda smp, col, val, unit, **kw: dict(set_label="Run A" if smp or col != "temperature_C" else "",
                                                          sample_label=smp, parameter=col, value=val, unit=unit,
                                                          quote="q", source="Table 1", confidence="high", **kw)
                out = response_model.model_validate({"parameters": [
                    v("", "temperature_C", 353.15, "K", err_plus=1.0, err_minus=1.0),   # whole paper, converted
                    v("1 h", "product_yield_pct", 12.5, "%"), v("2 h", "product_yield_pct", 20.0, "%"),
                    v("", "sample_material", 0, "", text="glycine")]})
            return SimpleNamespace(id="fake", stop_reason="end_turn", parsed_output=out,
                                   content=[SimpleNamespace(type="text", text=out.model_dump_json())],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5))

        try:
            with patch.object(api_client, "_send", send):
                result = run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp) / "out",
                                                                   pack="demo_area", registry_path=None))
            plan_prompt = seen["StructurePlan"]
            assert "one row per sample, grouped into sets" in plan_prompt               # the shared prompt
            assert "EXAMPLE RULES" in plan_prompt and "Demo area" in plan_prompt         # the pack's rules
            assert set(seen) == {"StructurePlan", "PaperMetadata", "ExampleMeasurementsResult"}
            with open(result.csv_path) as f:
                rows = list(csv.DictReader(f))
            assert [r["product_yield_pct"] for r in rows] == ["12.5", "20.0"]
            assert [r["temperature_C"] for r in rows] == ["80.0", "80.0"]               # K -> °C, every row
            assert rows[0]["temperature_C_err_plus"] == "1.0" and rows[0]["duration_hr"] == "1.0"
            assert all(r["sample_material"] == "glycine" for r in rows)
        finally:
            packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All template-pack tests passed.")
