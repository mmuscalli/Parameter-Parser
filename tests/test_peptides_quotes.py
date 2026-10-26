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
    # not in the text, but its source is a table the model saw as an image: said so, not "no"
    from parameter_extractor.validation.quotes import image_table_numbers
    tables = image_table_numbers({3: ["Table 1 Peptide formation"], 4: ["Table 2 Alkaline-earth"]})
    assert tables == {"1", "2"}
    set_row_value(row, "sampled_temperature_C", 81.0,
                  CellSource(origin="methodology", quote="Temperature (C) 100", source="Table 1"))
    check_row_quotes([row], text, tables)
    obs = {o.column: o for o in rows_to_observations([row])}
    assert obs["sampled_temperature_C"].quote_in_paper == "table image"
    assert obs["initial_temperature_C"].quote_in_paper == "no"           # no table source: model's wording


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
    cell = Flag("low_confidence", "m", quote="Temperature (C) 100", source="Table 1")
    check_flag_quotes([cell], text, {"1"})
    assert cell.quote is None and cell.table_image_quote == "Temperature (C) 100" and cell.unverified_quote is None



def test_quotes_are_capped_and_located_by_page():
    """Quotes and notes kept short (schemas.common), with the page the quote is on (Mickey, 2026-10-22)."""
    from parameter_extractor.schemas.common import QUOTE_MAX_CHARS, capped
    from parameter_extractor.schemas.row_schema import CellSource
    from parameter_extractor.validation.plausibility_checks import Flag
    from parameter_extractor.validation.quotes import PaperText, check_row_quotes, table_page_numbers
    long = "word " * 80
    assert len(CellSource(origin="x", quote=long).quote) <= QUOTE_MAX_CHARS + 2
    assert CellSource(origin="x", quote=long).quote.endswith(" …")
    assert capped("short quote", 50) == "short quote"
    f = Flag("low_confidence", "m", quote=long + " | " + "second quote", model_note="n " * 200)
    assert f.quote.endswith("| second quote") and f.quote.split(" | ")[0].endswith("…")
    assert len(f.model_note) < 160
    pages = ["Title page. Introduction text here.", "Methods: the solution was heated to 81 C for 3 days.",
             "Table 2. Yields\nGly2 1.5"]
    paper = PaperText("\n".join(pages), pages)
    assert paper.page_of("heated to 81 C for 3 days") == 2
    assert paper.page_of("heated to 81 C for …") == 2                 # a capped quote is still found
    assert paper.page_of("not in this paper at all, really not") is None
    from types import SimpleNamespace
    rows = [SimpleNamespace(provenance={"a": CellSource(origin="m", quote="heated to 81 C for 3 days", source="Methods"),
                                        "b": CellSource(origin="c", quote="Gly2 yield 1.5 percent", source="Table 2")})]
    check_row_quotes(rows, "\n".join(pages), {"2"}, pages, table_page_numbers({3: ["Table 2. Yields"]}))
    a, b = rows[0].provenance["a"], rows[0].provenance["b"]
    assert (a.quote_check, a.page) == ("in text", 2)
    assert (b.quote_check, b.page) == ("table image", 3)               # not in the text: its table's page


def test_quotes_must_name_the_species():
    """Chen2007 (2026-10-23): a table of structure drawings gives quotes like 'Entry 1 ... Yield (%) 2',
    a general procedure 'carboxylic acid (3 mmol)': the value is supported, its species inferred."""
    from parameter_extractor.validation.quotes import species_named_in, unnamed_species
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    from parameter_extractor.pipeline import _identity_flags
    named = [("isobutyric acid", "isobutyric acid 5 and cyclohexylamine 6"), ("Ala", "1 L-Alanine AA"),
             ("Phe-Ala", "FF, FA, AF, AA"), ("2peptide_Phe", "FF, FA, AF"), ("2peptide_Gly", "Gly2 yield 1.2"),
             ("K3[Fe(CN)6]", "potassium ferricyanide (30 mmol)"), ("Na2CO3", "sodium carbonate buffer"),
             ("CaCl2", "calcium chloride 2.5 mol dm-3"), ("NaCl", "3.33 mol dm-3 NaCl")]
    unnamed = [("N-isobutylisobutyramide", "Entry 1 ... Yield (%) 2"),
               ("isobutyric acid", "carboxylic acid (3 mmol), amine (3.3 mmol)"),
               ("Ala", "amino acids and/or peptides (1:1 ratio of each component, total 1 mmol)"), ("Gly", "")]
    for name, quote in named:
        assert species_named_in(name, quote), (name, quote)
    for name, quote in unnamed:
        assert not species_named_in(name, quote), (name, quote)
    chem = ChemistryExtraction.model_validate({"groups": [
        {"set": "Table 2", "sample": "Entry 1", "species": [
            {"nm": "N-isobutylisobutyramide", "r": "sampled", "ph": "aq", "v": 2, "u": "%", "q": "Entry 1 ... Yield (%) 2",
             "src": "Table 2, entry 1", "c": "medium", "how": "structure drawing, Table 2 entry 1"},
            {"nm": "isobutylamine", "r": "initial", "ph": "aq", "v": 3.3, "u": "mmol",
             "q": "isobutylamine (3.3 mmol)", "src": "Sect. 2", "c": "high"}]}],
        "unmapped_species": [], "added_solutions": [], "molar_ratios": []})
    assert [s.name for s in unnamed_species(chem.solutes)] == ["N-isobutylisobutyramide"]
    flags = _identity_flags(chem)
    assert len(flags) == 1 and flags[0].kind == "identity_not_quoted"
    assert "structure drawing, Table 2 entry 1" in flags[0].message
    from parameter_extractor.ingestion.flatten_to_template import _from_solute
    assert "[identified from: structure drawing, Table 2 entry 1]" in _from_solute(chem.solutes[0]).source


