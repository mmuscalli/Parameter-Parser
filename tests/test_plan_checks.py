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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All row-plan check tests passed.")
