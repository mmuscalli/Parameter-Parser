"""
Offline tests for the peptide naming convention (homopolymers
'<n>peptide_<AA>', heteropolymers 'AA1-AA2-...' in order), the calculated
total_sampled_peptides_yield, and the check that flag quotes are really the
paper's words. No API calls.

Run with: python tests/test_peptides_quotes.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor.calculators.peptide_totals import fill_total_peptide_yield
from parameter_extractor.ingestion.flatten_to_template import (
    column_for_solute, proposed_column_for_solute, row_to_template_dict, set_row_value)
from parameter_extractor.names import match_species
from parameter_extractor.registry import VariableRegistry, is_peptide_column
from parameter_extractor.schemas.chemistry import SoluteEntry
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.validation.plausibility_checks import Flag
from parameter_extractor.validation.quotes import PaperText, check_flag_quotes


def test_peptide_names():
    cases = {"Gly-Ala-Ala": "Gly-Ala-Ala", "H-Gly-L-Ala-OH": "Gly-Ala", "glycylalanine": "Gly-Ala",
             "Ala-Gly": "Ala-Gly", "GlyAla": "Gly-Ala", "alanylglycylvaline": "Ala-Gly-Val",
             "glycylglycylglycine": "3peptide_Gly", "Gly-Gly": "2peptide_Gly", "L-alanyl-L-alanine": "2peptide_Ala",
             "Gly14": "14peptide_Gly", "dialanine": "2peptide_Ala", "14peptide_Gly": "14peptide_Gly",
             # cyclic, homo- or heteromeric: cyclo_<AA1>-<AA2>-..., the template's DKP_<AA> included
             "DKP_Gly": "cyclo_Gly-Gly", "cyclo(Val-Gly)": "cyclo_Val-Gly", "c(L-Ala-L-Gly)": "cyclo_Ala-Gly",
             "glycine anhydride": "cyclo_Gly-Gly", "alanine diketopiperazine": "cyclo_Ala-Ala",
             "2,5-piperazinedione": "cyclo_Gly-Gly", "cyclo_Gly-Gly": "cyclo_Gly-Gly"}
    for name, expected in cases.items():
        assert match_species(name)[0] == expected, (name, match_species(name))
    for left_alone in ("cyclohexane", "Cl-", "MMP-Glycine", "Gly", "cyclo_Gly"):
        assert match_species(left_alone) in (None, (left_alone, "exact")), left_alone


def test_peptide_columns_are_constructed_not_listed():
    reg = VariableRegistry(None)
    for col in ("sampled_14peptide_Gly_%yield", "sampled_Gly-Ala-Ala_%yield", "initial_Ala-Gly_mM",
                "sampled_cyclo_Gly-Gly_%yield", "sampled_cyclo_Val-Gly_mM",
                "sampled_2peptide_Gly_%yield", "stock_Gly-Ala_mM"):
        assert reg.is_known_column(col), col
    for col in ("sampled_1peptide_Gly_mM", "sampled_Gly-Gly_mM", "sampled_Gly-Foo_mM", "sampled_Gly-Ala_aq_mM"):
        assert not is_peptide_column(col), col

    def entry(name, unit="%", role="sampled"):
        return SoluteEntry(name=name, in_controlled_vocab=False, phase="aq", role=role, concentration_value=1.0,
                           concentration_unit_raw=unit, quote="q", source="Table 1", confidence="high")
    assert column_for_solute(entry("Gly-Ala-Ala")) == "sampled_Gly-Ala-Ala_%yield"
    assert column_for_solute(entry("Gly-Ala", unit="mM")) == "sampled_Gly-Ala_mM"
    assert proposed_column_for_solute(entry("Ala-Gly", unit="mM", role="initial")) == "initial_Ala-Gly_mM"
    assert column_for_solute(entry("Total Gly in peptides")) == "total_sampled_peptides_yield"
    assert column_for_solute(entry("total peptide yield")) == "total_sampled_peptides_yield"


def _row(values: dict, full_id="001001001") -> ExtractedRow:
    row = ExtractedRow(full_id=full_id, set_id=full_id[:6], sample_id=full_id[6:], set_type="Independent",
                       entry_number=1, paper_title="t", authors=["a"], year_published=2000,
                       journal_published="j", experiment_type="Batch", solution_type="Wet")
    for col, v in values.items():
        set_row_value(row, col, v, CellSource(origin="chemistry", confidence="high"))
    return row


def test_total_peptide_yield_is_summed_or_checked():
    calc = _row({"sampled_2peptide_Gly_%yield": 2.77, "sampled_3peptide_Gly_%yield": 0.064,
                 "sampled_Gly-Ala-Ala_%yield": 0.5, "sampled_DKP_Gly_%yield": 9.0})
    stated_ok = _row({"sampled_2peptide_Gly_%yield": 1.0, "sampled_3peptide_Gly_%yield": 2.0,
                      "total_sampled_peptides_yield": 3.01}, "001002001")
    stated_partial = _row({"sampled_6peptide_Gly_%yield": 0.05, "total_sampled_peptides_yield": 2.56}, "001003001")
    none = _row({"sampled_2peptide_Gly_mM": 0.1}, "001004001")
    filled, differing = fill_total_peptide_yield([calc, stated_ok, stated_partial, none])
    assert filled == ["001001001"]
    d = row_to_template_dict(calc)
    assert d["total_sampled_peptides_yield"] == 12.334                   # cyclic (DKP) counts too
    assert d["sampled_cyclo_Gly-Gly_%yield"] == 9.0 and "sampled_DKP_Gly_%yield" not in d   # old name moved
    prov = calc.provenance["total_sampled_peptides_yield"]
    assert prov.origin == "calculated" and "2peptide_Gly 2.77 + 3peptide_Gly 0.064" in prov.source
    assert "Gly-Ala-Ala 0.5" in prov.source and "cyclo_Gly-Gly 9" in prov.source
    assert row_to_template_dict(stated_ok)["total_sampled_peptides_yield"] == 3.01      # stated: kept
    assert [x[0] for x in differing] == ["001003001"]                    # 0.05 listed vs 2.56 stated
    assert "total_sampled_peptides_yield" not in row_to_template_dict(none)


def test_value_quotes_are_marked_in_provenance_and_observations():
    from parameter_extractor.ingestion.observations import rows_to_observations
    from parameter_extractor.validation.quotes import check_row_quotes
    text = json.loads((ROOT / "runs" / "eder1994_auto" / "parsed_paper.json").read_text())["text"]
    row = _row({})
    set_row_value(row, "vessel_material", "glass", CellSource(origin="methodology", quote="heated in a glass flask"))
    set_row_value(row, "initial_temperature_C", 81.0,
                  CellSource(origin="methodology", quote="Table 1 conditions list the reaction temperature, 81 C"))
    assert check_row_quotes([row], text) == 1
    obs = {o.column: o for o in rows_to_observations([row])}
    assert obs["vessel_material"].quote_in_paper == "yes" and obs["initial_temperature_C"].quote_in_paper == "no"


def test_flag_quotes_must_be_the_papers_words():
    text = json.loads((ROOT / "runs" / "eder1994_auto" / "parsed_paper.json").read_text())["text"]
    paper = PaperText(text)
    # genuine, though the two columns' lines are interleaved in the text layer
    assert paper.contains("the solutions were heated in a glass flask without stirring on a "
                          "thermostatically controlled sand-bath with reflux cooler")
    assert not paper.contains("Table 1 conditions list the reaction temperature, 81 C")      # the model's words
    flag = Flag("low_confidence", "m", quote="Solutions were prepared in distilled water | "
                                            "Table 1 conditions list the reaction temperature, 81 C")
    check_flag_quotes([flag], text)
    assert flag.quote == "Solutions were prepared in distilled water"
    assert flag.unverified_quote == "Table 1 conditions list the reaction temperature, 81 C"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All peptide / quote tests passed.")
