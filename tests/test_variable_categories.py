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
from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
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
    assert ids == ["starting_species", "products", "solution_prep", "conditions", "analysis", "metadata",
                   "methodology", "figure", "assumed"]
    assert [c.id for c in vc.assignable()] == ["solution_prep", "conditions", "analysis", "metadata", "methodology"]
    assert vc.for_source("species", "sampled") == "products" and vc.for_source("species", "initial") == "starting_species"
    assert vc.for_source("species") == "starting_species" and vc.for_source("added_solution") == "solution_prep"
    try:
        packs.activate("exoplanets")
        assert [c.id for c in vc.categories()] == ["observations", "stellar_activity", "data_reduction", "metadata",
                                                   "methodology", "figure", "assumed"]
        assert vc.guess("45 min") == "methodology"       # no number category there
        spec = load_specs()["system_and_discovery"]      # the step that collects them
        rule = next(r for r in spec._field_rules() if "`cat` its category" in r)
        assert "`data_reduction` (" in rule and "`stellar_activity` (" in rule and "not priors" in rule
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
    assert other["properties"]["cat"]["enum"] == ["solution_prep", "conditions", "analysis", "metadata", "methodology"]
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
    assert order == sorted(order, key=["solution_prep", "conditions", "analysis", "metadata", "methodology"].index)


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
                assert [g.category for g in seen] == ["starting_species", "products", "conditions", "conditions"]
                assert len(flags) == 4 and "(Reaction Conditions):" in flags[2].message
            else:
                assert names == ["reaction volume"], names               # the user's own search term
                assert len(flags) == 2 and "'reaction volume'" in flags[0].message   # reviewed, not added
                flag = flags[1]                                          # everything else in one flag
                assert "suggestions are off" in flag.message and "Starting Species: RbCl; Products: Foo" in flag.message
                assert "Reaction Conditions: stirring rate" in flag.message
                assert {v["name"] for v in record["left_out"]} == {"RbCl", "Foo", "stirring rate", "reaction volume"}


def test_software_already_in_the_fit_models_is_not_suggested_again():
    from parameter_extractor.ingestion.duplicates import drop_recorded_software
    from parameter_extractor.schemas.fit_models import FitModels
    fits = FitModels.model_validate({"models": [{
        "label": "RV fit", "rows": [], "stars": [], "datasets": [], "joint": False, "joint_description": "",
        "star_and_planets_joint": False, "priors": [], "assumptions": [], "quote": "", "source": "",
        "confidence": "high", "software": [{"name": "RadVel", "version": "", "role": "fitting code"},
                                           {"name": "emcee", "version": "3", "role": "sampler"}]}]})
    method = empty_methodology("p")
    method.other_parameters += [_other("fitting software", "RadVel package with the emcee sampler (v3.0)", "data_reduction"),
                                _other("RV extraction", "SERVAL pipeline, then RadVel", "data_reduction"),
                                _other("outlier removal", "3-sigma clipping", "data_reduction")]
    dropped = drop_recorded_software(method, fits)
    assert [d.parameter.name for d in dropped] == ["fitting software"] and "radvel" in dropped[0].matches
    assert [p.name for p in method.other_parameters] == ["RV extraction", "outlier removal"]
    assert drop_recorded_software(method, None) == []                    # fitting-models step off: all kept


def test_suggestions_repeating_dataset_values_are_dropped():
    from parameter_extractor.ingestion.duplicates import drop_repeated_values
    from parameter_extractor.schemas.row_schema import ExtractedRow
    row = ExtractedRow(full_id="001001001", set_id="001001", sample_id="001", set_type="text", entry_number=1,
                       paper_title="t", authors=["A"], year_published=2020, journal_published="j",
                       experiment_type="Batch", solution_type="Wet",
                       initial_temperature_C=42.5, extra={"st_rotpalt1": 42.5, "st_rotpalt1err1": 3.4, "x": 0.49})
    method = empty_methodology("p")
    method.other_parameters += [_other("rotation from activity", "42.5 ± 3.4 days", "stellar_activity"),
                                _other("correlation", "r ~ 0.49", "stellar_activity"),          # one short number
                                _other("observing run", "Sector 1, 2018", "observations"),     # nothing distinctive
                                _other("cadence", "42.5 s and 7 min", "observations"),         # 7 isn't a value
                                _other("activity model", "extra Keplerian with a prior on 42.5 ± 3.4 d", "stellar_activity"),
                                _other("spread", "42.5 to 0.49 s", "observations")]            # two parameters
    dropped = drop_repeated_values(method, [row], lambda s, smp: ["001001001"])
    assert [d.parameter.name for d in dropped] == ["rotation from activity"], dropped
    assert dropped[0].matches == "st_rotpalt1 = 42.5, st_rotpalt1err1 = 3.4"
    assert [p.name for p in method.other_parameters] == ["correlation", "observing run", "cadence", "activity model",
                                                         "spread"]


