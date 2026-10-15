"""
Offline tests for flag grouping (one low-confidence flag per field across
sets), the "concentration not stated" flag, and dropping methodology
parameters that only repeat amounts the chemistry step records (one
quantity, one variable). No API calls.

Run with: python tests/test_flags_duplicates.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor.ingestion.duplicates import amounts, drop_repeated_amounts
from parameter_extractor.ingestion.new_variables import collect_new_variables
from parameter_extractor.registry import VariableRegistry
from parameter_extractor.schemas.chemistry import AddedSolution, ChemistryExtraction, SoluteEntry
from parameter_extractor.schemas.methodology import Methodology, OtherParameter, SetOverride
from parameter_extractor.validation.plausibility_checks import check_extraction
from test_pipeline_offline import REPLAY_DIR


def _methods():
    meth = Methodology.model_validate_json((REPLAY_DIR / "methodology.output.json").read_text())
    meth.other_parameters, meth.per_set_overrides = [], []
    return meth


def _solute(name, value, unit="mM", **kw):
    return SoluteEntry(name=name, in_controlled_vocab=False, phase="aq", role="initial",
                       concentration_value=value, concentration_unit_raw=unit if value is not None else None,
                       concentration_mM=value, quote="q", source="Methods", confidence=kw.pop("confidence", "high"),
                       **kw)


def _kim():
    return ChemistryExtraction(paper_id="p", solutes=[
        _solute("ribose 1,2-cyclic phosphate", 15, concentration_basis="stock", stock_solution="ribose stock"),
        _solute("CaCl2", 15, concentration_basis="stock", stock_solution="calcium chloride solution"),
        _solute("cytosine", 3.75, concentration_basis="stock", stock_solution="nucleobase solution"),
        _solute("uracil", None, set_label="U", confidence="medium"),
    ], added_solutions=[AddedSolution(solution="ribose stock", volume="5 µL"),
                        AddedSolution(solution="nucleobase solution", volume="20 µL"),
                        AddedSolution(solution="calcium chloride solution", volume="8 µL")])


def _param(name, value, set_label=None):
    return OtherParameter(name=name, value=value, set_label=set_label, quote="q", source="Methods",
                          confidence="high")


def test_low_confidence_flags_are_grouped_per_field():
    meth = _methods()
    for label, t in (("a", 100), ("b", 85), ("c", 125)):
        meth.per_set_overrides.append(SetOverride(set_label=label, field_name="sampled_temperature_C", value=t,
                                                  confidence="medium", quote=f"{t} C", source="Table 1"))
    meth.per_set_overrides.append(SetOverride(set_label="a", field_name="initial_pH", value=7, confidence="low",
                                              quote="pH 7", source="Methods"))
    flags = [f for f in check_extraction(meth, ChemistryExtraction(paper_id="p", solutes=[]))
             if f.kind == "low_confidence" and "methodology." not in f.message]
    assert len(flags) == 2
    temp = next(f for f in flags if "sampled_temperature_C" in f.message)
    assert "in 3 sets" in temp.message and "'b' = 85" in temp.message
    assert temp.quote == "100 C | 85 C | 125 C" and temp.source == "Table 1"
    assert next(f for f in flags if "initial_pH" in f.message).message.startswith("initial_pH = 7 for set 'a'")


def test_missing_concentration_has_its_own_flag():
    flags = check_extraction(_methods(), _kim())
    missing = [f for f in flags if f.kind == "concentration_not_stated"]
    assert len(missing) == 1 and "uracil" in missing[0].message and "None" not in missing[0].message
    assert not any("uracil" in f.message for f in flags if f.kind == "low_confidence")


def test_amounts_found_in_text():
    assert [(k, v) for k, v, _ in amounts("5 µL ribose (15 mM), 0.02 mL, 0.5 M ammonia, 3–96 h")] == [
        ("volume", 5.0), ("concentration", 15.0), ("volume", 20.0), ("concentration", 500.0)]


def test_repeated_amounts_are_dropped_once():
    meth, chem = _methods(), _kim()
    meth.other_parameters = [
        _param("nucleobase solution volume", "20 µL, 3.75 mM in case of 1:1 molar ratio"),   # repeat
        _param("calcium chloride solution volume", "8 µL, 15 mM"),                           # repeat (via solution)
        _param("guanine medium", "0.5 M ammonia"),                                           # ammonia not recorded
        _param("redissolution volume", "0.3 mL water"),                                      # not a repeat
        _param("total reaction volume", "33 µL"),                                            # a different quantity
        _param("mystery solution", "15 mM"),                                                 # equal number, unlinked
        _param("heating", "lids open until dry"),                                            # no amounts
    ]
    dropped = drop_repeated_amounts(meth, chem)
    assert [d.parameter.name for d in dropped] == ["nucleobase solution volume", "calcium chloride solution volume"]
    assert "CaCl2 15 mM" in dropped[1].matches and "ribose" not in dropped[1].matches
    assert [p.name for p in meth.other_parameters] == ["guanine medium", "redissolution volume",
                                                       "total reaction volume", "mystery solution", "heating"]


def test_each_solution_volume_is_one_review_variable():
    meth, chem = _methods(), _kim()
    meth.other_parameters = [_param("nucleobase solution volume", "20 µL")]
    drop_repeated_amounts(meth, chem)
    new = [v for v in collect_new_variables(meth, chem, VariableRegistry(None)) if v.kind == "parameter"]
    assert [(v.name, v.value_text, v.proposed_column) for v in new] == [
        ("volume added: ribose stock", "5 µL", "added_ribose_stock_volume_uL"),
        ("volume added: nucleobase solution", "20 µL", "added_nucleobase_solution_volume_uL"),
        ("volume added: calcium chloride solution", "8 µL", "added_calcium_chloride_solution_volume_uL")]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All flag / duplicate tests passed.")
