"""
The Flagged values window shows what needs a look (Mickey, 2026-11-12: whole-paper values like solution_type were
flagged on every row, and notes outnumbered doubts). Nothing is dropped -- Things to check lists every flag:
- Flag.minor, set where a flag is made: a step's 'medium' confidence; passes that disagreed where a majority agreed.
  The window shows minor notes only with "Show minor notes"; "Mark all flags checked" includes them.
- A flag about ONE value stated for several rows (one column, one value) is listed once, not on every row.
- Compounds named inside a quoted set label aren't the flag's subject (Riggi2023: ImpA in 'ImpA 15 mM with mineral').
- Logarithms of percentages aren't checked against 0-100% (Cleaves2008's log10 % yields are below 0).

Run with: python tests/test_flag_selectivity.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)


def test_minor_is_set_from_facts():
    from parameter_extractor.validation.plausibility_checks import Flag, _medium
    from parameter_extractor.voting import Disagreement, disagreement_flags, disagreements
    assert _medium("medium") and not _medium("low") and not _medium(None)
    clear = Disagreement("Experimental conditions", "vessel_material", "set A", "glass", {"glass": 2, "PTFE": 1}, 3, 3)
    split = Disagreement("Experimental conditions", "stirring", "set A", "yes", {"yes": 1, "no": 1, "none": 1}, 3, 3)
    once = Disagreement("Solution chemistry", "Kaolinite (initial)", "set B", "5 mg", {"5 mg": 1}, 3, 1)
    twice = Disagreement("Solution chemistry", "Pyrite (initial)", "set B", "5 mg", {"5 mg": 2}, 3, 2)
    got = dict((m.split(":")[1].split(" ")[1], minor) for m, minor in disagreements([clear, split, once, twice]))
    assert got == {"vessel_material": True, "stirring": False, "Kaolinite": False, "Pyrite": True}, got
    assert [m for m, _ in disagreements([clear])] == disagreement_flags([clear])      # same messages as before
    # flags saved before the field: read from the wording
    from parameter_extractor.run_folder import _flag
    assert _flag({"kind": "low_confidence", "message": "x = 'Wet' for every experiment set has confidence 'medium'."}
                 ).minor
    assert not _flag({"kind": "low_confidence", "message": "x has confidence 'low'."}).minor
    assert _flag({"kind": "pass_disagreement", "message": "S: x differs between passes in 1 place(s) -- the most "
                  "common value was kept. a: kept glass (2 of 3; others PTFE x1)."}).minor
    assert not _flag({"kind": "pass_disagreement", "message": "S: Kaolinite (initial) was found by only some of the 3 "
                      "passes in 1 place(s) -- kept. a: 5 mg, found by 1 of 3 passes."}).minor
    assert _flag({"kind": "low_confidence", "message": "x has confidence 'low'.", "minor": True}).minor
    assert Flag("out_of_range", "m").minor is False


def test_one_value_on_several_rows_is_listed_once():
    from parameter_extractor.gui.flagged_values import _one_value
    from parameter_extractor.validation.plausibility_checks import Flag
    values = {("001001001", "solution_type"): "Wet", ("001001002", "solution_type"): "Wet",
              ("001001001", "initial_temperature_C"): "100", ("001001002", "initial_temperature_C"): "100",
              ("001001001", "vessel"): "glass", ("001001002", "vessel"): "PTFE"}
    cells = {("001001001", "solution_type"), ("001001002", "solution_type")}
    assert _one_value(Flag("low_confidence", "m"), cells, values)
    assert not _one_value(Flag("conflicting_values", "m"),                       # questions each value: on its cells
                          {("001001001", "initial_temperature_C"), ("001001002", "initial_temperature_C")}, values)
    assert not _one_value(Flag("low_confidence", "m"), {("001001001", "vessel"), ("001001002", "vessel")}, values)
    assert not _one_value(Flag("low_confidence", "m"), {("001001001", "solution_type")}, values)      # one row


def test_set_labels_dont_name_the_subject():
    from parameter_extractor import flag_targets as ft
    from parameter_extractor.validation.plausibility_checks import Flag
    obs = [{"full_id": f"00100100{k}", "set_id": "001001", "column": c, "value": "5"}
           for k in (1, 2) for c in ("initial_ImpA_aq_mM", "initial_Kaolinite_s_mg")]
    index = ft.Index(obs, set_labels=["ImpA 15 mM with mineral, 3 days, ambient"])
    flag = Flag("pass_disagreement", "Solution chemistry: Kaolinite (initial) was found by only some of the 3 passes "
                                     "in 1 place(s) -- kept. ImpA 15 mM with mineral, 3 days, ambient: 5 mg, found by "
                                     "1 of 3 passes.")
    assert {col for _fid, col in ft.targets(flag, index)} == {"initial_Kaolinite_s_mg"}


def test_log_percentages_are_not_range_checked():
    from parameter_extractor.schemas.row_schema import ExtractedRow
    from parameter_extractor.validation.plausibility_checks import check_row
    row = ExtractedRow(full_id="001001001", set_id="001001", sample_id="001", entry_number=1, set_type="Independent",
                       paper_title="t", authors=[], year_published=2008, journal_published="j",
                       experiment_type="Batch", solution_type="Wet")
    row.extra["sampled_Gly-Gly_aq_log10_%yield"] = -2.06
    row.extra["sampled_Gly-Gly_aq_%yield"] = 130.0
    messages = " ".join(f.message for f in check_row(row))
    assert "log10" not in messages and "sampled_Gly-Gly_aq_%yield=130.0 is outside 0-100%" in messages


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All flag selectivity tests passed.")