def test_symbol_font_characters_in_the_private_use_area():
    """kim2017: SymbolMT draws µ, α, β at U+F06D/F061/F062 -- they used to vanish ('5 L' for 5 µL)."""
    from parameter_extractor.ingestion.pdf_parser import _symbol_private_use
    assert [_symbol_private_use(c) for c in "\uf06d\uf061\uf062\uf0b0\uf0b1"] == ["µ", "α", "β", "°", "±"]
    assert _symbol_private_use("m") is None and _symbol_private_use("\ue000") is None
    assert vc.unit_suffix("µL") == "_uL" and vc.unit_suffix("mL") == "_mL" and vc.unit_suffix("min") == "_hr"


def test_mixture_flags_are_one_per_species():
    from parameter_extractor.calculators.mixing import MixingNote
    from parameter_extractor.pipeline import grouped_mixing_flags
    notes = [MixingNote("derived", f"CaCl2 (set 'S{i}'): {v} mM in the mixture -- 15 mM x 15 µL / {t} µL.",
                        species="CaCl2", short=f"S{i}: {v} mM") for i, (v, t) in enumerate([(9, 25), (6, 37.5)])]
    notes.append(MixingNote("not_derived", "X: not calculated"))
    flags = grouped_mixing_flags(notes)
    assert [f.kind for f in flags] == ["not_calculated", "derived_value"]
    assert "in 2 places -- S0: 9 mM; S1: 6 mM" in flags[1].message and "15 mM x 15 µL / 25 µL" in flags[1].message


def test_recovered_starting_material_is_not_a_yield():
    from parameter_extractor.ingestion.flatten_to_template import proposed_column_for_solute, species_alias_name
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.registry import VariableRegistry
    c = dict(phase="aq", role="sampled", concentration_value=93.1, concentration_unit_raw="%", quote="1 93.1",
             confidence="high", conversion_note=None)
    by_header = SoluteEntry(name="nicotinamide", source="Table 1, row 1, column Recovered Nicotinamide (%)", **c)
    by_model = SoluteEntry(name="nicotinamide", source="Table 1", measure="recovered", **c)
    product = SoluteEntry(name="nicotinamide ribose 2'-phosphate", source="Table 1, row 1, column Yield of 7 (%)", **c)
    assert proposed_column_for_solute(by_header) == proposed_column_for_solute(by_model) == "sampled_nicotinamide_%recovered"
    assert proposed_column_for_solute(product) == "sampled_nicotinamide_ribose_2'-phosphate_%yield"
    assert species_alias_name(by_model) == "sampled nicotinamide % recovered" and unit_for_column(
        "sampled_nicotinamide_%recovered") == "%"
    assert VariableRegistry(None).display_name("species:sampled nicotinamide % recovered") == \
        "nicotinamide (measured, % recovered)"


def test_volumes_that_differ_by_sample():
    """kim2017 live run: one set whose samples differ by the ammonium formate volume added -- given per
    sample (sample_label on the added solution), or wrongly as a 'concentration' in µL (repaired)."""
    from parameter_extractor.calculators.mixing import derive_mixture_concentrations, volumes_as_concentrations
    from parameter_extractor.schemas.chemistry import AddedSolution
    base = dict(phase="aq", quote="q", source="s", confidence="high", conversion_note=None)
    chem = ChemistryExtraction(
        solutes=[SoluteEntry(name="CaCl2", role="initial", concentration_value=15, concentration_unit_raw="mM",
                             concentration_mM=15, concentration_basis="stock", stock_solution="CaCl2 stock", **base),
                 SoluteEntry(name="formate", role="initial", concentration_value=15, concentration_unit_raw="mM",
                             concentration_mM=15, concentration_basis="stock", stock_solution="formate stock", **base),
                 SoluteEntry(name="formate", role="initial", set_label="T1", sample_label="b",
                             concentration_value=5, concentration_unit_raw="µL", **base)],      # a volume
        added_solutions=[AddedSolution(solution="CaCl2 stock", volume="15 µL"),
                         AddedSolution(set_label="T1", sample_label="a", solution="formate stock", volume="0 µL")])
    [repair] = volumes_as_concentrations(chem)
    assert repair.kind == "repaired" and [s.sample_label for s in chem.added_solutions] == ["", "a", "b"]
    notes = derive_mixture_concentrations(chem, ["T1"], {"T1": ["a", "b"]})
    got = {(s.name, s.sample_label): s.concentration_mM for s in chem.solutes if s.derived}
    assert got == {("CaCl2", "a"): 15.0, ("CaCl2", "b"): 11.25, ("formate", "a"): 0.0, ("formate", "b"): 3.75}, got   # b: 15 + 5 µL
    assert all(n.kind == "derived" for n in notes)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All variable-category tests passed.")
