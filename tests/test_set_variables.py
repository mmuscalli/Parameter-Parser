"""
What distinguishes the rows of a set and what they should share (calculators/set_variables.py, Mickey 2026-11-17):
set_independent_variable / set_independent_value from the rows themselves, and set_gap flags for a starting compound
missing on a minority of a set's rows. No API calls.

Run with: python tests/test_set_variables.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor.calculators.set_variables import add_set_variables, set_gap_flags  # noqa: E402
from parameter_extractor.schemas.row_schema import ExtractedRow  # noqa: E402

BASE = dict(set_type="Independent", paper_title="t", authors=[], year_published=2008, journal_published="j",
            experiment_type="Batch", solution_type="Wet")


def _rows(set_no, values, **kw):
    out = []
    for i, extra in enumerate(values, 1):
        out.append(ExtractedRow(full_id=f"001{set_no:03d}{i:03d}", set_id=f"001{set_no:03d}", sample_id=f"{i:03d}",
                                entry_number=i, **BASE, **kw, extra={"sampled_Gly-Gly_aq_%yield": 1.0, **extra}))
    return out


def test_time_series_and_a_concentration_sweep():
    series = _rows(1, [{"duration_hr": t, "initial_Gly_aq_mM": 100.0, "initial_pH": 7.0} for t in (1, 2, 5)])
    sweep = _rows(2, [{"duration_hr": 24.0, "initial_NaCl_aq_mM": c, "initial_Gly_aq_mM": 100.0} for c in (0.5, 1.0)])
    single = _rows(3, [{"duration_hr": 24.0, "initial_Gly_aq_mM": 100.0}])
    rows = series + sweep + single
    add_set_variables(rows)
    assert [(r.extra["set_independent_variable"], r.extra["set_independent_value"]) for r in series] == \
        [("duration_hr", "1"), ("duration_hr", "2"), ("duration_hr", "5")]
    assert [(r.extra["set_independent_variable"], r.extra["set_independent_value"]) for r in sweep] == \
        [("initial_NaCl_aq_mM", "0.5"), ("initial_NaCl_aq_mM", "1")]
    assert single[0].extra["set_independent_variable"] == "" and single[0].extra["set_independent_value"] == ""


def test_several_variables_time_first_and_compounds_some_rows_lack():
    rows = _rows(1, [{"initial_temperature_C": 80.0, "duration_hr": 24.0, "initial_H2S_aq_mM": 50.0},
                     {"initial_temperature_C": 90.0, "duration_hr": 48.0, "initial_CH3SH_aq_mM": 50.0}])
    add_set_variables(rows)
    assert rows[0].extra["set_independent_variable"] == \
        "duration_hr; initial_temperature_C; initial_H2S_aq_mM; initial_CH3SH_aq_mM"
    assert rows[1].extra["set_independent_value"] == "48; 90; not given; 50"


def test_a_compound_missing_on_a_minority_is_flagged_not_filled():
    rows = _rows(1, [{"initial_Gly_aq_mM": 100.0, "initial_NaCl_aq_mM": 500.0, "duration_hr": t} for t in (1, 2, 3)]
                 + [{"initial_Gly_aq_mM": 100.0, "duration_hr": 4.0}])
    flags = set_gap_flags(rows)
    assert len(flags) == 1 and flags[0].kind == "set_gap", flags
    assert "initial_NaCl_aq_mM" in flags[0].message and "001001004" in flags[0].message and "500" in flags[0].message
    assert "initial_NaCl_aq_mM" not in rows[3].extra                       # never filled


def test_no_flag_for_substitutions_screens_or_cited_rows():
    # H2S in some runs, CH3SH in the others: a substitution
    swap = _rows(1, [{"initial_H2S_aq_mM": 50.0}] * 3 + [{"initial_CH3SH_aq_mM": 50.0}])
    # a reagent in 2 of 6 screening entries isn't missing from the other 4
    screen = _rows(2, [{"initial_borate_aq_mM": 500.0}] * 2 + [{"initial_CHES_aq_mM": 300.0}] * 4)
    cited = _rows(3, [{"initial_NaCl_aq_mM": 500.0}] * 3 + [{}], original_data_reference="Smith 1990")
    assert set_gap_flags(swap + screen + cited) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All set-variable tests passed.")
