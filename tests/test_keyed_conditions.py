"""
Conditions the paper gives for a starting solution (calculators/keyed_conditions.py, Mickey 2026-11-17: mitsuzawa
2004's starting pH per starting material never reached its figure rows): the answer row's `for`, the composition
match, a row's own value winning, conflicts and unreadable solutions flagged. No API calls.

Run with: python tests/test_keyed_conditions.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import packs  # noqa: E402
from parameter_extractor.calculators.keyed_conditions import apply_keyed_conditions, parse_solution  # noqa: E402
from parameter_extractor.schemas.row_schema import ExtractedRow  # noqa: E402

BASE = dict(set_type="Time Series", paper_title="t", authors=[], year_published=2004, journal_published="j",
            experiment_type="Flowthrough", solution_type="Wet")


def _row(fid, start, **extra):
    return ExtractedRow(full_id=fid, set_id=fid[:6], sample_id=fid[6:], entry_number=int(fid[6:]), **BASE,
                        species_mM=start, extra={"data_location": "Figure. 3", "sampled_Gly-Gly_aq_mM": 0.1, **extra})


def _answer(rows):
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.stages.optional import load_specs
    spec = load_specs()["experimental_conditions"]
    assert spec.by_starting_solution
    _Item, Result = spec.models()
    return spec, Result.model_validate({"rows": rows, "notes": ""})


def _ph(sol, ph):
    return {"set": "", "for": sol, "values": [{"col": "initial_pH", "v": ph, "u": "", "q": f"{sol} ({ph})",
                                               "src": "Table 2", "c": "high"}]}


def test_the_solutions_are_read():
    assert parse_solution("glycine 100 mM; diglycine 3.7 mM") == \
        ({"initial_Gly_aq_mM": 100.0, "initial_Gly-Gly_aq_mM": 3.7}, [])
    assert parse_solution("10^-2 M glycine")[0] == {"initial_Gly_aq_mM": 10.0}
    assert parse_solution("Gly (0.1 M)")[0] == {"initial_Gly_aq_mM": 100.0}
    assert parse_solution("cyclo(Gly-Gly) 2 mM")[0] == {"initial_cyclo_Gly-Gly_aq_mM": 2.0}
    assert parse_solution("the usual mixture") == ({}, ["the usual mixture"])


def test_values_reach_the_rows_with_that_starting_composition():
    spec, result = _answer([_ph("glycine 100 mM", 6.1), _ph("diglycine 3.7 mM", 5.7),
                            _ph("glycine 100 mM; diglycine 3.7 mM", 5.9)])
    # the values for a starting solution are not paper-wide values
    assert all(not p.set_label and p.parameter != "initial_pH" for p in result.parameters)
    g = _row("018002001", {"initial_Gly_aq_mM": 100.0})
    gg = _row("018003001", {"initial_Gly-Gly_aq_mM": 3.7})
    both = _row("018004001", {"initial_Gly_aq_mM": 100.0, "initial_Gly-Gly_aq_mM": 3.7})
    own = _row("018002002", {"initial_Gly_aq_mM": 100.0}, initial_pH=6.3)      # the row's own value wins
    other = _row("018005001", {"initial_Gly_aq_mM": 10.0})                     # another concentration
    flags = apply_keyed_conditions([g, gg, both, own, other], [(spec, result)])
    assert g.extra["initial_pH"] == 6.1 and gg.extra["initial_pH"] == 5.7 and both.extra["initial_pH"] == 5.9
    assert own.extra["initial_pH"] == 6.3 and "initial_pH" not in other.extra
    assert "for the starting solution 'glycine 100 mM'" in g.provenance["initial_pH"].origin
    assert len(flags) == 1 and flags[0].kind == "for_solution" and "'glycine 100 mM': 1 row(s)" in flags[0].message


def test_conflicts_unreadable_and_unmatched_solutions_are_flagged_not_written():
    spec, result = _answer([_ph("glycine 100 mM", 6.1), _ph("Gly (0.1 M)", 6.4), _ph("the usual mixture", 7.0),
                            _ph("alanine 50 mM", 6.0)])
    g = _row("018002001", {"initial_Gly_aq_mM": 100.0})
    msg = apply_keyed_conditions([g], [(spec, result)])[0].message
    assert "initial_pH" not in g.extra                        # two solutions, two values: nothing written
    assert "conflicting values" in msg and "'the usual mixture': its compounds" in msg
    assert "'alanine 50 mM': no row starts with this solution" in msg


def test_steps_without_the_option_send_no_for_field():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.stages.optional import StageSpec, load_specs
    spec = load_specs()["experimental_conditions"]
    off = StageSpec.model_validate({**spec.model_dump(), "by_starting_solution": False})
    schema = json.dumps(off.models()[1].model_json_schema())
    assert '"for"' not in schema and '"for"' in json.dumps(spec.models()[1].model_json_schema())


def test_the_experiment_rules_reach_any_pack_not_only_the_curated_one():
    """2026-11-17 (Mickey: no fixes that only one pack gets): the per-row, starting-value, number-in-text and
    starting-solution rules come from what a step HAS (initial_* conditions; a pack with the chemistry step), so a
    drafted or a user's own pack gets them like the prebiotic pack; steps without starting conditions (exoplanets,
    module steps) get none of them and their requests don't change."""
    from parameter_extractor.stages.optional import StageSpec, load_specs
    drafted = StageSpec.model_validate({
        "name": "conditions", "label": "Conditions", "intro": "Extract the conditions.", "per": "sample",
        "parameters": [{"column": "initial_pH"}, {"column": "initial_temperature_C", "unit": "°C"},
                       {"column": "buffer", "kind": "text"}]})
    rules = " ".join(drafted._field_rules())
    assert "row by row" in rules and "BEFORE the reaction" in rules and "a buffer described as 'pH 9.1'" in rules
    assert "STARTING SOLUTION" not in rules                     # only with the option (set when the pack has chemistry)
    on = drafted.model_copy(update={"by_starting_solution": True})
    assert "STARTING SOLUTION" in " ".join(on._field_rules())
    packs.activate("prebiotic_chemistry")
    conditions = load_specs()["experimental_conditions"]
    assert conditions.by_starting_solution and "row by row" in " ".join(conditions._field_rules())
    packs.activate("exoplanets")
    for spec in load_specs().values():
        text = " ".join(spec._field_rules())
        assert not spec.by_starting_solution and "row by row" not in text and "BEFORE the reaction" not in text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All starting-solution tests passed.")
