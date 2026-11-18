"""
Tables probably read incompletely (calculators/plan_checks.py, Mickey 2026-11-17: Huber1998's Table 1 -- a pH per run,
legible -- came back without pH): a set whose row plan says a condition differs per row, but whose rows have none (or
one value). Only explicit evidence counts; a set's own single value ('T = 50 C') never does. No API calls.

Run with: python tests/test_plan_checks.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor.calculators.plan_checks import plan_mismatch_flags, varies_evidence  # noqa: E402
from parameter_extractor.schemas.row_schema import ExtractedRow  # noqa: E402
from parameter_extractor.schemas.structure_plan import StructurePlan  # noqa: E402

LABELS = {"temperature": "initial_temperature_C", "time": "duration_hr", "pressure": "initial_pressure_bar",
          "pH": "initial_pH"}


def test_what_counts_as_the_plan_saying_a_condition_varies():
    assert varies_evidence("pH", "amino acid = L-Tyr; H2S; pH varies; 1 day and 4 days") == "word"
    assert varies_evidence("pH", "sulfur source, Na2HPO4 presence, pH per run; 1 day") == "word"
    assert varies_evidence("pH", "initial pH (2.0, 9.0, 10.5) at 0.025 M glycine, 94 C, 24 h") == "list"
    assert varies_evidence("temperature", "set temperature = 200, 250, 300, 350, 400 C") == "list"
    assert varies_evidence("pH", "pH 7.5-9.9; 1 day") == "range"
    # a set's own single value, and numbers that belong to something else
    assert varies_evidence("temperature", "amino acid = glycine, T = 50 C; sample = catalyst") == ""
    assert varies_evidence("temperature", "cation Na+, 3.33 mol/dm3, 81 C") == ""
    assert varies_evidence("pH", "poly(G) 10.6 mM, pH 11.4, 70 C, incubation time") == ""
    assert varies_evidence("temperature", "initial pH (1.4 vs 2.6); radioactive reactant = 2-14C glycine") == ""


def _plan(varies, n):
    return StructurePlan.model_validate({"experiment_sets": [{
        "set_label": "Table 1 block", "set_type": "Independent", "varying_condition_summary": varies,
        "source_table_or_section": "Table 1", "samples": [{"sample_label": f"Run {i}"} for i in range(1, n + 1)]}],
        "n_rows": n})


def _rows(n, **extra):
    base = dict(set_type="Independent", paper_title="t", authors=[], year_published=1998, journal_published="j",
                experiment_type="Batch", solution_type="Wet")
    return [ExtractedRow(full_id=f"001001{i:03d}", set_id="001001", sample_id=f"{i:03d}", entry_number=i, **base,
                         extra={"sampled_Gly-Gly_aq_mM": 1.0, **{k: (v(i) if callable(v) else v)
                                                                   for k, v in extra.items()}})
            for i in range(1, n + 1)]


def test_a_table_without_its_per_row_condition_is_flagged():
    flags = plan_mismatch_flags(_rows(4), _plan("H2S vs CH3SH; pH per run; 1 day", 4), LABELS)
    assert len(flags) == 1 and flags[0].kind == "plan_mismatch" and "no initial_pH" in flags[0].message
    flags = plan_mismatch_flags(_rows(4, initial_pH=9.1), _plan("pH per run", 4), LABELS)
    assert len(flags) == 1 and "the same initial_pH on every row (9.1)" in flags[0].message
    # read per row: no flag
    assert plan_mismatch_flags(_rows(4, initial_pH=lambda i: 7.0 + i), _plan("pH per run", 4), LABELS) == []


def test_ranges_and_single_values_are_not_flagged_when_rows_have_the_value():
    # 'pH 7.5-9.9' with one value on every row may be one imprecise condition; with no value at all it's flagged
    assert plan_mismatch_flags(_rows(3, initial_pH="7.5:9.9"), _plan("pH 7.5-9.9", 3), LABELS) == []
    assert len(plan_mismatch_flags(_rows(3), _plan("pH 7.5-9.9", 3), LABELS)) == 1
    assert plan_mismatch_flags(_rows(3, initial_temperature_C=50.0), _plan("T = 50 C; catalyst varies", 3),
                               LABELS) == []


def test_a_step_answer_without_the_per_row_condition_is_read_again():
    """stages/repair.py: before rows are built, a set whose plan says pH differs per run but whose conditions answer
    gives no per-run pH gets ONE follow-up request -- only those sets (plan ids) and that column -- and its per-row
    values join the answer. Nothing is asked when the answer has them."""
    from types import SimpleNamespace
    from unittest.mock import patch
    from parameter_extractor import packs
    from parameter_extractor.stages import optional, repair
    packs.activate("prebiotic_chemistry")
    spec = optional.load_specs()["experimental_conditions"]
    _Item, Result = spec.models()
    plan = StructurePlan.model_validate({"experiment_sets": [
        {"set_label": "Table 1 block", "set_type": "Independent", "varying_condition_summary": "H2S vs CH3SH; pH per run",
         "source_table_or_section": "Table 1", "samples": [{"sample_label": f"Run {i}"} for i in (1, 2, 3)]},
        {"set_label": "Other block", "set_type": "Independent", "varying_condition_summary": "T = 50 C",
         "source_table_or_section": "Table 2", "samples": [{"sample_label": "A"}, {"sample_label": "B"}]}],
        "n_rows": 5})
    value = lambda col, v: {"col": col, "v": v, "u": "", "q": "q", "src": "Table 1", "c": "high"}   # noqa: E731
    answer = Result.model_validate({"rows": [{"set": "", "values": [value("initial_temperature_C", 100)]}],
                                    "notes": "pH per run not entered"})
    found = repair.incomplete(plan, [(spec, answer)], packs.current().manifest.label_columns)
    assert [(s.name, sets, cols) for s, sets, cols in found] == [("experimental_conditions", ["S1"], ["initial_pH"])]
    narrowed = repair.repair_spec(spec, ["S1"], ["initial_pH"])
    assert narrowed.name == "experimental_conditions_repair" and [p.column for p in narrowed.parameters] == \
        ["initial_pH"] and "S1" in narrowed.rules[-1] and not narrowed.open_ended
    _I2, R2 = narrowed.models()
    again = R2.model_validate({"rows": [{"set": "Table 1 block", "sample": f"Run {i}", "values": [value("initial_pH", ph)]}
                                        for i, ph in ((1, 7.5), (2, 8.5), (3, 8.8))], "notes": ""})
    ex = SimpleNamespace(structure=plan, optional={spec.name: (spec, answer)})
    ex.optional_list = [(spec, answer)]
    ctx = SimpleNamespace(total_steps=0, note=lambda *a: None)
    with patch.object(optional, "run_optional_stage", lambda *a, **k: again) as _:
        notes = repair.repair_steps(ctx, ex, "text", None, packs.current().manifest.label_columns)
    assert "3 value(s) added" in notes[0]
    values = optional.optional_values(spec, answer, plan)
    assert {k[1]: v.value for k, v in values.items() if k[2] == "initial_pH"} == {"Run 1": 7.5, "Run 2": 8.5,
                                                                                 "Run 3": 8.8}
    assert repair.incomplete(plan, [(spec, answer)], packs.current().manifest.label_columns) == []   # complete now


def test_a_failed_repair_is_a_note_not_a_failed_run():
    from types import SimpleNamespace
    from unittest.mock import patch
    from parameter_extractor import packs
    from parameter_extractor.stages import optional, repair
    packs.activate("prebiotic_chemistry")
    spec = optional.load_specs()["experimental_conditions"]
    _Item, Result = spec.models()
    plan = StructurePlan.model_validate({"experiment_sets": [
        {"set_label": "B", "set_type": "Independent", "varying_condition_summary": "pH per run",
         "source_table_or_section": "Table 1", "samples": [{"sample_label": "1"}, {"sample_label": "2"}]}], "n_rows": 2})
    answer = Result.model_validate({"rows": [], "notes": ""})
    ex = SimpleNamespace(structure=plan, optional={spec.name: (spec, answer)}, optional_list=[(spec, answer)])

    def fail(*a, **k):
        raise RuntimeError("no saved answer")
    with patch.object(optional, "run_optional_stage", fail):
        notes = repair.repair_steps(SimpleNamespace(total_steps=0, note=lambda *a: None), ex, "t", None,
                                    packs.current().manifest.label_columns)
    assert "failed" in notes[0] and answer.rows == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All row-plan check tests passed.")