def test_table_results_expand_to_species_entries():
    """Chemistry tables in their own layout (2026-10-27, ~50-80% fewer output tokens): columns once,
    rows of values as printed -> the same species entries, quoted from the row label and value."""
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    chem = ChemistryExtraction.model_validate({"tables": [{"src": "Table 1", "c": "medium", "cols": [
        {"nm": "Gly", "r": "initial", "ph": "aq", "u": "M", "lbl": "[Gly]start"},
        {"nm": "2peptide_Gly", "r": "sampled", "ph": "aq", "u": "%", "lbl": "% (Gly)2"},
        {"nm": "cyclo_Gly-Gly", "r": "sampled", "ph": "aq", "u": "%", "lbl": "DKP", "how": "DKP = cyclo(Gly-Gly)"}],
        "rows": [{"set": "S", "sample": "a", "row": "1", "v": ["10\u22124", "2.77a", "nd"]},
                 {"set": "S", "sample": "b", "row": "2", "v": ["0.1", "\u22120.5", "detected"]},
                 {"set": "S", "sample": "c", "row": "3", "v": ["", "-", "n.d."]}]}],
        "groups": [{"set": "S", "species": [{"nm": "NaCl", "r": "initial", "ph": "aq", "v": 0.25, "u": "M",
                                             "q": "0.25 M NaCl", "src": "Methods", "c": "high"}]}],
        "unmapped_species": [], "added_solutions": [], "molar_ratios": [], "mixture_totals": []})
    by = {(s.name, s.sample_label): s for s in chem.solutes}
    assert by[("NaCl", None)].concentration_value == 0.25                          # groups still work
    gly2 = by[("2peptide_Gly", "a")]
    assert (gly2.concentration_value, gly2.concentration_unit_raw) == (2.77, "%")   # footnote letter dropped
    assert gly2.quote == "1 2.77a" and gly2.source == "Table 1, row 1, column % (Gly)2"
    assert gly2.confidence == "medium" and gly2.set_label == "S"
    assert by[("2peptide_Gly", "b")].concentration_value == -0.5                   # unicode minus
    dkp = by[("cyclo_Gly-Gly", "a")]
    assert dkp.concentration_value is None and dkp.detection == "not detected" and dkp.identified_by
    assert by[("cyclo_Gly-Gly", "b")].detection == "detected" and by[("cyclo_Gly-Gly", "c")].detection == "not detected"
    assert ("2peptide_Gly", "c") not in by and ("Gly", "c") not in by               # '-' and '' are no values
    assert by[("Gly", "b")].role == "initial" and by[("Gly", "b")].detection == ""   # per-sample start
    assert chem.tables == [] and chem.groups == []                                  # kept once, in solutes
    from parameter_extractor.schemas.chemistry import _cell_number
    assert _cell_number("1.2 \u00d7 10\u22123") == 1.2e-3 and _cell_number("3.5 x 10^2") == 350
    assert _cell_number("2.77a") == 2.77 and _cell_number("0.10*") == 0.1 and _cell_number(".5") == 0.5
    assert _cell_number("2.1 \u00b1 0.3") == 2.1                                    # the value; its error dropped
    for unclear in ("10\u22124", "<0.1", "1-4", "trace", ""):
        assert _cell_number(unclear) is None, unclear
    assert ("Gly", "a") not in by                                                    # '10−4': not guessed

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All peptide / quote tests passed.")
