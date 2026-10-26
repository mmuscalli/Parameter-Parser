"""
Offline tests for domain packs (packs/): the prebiotic chemistry pack carries
what used to be built in, and a second, unrelated pack -- written here as a
throwaway folder: its own template, structure prompt and a per-sample stage,
no methodology or chemistry -- runs through the real pipeline (API calls
replaced) and produces its own CSV. No API calls.

Run with: python tests/test_domain_packs.py
"""
import csv
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client, packs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pipeline import run_pipeline
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from test_pipeline_offline import PDF, REPLAY_DIR


def test_prebiotic_pack_carries_the_old_defaults():
    pack = packs.activate("prebiotic_chemistry")
    # PaperDataTemplate's 280 columns, less 65 Mickey removed and author1..7 -> author_list (2026-10-22)
    assert len(pack.template_columns) == 208 and len(pack.species_names) == 129
    assert "author_list" in pack.template_columns and "author1" not in pack.template_columns
    assert not {"cycle_number", "cycle_duration_hr", "initial_Na+_mM", "isModeled"} & set(pack.template_columns)
    # methodology became the configurable experimental_conditions stage (2026-10-22)
    assert not pack.uses("methodology") and pack.uses("chemistry") and pack.uses("peptide_totals")
    assert pack.uses("water_type") and pack.uses("results_check")
    assert pack.prompt_path("chemistry").parent.name == "prompts" and pack.folder.name in str(pack.prompt_path("chemistry"))
    assert pack.prompt_path("metadata").parent.parent.name == "parameter_extractor"   # generic: the app's
    from parameter_extractor.stages.optional import load_specs
    assert list(load_specs()) == ["experimental_conditions", "wet_dry"]


def _write_pack(base: Path) -> Path:
    folder = base / "exoplanet_demo"
    (folder / "prompts").mkdir(parents=True)
    (folder / "stages").mkdir()
    (folder / "pack.json").write_text(json.dumps({
        "id": "exoplanet_demo", "label": "Exoplanets (demo)", "template": "template.json",
        "builtin_stages": [], "postprocess": [], "units": {"set": "planetary system", "sample": "planet"}}))
    (folder / "template.json").write_text(json.dumps({
        "all_columns": ["full_id", "pl_name", "hostname", "pl_orbper", "pl_bmassj", "st_mass", "paper_title"],
        "species_names": []}))
    (folder / "prompts" / "structure_planner.md").write_text(
        "DEMO PROMPT: one set per planetary system, one sample per planet.\n{{PAPER_TEXT}}")
    (folder / "stages" / "planets.json").write_text(json.dumps({
        "name": "planet_parameters", "label": "Planet parameters", "per": "sample",
        "trigger": {"always": True}, "set_word": "planetary system",
        "intro": "Extract each planet's orbital parameters.",
        "parameters": [{"column": "pl_orbper", "unit": "d", "description": "orbital period"},
                       {"column": "pl_bmassj", "unit": "M_J", "description": "planet mass (or M sin i)"},
                       {"column": "st_mass", "unit": "M_sun", "description": "host star mass"}]}))
    return folder


