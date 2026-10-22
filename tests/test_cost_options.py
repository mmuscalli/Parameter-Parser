"""
Offline tests for the cost options (2026-10-22): prompt caching (on by default --
the paper, text + table images, sent first and identically in every
paper-reading step, marked for caching, each step's own task after it, one
shared system prompt and the same tool list, each step answering through its
own tool: the API's cache key includes a request's output schema, so per-step
output formats couldn't share the cache), cache-aware cost estimates, and the
model profiles (standard / economy). Replays nielsen2019's recorded responses;
no API calls.

Run with: python tests/test_cost_options.py
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

from parameter_extractor import api_client, packs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pipeline import run_pipeline
from parameter_extractor.pricing import request_cost
from test_pipeline_offline import make_replay

PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Nielsen2019" / "nielsen2019.pdf"
REF = ROOT / "runs" / "nielsen2019_auto"
PAPER_STAGES = {"StructurePlan", "PlanetParametersResult", "StellarParametersResult", "SystemAndDiscoveryResult",
                "FitModels"}


def _run(tmp, **kw):
    replay, sent = make_replay(REF), {}

    def send(ctx, *, model, system_prompt, content, response_model, **rest):
        sent[response_model.__name__] = (model, system_prompt, content, getattr(api_client._streamed, "tool", None))
        out = replay(ctx, model=model, system_prompt=system_prompt, content=content, response_model=response_model)
        if response_model.__name__ in PAPER_STAGES and isinstance(content, list):   # as the API reports caching
            first = response_model.__name__ == "StructurePlan"
            out.usage = SimpleNamespace(input_tokens=900, output_tokens=out.usage.output_tokens,
                                        cache_creation_input_tokens=30000 if first else 0,
                                        cache_read_input_tokens=0 if first else 30000)
        return out
    with patch.object(api_client, "_send", send):
        result = run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp), pack="exoplanets", **kw))
    return result, sent


def test_the_paper_is_one_cached_prefix():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result, sent = _run(tmp, prompt_caching=True)
            assert result.csv_path.read_text() == (REF / "nielsen2019_extracted.csv").read_text()   # same result
            prefixes = []
            tool_lists = set()
            for name in PAPER_STAGES:
                model, system, content, tool = sent[name]
                # every step: the same tool list (all the run's paper-reading steps), forced to its own
                assert tool is not None and tool[0] in [t["name"] for t in tool[1]]
                assert sent[name][2][-1]["text"].endswith(f"Answer by calling the `{tool[0]}` tool.")
                tool_lists.add(json.dumps(tool[1]))
                assert system == api_client.SHARED_SYSTEM
                marked = [i for i, b in enumerate(content) if "cache_control" in b]
                assert len(marked) == 1 and content[marked[0]]["text"].startswith("PAPER TEXT:")
                prefixes.append(json.dumps(content[:marked[0] + 1]))
                task = content[-1]["text"]
                assert task.startswith("YOUR TASK: ") and api_client.PAPER_ABOVE in task
                paper = content[marked[0]]["text"]
                assert paper[200:700] not in task and len(task) < len(paper)  # the paper isn't sent twice
            assert len(set(prefixes)) == 1                                       # byte-identical prefix
            assert len(tool_lists) == 1                                          # ... and tool list
            names = [t["name"] for t in json.loads(tool_lists.pop())]
            assert names == ["structure_planner", "fit_models", "planet_parameters", "stellar_parameters",
                             "system_and_discovery"]
            assert sent["PaperMetadata"][3] is None                              # not a paper-reading step
            assert any(b["type"] == "image" for b in json.loads(prefixes[0]))   # table pages included
            assert isinstance(sent["PaperMetadata"][2], str)                    # page 1 only: not shared
            # cached tokens counted, and priced at the cache rates
            usage = {u.stage: u for u in result.usage}
            assert usage["structure_planner"].cache_write_tokens == 30000
            assert usage["planet_parameters"].cache_read_tokens == 30000
            assert usage["planet_parameters"].prompt_tokens == 30900
            assert abs(usage["planet_parameters"].cost_usd
                       - request_cost("claude-sonnet-5-5", 900, usage["planet_parameters"].output_tokens, 0, 30000)) < 1e-9
            assert result.cached_tokens == 4 * 30000
            summary = json.loads((result.run_dir / "run_summary.json").read_text())
            assert summary["cache_read_tokens"] == 120000 and summary["input_tokens"] == result.input_tokens
    finally:
        packs.activate("prebiotic_chemistry")


def test_caching_can_be_switched_off():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result, sent = _run(tmp, prompt_caching=False)
            assert result.csv_path.read_text() == (REF / "nielsen2019_extracted.csv").read_text()
            model, system, content, tool = sent["PlanetParametersResult"]
            assert tool is None                                                  # structured output as before
            assert system != api_client.SHARED_SYSTEM
            assert not any("cache_control" in b for b in content if isinstance(b, dict))
            assert "PAPER TEXT" in content[-1]["text"]
    finally:
        packs.activate("prebiotic_chemistry")


def test_model_profiles():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    try:
        for profile, expect in (("standard", {"StructurePlan": "sonnet", "PlanetParametersResult": "sonnet"}),
                                ("economy", {"StructurePlan": "haiku", "FitModels": "haiku",
                                             "PlanetParametersResult": "haiku"})):
            with tempfile.TemporaryDirectory() as tmp:
                _, sent = _run(tmp, model_profile=profile)
            for name, family in expect.items():
                assert family in sent[name][0], (profile, name, sent[name][0])
        cfg = RunConfig.from_settings(api_key="x", model_profile="economy")
        assert "sonnet" in cfg.model_for("figure_planner")                    # asked-for steps keep Sonnet
    finally:
        packs.activate("prebiotic_chemistry")


def test_units_and_names_found_in_the_live_tests():
    from parameter_extractor.units import convert_printed
    from parameter_extractor.calculators.exoplanets import reference_name
    assert abs(convert_printed(0.485, "10^9 erg s-1 cm-2", "S_E")[0] - 356.36) < 0.01     # nielsen2019 pl_insol
    assert abs(convert_printed(1361, "W/m2", "S_E")[0] - 1) < 1e-9
    assert convert_printed(0.2, "deg", "")[0] is None and convert_printed(0.1, "dex", "")[0] == 0.1
    assert reference_name(["Huan-Yu TENG", "Bun'ei SATO", "Masayuki KUZUHARA"], 2023) == "Teng et al. 2023"
    assert reference_name(["H.-Y. Teng", "B. Sato"], 2023) == "Teng & Sato 2023"


def test_a_forced_tool_call_is_read_like_a_structured_output():
    from pydantic import BaseModel, ValidationError

    class Answer(BaseModel):
        planet: str
        period_days: float
    message = SimpleNamespace(id="m", stop_reason="tool_use", usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                              content=[SimpleNamespace(type="tool_use", name="other", input={}),
                                       SimpleNamespace(type="tool_use", name="planet_parameters",
                                                       input={"planet": "HD 1397 b", "period_days": 11.5})])
    out = api_client._from_tool_call(message, "planet_parameters", Answer)
    as_string = SimpleNamespace(**{**vars(message), "content": [SimpleNamespace(
        type="tool_use", name="planet_parameters", input={"planet": "HD 1397 b", "period_days": 11.5})]})
    assert api_client._decoded({"items": '[{"a": 1}]', "notes": "[not json"}) == {"items": [{"a": 1}], "notes": "[not json"}
    assert api_client._from_tool_call(as_string, "planet_parameters", Answer).parsed_output.period_days == 11.5
    assert out.parsed_output == Answer(planet="HD 1397 b", period_days=11.5) and out.stop_reason == "end_turn"
    bad = SimpleNamespace(**{**vars(message), "content": [SimpleNamespace(type="tool_use", name="planet_parameters",
                                                                          input={"planet": "x"})]})
    try:
        api_client._from_tool_call(bad, "planet_parameters", Answer)
    except ValidationError:
        pass                                     # handled like a broken answer: retried once
    else:
        raise AssertionError("an answer missing a field must not pass")


def test_cache_prices():
    # Sonnet 5.5: write 1.25x, read 0.05x the $2 input price
    assert abs(request_cost("claude-sonnet-5-5", 1_000_000, 0, 0, 0) - 2.0) < 1e-9
    assert abs(request_cost("claude-sonnet-5-5", 0, 0, 1_000_000, 0) - 2.5) < 1e-9
    assert abs(request_cost("claude-sonnet-5-5", 0, 0, 0, 1_000_000) - 0.1) < 1e-9
    # Haiku 5.5: the 100K tier counts cached tokens too
    assert abs(request_cost("claude-haiku-5-5", 1000, 0, 0, 50_000) - (1000 * 0.10 + 50_000 * 0.01) / 1e6) < 1e-12
    assert abs(request_cost("claude-haiku-5-5", 1000, 0, 0, 120_000) - (1000 * 0.50 + 120_000 * 0.05) / 1e6) < 1e-12


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All cost-option tests passed.")
