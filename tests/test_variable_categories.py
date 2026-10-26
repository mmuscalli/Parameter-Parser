"""
Offline tests for new-variable categories (variable_categories.py) and the "Suggest new variables"
switch (RunConfig.suggest_new_variables): categories per pack, the model's `cat` in open-ended
stages, values put in their category's format (number + unit -> column suffix, word limits),
grouping for the review, and what's reviewed with suggestions off. No API calls.

Run with: python tests/test_variable_categories.py
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client, packs, pipeline
from parameter_extractor import variable_categories as vc
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.ingestion.new_variables import collect_new_variables, group_new_variables, stored_value
from parameter_extractor.pipeline import extract, finish
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.methodology import OtherParameter, empty_methodology
from parameter_extractor.schemas.variables import TermFinding, TermSearch
from parameter_extractor.stages.optional import for_run, load_specs
from test_new_variables import _add_extras
from test_pipeline_offline import PDF, _replay_send


def _other(name, value, category=""):
    return OtherParameter(name=name, value=value, quote="q", source="Methods", confidence="high", category=category)


def test_categories_per_pack():
    packs.activate("prebiotic_chemistry")
    ids = [c.id for c in vc.categories()]
    assert ids == ["species", "solution_prep", "conditions", "metadata", "methodology", "figure", "assumed"]
    assert [c.id for c in vc.assignable()] == ["solution_prep", "conditions", "metadata", "methodology"]
    assert vc.for_source("species", "sampled") == "species" and vc.for_source("added_solution") == "solution_prep"
    try:
        packs.activate("exoplanets")                     # only the shared ones (+ built-in groups)
        assert [c.id for c in vc.categories()] == ["metadata", "methodology", "figure", "assumed"]
        assert vc.guess("45 min") == "methodology"       # no number category there
    finally:
        packs.activate("prebiotic_chemistry")


def test_a_pack_can_replace_a_shared_category():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "p"
        folder.mkdir()
        (folder / "template.json").write_text(json.dumps({"all_columns": ["a"]}))
        (folder / "pack.json").write_text(json.dumps({
            "id": "p", "label": "P", "template": "template.json",
            "variable_categories": [{"id": "metadata", "label": "Catalogue data", "value_type": "text",
                                     "max_words": 5},
                                    {"id": "observations", "label": "Observations", "value_type": "any"}]}))
        pack = packs.Pack(folder)
        cats = vc.categories(pack)
        assert [c.id for c in cats] == ["metadata", "observations", "methodology", "figure", "assumed"]
        assert cats[0].label == "Catalogue data"


def test_open_ended_items_carry_a_category_unless_suggestions_are_off():
    spec = load_specs()["experimental_conditions"]
    _, result = spec.models()
    other = next(d for name, d in result.model_json_schema()["$defs"].items() if name.endswith("Other"))
    assert other["properties"]["cat"]["enum"] == ["solution_prep", "conditions", "metadata", "methodology"]
    assert "cat" in other["required"] and "default" not in other["properties"]["cat"]
    rule = next(r for r in spec._field_rules() if "`cat` its category" in r)
    assert "`conditions` (" in rule and "one number with its unit" in rule
    # an answer recorded before categories still loads (category '')
    assert result.model_validate({"other": [{"nm": "x", "v": "1 h", "q": "", "src": "", "c": "high"}]}).other[0].category == ""
    off = for_run(spec, suggest=False)
    assert "other" not in off.models()[1].model_fields and not any("`other`" in r for r in off._field_rules())
    assert for_run(spec, suggest=True) is spec


def test_values_follow_their_category_format():
    method = empty_methodology("p")
    method.other_parameters += [
        _other("reaction time", "45 min", "conditions"),
        _other("buffer pH range", "pH 7-8", "conditions"),                       # not one number
        _other("heating method", "thermostatically controlled sand bath with a reflux cooler on top of the "
                                 "reaction vial", "methodology"),                # over 10 words
        _other("chemical supplier", "Sigma-Aldrich", "species"),                 # not one the model may assign
        _other("reactor volume", "0.25 cm3"),                                    # recorded before categories
        _other("reactor tube length", "5 m", "conditions"),                      # metres, not molar
    ]
    found = {v.name: v for v in collect_new_variables(method, ChemistryExtraction(solutes=[]))}
    t = found["reaction time"]
    assert (t.category, t.value, t.unit, t.proposed_column) == ("conditions", 45.0, "min", "reaction_time_hr")
    assert stored_value(t, t.proposed_column)[0] == 0.75                        # converted to hours
    assert stored_value(t, "reaction_time")[0] == "45 min"                     # a column with no unit keeps it
    assert found["buffer pH range"].value is None and "one number" in found["buffer pH range"].format_note
    assert "at most 10 words" in found["heating method"].format_note
    assert found["chemical supplier"].category == "methodology" and not found["chemical supplier"].format_note
    assert found["reactor volume"].category == "conditions" and found["reactor volume"].proposed_column == "reactor_volume_mL"
    length = found["reactor tube length"]
    assert length.value is None and "metres or molar" in length.format_note and length.proposed_column == "reactor_tube_length"
    order = [g.category for g in group_new_variables(list(found.values()))]
    assert order == sorted(order, key=["species", "solution_prep", "conditions", "metadata", "methodology"].index)


def _run(tmp: Path, suggest: bool, review):
    config = RunConfig.from_settings(api_key="replay", output_dir=tmp, registry_path=tmp / "r.json",
                                     focus_terms=["reaction volume"], suggest_new_variables=suggest)
    search = TermSearch(findings=[TermFinding(term="reaction volume", found=True, name="reaction volume",
                                              value="1 cm3", column="", set_label="", quote="1 cm3 vials",
                                              source="Experimental", confidence="high")])
    with patch.object(api_client, "_send", _replay_send), \
            patch.object(pipeline, "run_term_search", lambda ctx, t, *a: search):
        ex = extract(PDF, config)
        _add_extras(ex)
        return finish(ex, review=review)


def test_suggestions_off_reviews_only_what_was_asked_for():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    for suggest in (True, False):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(Path(tmp), suggest, lambda groups, unfound, reg: seen.extend(groups) or [])
            names = [g.name for g in seen]
            record = json.loads((result.run_dir / "new_variables.json").read_text())
            flags = [f for f in result.paper_flags if f.kind == "new_variable"]
            if suggest:
                assert names == ["RbCl", "Foo", "stirring rate", "reaction volume"], names     # first seen within one
                assert [g.category for g in seen] == ["species", "species", "conditions", "conditions"]
                assert len(flags) == 4 and "(Reaction Conditions):" in flags[2].message
            else:
                assert names == ["reaction volume"], names               # the user's own search term
                assert len(flags) == 2 and "'reaction volume'" in flags[0].message   # reviewed, not added
                flag = flags[1]                                          # everything else in one flag
                assert "suggestions are off" in flag.message and "Chemical Species: RbCl, Foo" in flag.message
                assert "Reaction Conditions: stirring rate" in flag.message
                assert {v["name"] for v in record["left_out"]} == {"RbCl", "Foo", "stirring rate", "reaction volume"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All variable-category tests passed.")