def test_a_second_pack_runs_end_to_end():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp:
        packs.add_search_dir(Path(tmp))
        _write_pack(Path(tmp))
        assert "exoplanet_demo" in packs.available()
        prompts_seen = {}
        meta = PaperMetadata.model_validate_json((REPLAY_DIR / "metadata.output.json").read_text())

        def send(ctx, *, model, system_prompt, content, response_model, **kw):
            name = response_model.__name__
            text = content if isinstance(content, str) else content[-1]["text"]
            prompts_seen[name] = text
            if name == "StructurePlan":
                out = response_model.model_validate({
                    "paper_id": "p", "total_planned_rows": 3, "experiment_sets": [
                        {"set_label": "11 Com", "set_type": "Independent", "varying_condition_summary": "11 Com",
                         "source_table_or_section": "Table 2", "data_source": "",
                         "samples": [{"sample_label": "11 Com b", "source": "Table 2"}]},
                        {"set_label": "HD 173416", "set_type": "Independent", "varying_condition_summary": "HD",
                         "source_table_or_section": "Table 2", "data_source": "",
                         "samples": [{"sample_label": "HD 173416 b", "source": "Table 2"},
                                     {"sample_label": "HD 173416 c", "source": "Table 2"}]}]})
            elif name == "PaperMetadata":
                out = meta
            else:      # the planet stage
                v = lambda s, smp, col, val: {"set_label": s, "sample_label": smp, "parameter": col, "value": val,
                                              "quote": "q", "source": "Table 2", "confidence": "high"}
                out = response_model.model_validate({"parameters": [
                    v("11 Com", "11 Com b", "pl_orbper", 326.03), v("11 Com", "11 Com b", "pl_bmassj", 19.4),
                    v("11 Com", "", "st_mass", 2.7),                                   # the whole system
                    v("HD 173416", "HD 173416 b", "pl_orbper", 323.6),
                    v("HD 173416", "HD 173416 c", "pl_orbper", 1000.0)]})
            raw = out.model_dump_json()
            return SimpleNamespace(id="fake", stop_reason="end_turn", parsed_output=out,
                                   content=[SimpleNamespace(type="text", text=raw)],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5))

        with patch.object(api_client, "_send", send):
            result = run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp) / "out",
                                                               pack="exoplanet_demo"))
        try:
            assert "DEMO PROMPT" in prompts_seen["StructurePlan"]                 # the pack's own prompt
            assert set(prompts_seen) == {"StructurePlan", "PaperMetadata", "PlanetParametersResult"}  # no chemistry
            assert "one planet only" in prompts_seen["PlanetParametersResult"]
            with open(result.csv_path) as f:
                rows = list(csv.DictReader(f))
            header = list(rows[0])
            assert header[:7] == ["full_id", "pl_name", "hostname", "pl_orbper", "pl_bmassj", "st_mass", "paper_title"]
            assert [r["pl_orbper"] for r in rows] == ["326.03", "323.6", "1000.0"]          # one row per planet
            assert [r["st_mass"] for r in rows] == ["2.7", "", ""] and rows[0]["pl_bmassj"] == "19.4"
            assert not any(c.startswith(("initial_", "sampled_")) for c in header)          # no chemistry columns
            assert [u.stage for u in result.usage] == ["structure_planner", "metadata", "planet_parameters"]
        finally:
            packs.activate("prebiotic_chemistry")


def test_unknown_pack_is_a_clear_error():
    try:
        packs.activate("no_such_pack")
    except ValueError as e:
        assert "prebiotic_chemistry" in str(e)
    else:
        raise AssertionError("an unknown pack must be refused")
    packs.activate("prebiotic_chemistry")



def test_shared_columns_and_prompt_rules():
    """2026-10-26: every pack gets packs/common_columns.json's columns (unless its template has them),
    and a pack adds rules to a shared prompt with prompts/<name>.rules.md instead of copying it."""
    from parameter_extractor.registry import standard_columns
    from parameter_extractor.stages.prompt_loader import load_prompt
    common = [c["column"] for c in packs.common_columns()]
    assert common[:5] == ["paper_title", "paper_DOI", "author_list", "year_published", "journal_published"]
    try:
        exo = packs.activate("exoplanets")
        assert standard_columns()[:6] == common                       # none in the archive's layout
        assert "Rules for this research area" not in load_prompt("figure_planner")     # no extra rules
        assert "row of the exoplanets dataset" in " ".join(load_prompt("figure_planner").split())
        packs.activate("prebiotic_chemistry")
        assert standard_columns()[0] == "paper_arxiv_id"               # the rest are template columns
        prompt = load_prompt("figure_planner", FIGURE_ID="Fig. 2")
        assert "Rules for this research area (Prebiotic chemistry):" in prompt
        assert "COMPLETE initial composition" in prompt and "FIGURE: Fig. 2" in prompt
        assert not (packs.current().folder / "prompts" / "figure_planner.md").exists()   # no copy
        assert "{{PACK_RULES}}" not in load_prompt("metadata", PAPER_TEXT="x")
    finally:
        packs.activate("prebiotic_chemistry")

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All domain pack tests passed.")
