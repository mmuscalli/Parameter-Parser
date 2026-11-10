"""
Cost pass 2026-11-09: the extraction steps get a compact row plan with ids for sets and samples and may answer with
the ids (structure_plan.step_plan_json / plan_ids / expand_ids, applied in api_client.call_structured); the Balanced
profile's row planning caches nothing its Haiku steps can't read, and one warm-up request caches the paper for them;
one chemistry species without a value doesn't fail the step. No API calls.
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("PARAMETER_EXTRACTOR_NO_KEYCHAIN", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client  # noqa: E402
from parameter_extractor.schemas.structure_plan import (StructurePlan, expand_ids, plan_ids,  # noqa: E402
                                                        step_plan_json)

PLAN = StructurePlan.model_validate({"kind": "experimental", "n_rows": 3, "excluded": ["Fig. 2 data, figure only"],
                                     "notes": "a note", "sets": [
    {"set": "Na+ 3.33 M, 81 C", "type": "Time Series", "varies": "Na+", "src": "Table 1",
     "samples": [{"label": "t = 97.3 h", "hr": 97.3, "src": "Table 1"}, {"label": "t = 245.8 h", "hr": 245.8, "src": ""}]},
    {"set": "K+ 3.33 M, 85 C", "type": "Time Series", "varies": "K+", "src": "Table 1",
     "samples": [{"label": "t = 97.3 h", "hr": 97.3, "src": "Fig. 3"}]}]})


def test_compact_plan_and_ids():
    text = step_plan_json(PLAN)
    assert "S1.2" in text and "S2.1" in text and "excluded" not in text and "a note" not in text
    assert "\n  " not in text.split("\n", 1)[1]                          # one line of JSON, no indentation
    assert '"src":"Fig. 3"' in text and text.count('"src":"Table 1"') == 2    # a sample's src only when it differs
    assert len(text) < len(PLAN.model_dump_json(indent=2))
    ids = plan_ids(PLAN)
    assert ids["S2"] == ("set", "K+ 3.33 M, 85 C") and ids["S2.1"] == ("sample", "K+ 3.33 M, 85 C", "t = 97.3 h")


def test_answers_with_ids_get_labels_back():
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    ids = plan_ids(PLAN)
    chem = ChemistryExtraction.model_validate({
        "tables": [{"src": "Table 1", "c": "high", "cols": [{"nm": "Gly-Gly", "r": "sampled", "ph": "aq", "u": "%",
                                                              "lbl": "%"}],
                    "rows": [{"set": "S1", "sample": "S1.2", "row": "245.8", "v": ["5.60"]},
                             {"set": "", "sample": "S2.1", "row": "97.3", "v": ["1.0"]}]}],
        "groups": [{"set": "S2", "sample": "", "species": [
            {"nm": "KCl", "r": "initial", "ph": "aq", "v": 3.33, "u": "M", "q": "q", "src": "s", "c": "high"},
            {"nm": "Gly", "r": "initial", "ph": "aq", "u": "M", "q": "q", "src": "s", "c": "high"}]}],  # no `v`
        "added_solutions": [], "molar_ratios": [], "unmapped_species": []})
    expand_ids(chem, ids)
    got = {(s.name, s.set_label, s.sample_label) for s in chem.solutes}
    assert ("Gly-Gly", "Na+ 3.33 M, 81 C", "t = 245.8 h") in got
    assert ("Gly-Gly", "K+ 3.33 M, 85 C", "t = 97.3 h") in got           # the set from the sample's id
    assert ("KCl", "K+ 3.33 M, 85 C", None) in got or ("KCl", "K+ 3.33 M, 85 C", "") in got
    gly = next(s for s in chem.solutes if s.name == "Gly")
    assert gly.concentration_value is None                                # left out: 'not given', no failure
    # labels and other strings pass unchanged
    from parameter_extractor.schemas.chemistry import SoluteEntry
    e = SoluteEntry.model_validate({"nm": "S2", "r": "initial", "ph": "aq", "v": 1, "u": "M", "q": "S1 text",
                                    "src": "Table S1", "c": "high", "set_label": "Na+ 3.33 M, 81 C"})
    expand_ids(e, ids)
    assert e.set_label == "Na+ 3.33 M, 81 C" and e.quote == "S1 text" and e.source == "Table S1"


def test_spec_stage_answers():
    from parameter_extractor import packs
    from parameter_extractor.stages.optional import load_specs
    spec = load_specs(packs.available()["prebiotic_chemistry"])["experimental_conditions"]
    model = spec.models()[1]
    r = model.model_validate({"rows": [{"set": "S1", "sample": "S1.1", "values": [
        {"col": "initial_temperature_C", "v": 81, "u": "°C", "q": "81 C", "src": "Table 1", "c": "high"}]}],
        "notes": "", "other": []})
    expand_ids(r, plan_ids(PLAN))
    item = r.parameters[0]
    assert item.set_label == "Na+ 3.33 M, 81 C" and item.sample_label == "t = 97.3 h"


def test_balanced_profile_caching():
    from parameter_extractor.config.run_config import RunConfig
    standard = RunConfig.from_settings(api_key="x", model_profile="standard", registry_path=None)
    balanced = RunConfig.from_settings(api_key="x", model_profile="balanced", registry_path=None)
    assert not api_client.steps_model_differs(standard) and api_client.steps_model_differs(balanced)
    paper = api_client.PaperContext(text="T")
    assert "cache_control" in api_client._paper_blocks(paper)[-1]
    assert "cache_control" not in api_client._paper_blocks(paper, cached=False)[-1]
    # the warm-up never calls the API when tests replace the network call
    from parameter_extractor.run_context import RunContext
    ctx = RunContext(config=balanced, run_dir=Path("/tmp"), total_steps=1)
    ctx.paper = paper
    with patch.object(api_client, "_send", lambda *a, **k: None):
        api_client.warm_cache(ctx)
    assert ctx.usage == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
