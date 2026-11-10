"""
Tables read by the app (2026-11-07, ingestion/table_grid.py): cells from the PDF's text layer (or an arXiv text's
' | ' rows) as numbered grids; the chemistry step and the table-reading stages answer with a mapping (grid column
-> variable, grid row -> sample) and the app reads the cells. No API calls; the PDF checks skip when a paper isn't
on this computer.

Run with: python tests/test_table_grids.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs
from parameter_extractor.ingestion import table_grid as tg

PAPERS = ROOT.parent / "Paper Files" / "Paper Lists"


def _grids(pdf: Path):
    from parameter_extractor.ingestion.pdf_parser import parse_pdf
    from parameter_extractor.ingestion.table_finder import find_tables
    parsed = parse_pdf(str(pdf))
    with tempfile.TemporaryDirectory() as tmp:
        tables = find_tables(str(pdf), sorted(parsed.table_pages), Path(tmp), rotations=parsed.page_rotations)
    return tg.pdf_grids(str(pdf), tables)


def test_cells():
    c = tg.cell_value
    assert c("13.96").value == 13.96
    assert (c("1.23 ± 0.05").err_plus, c("1.23 ± 0.05").err_minus) == (0.05, -0.05)
    v = c("1.23^{+0.05}_{-0.04}")
    assert (v.value, v.err_plus, v.err_minus) == (1.23, 0.05, -0.04)
    v = c("$1.23_{-0.04}^{+0.05}$")                    # arXiv's LaTeX order
    assert (v.value, v.err_plus, v.err_minus) == (1.23, 0.05, -0.04)
    assert (c("< 3.5").value, c("< 3.5").limit) == (3.5, 1) and c("> 13").limit == -1
    assert (c("5-10").value, c("5-10").high) == (5, 10)
    assert c("10^{–4}").value == 1e-4 and c("2 × 10^{-3}").value == 0.002      # powers, not uncertainties
    assert c("10-4").value is None                     # a lost superscript stays unread
    assert c("ND").detected == "not detected" and c("17.7^{a}").value == 17.7 and c("0.03*").value == 0.03
    assert (c("45 °C").value, c("45 °C").unit) == (45, "°C")
    assert tg.plain("10^{–4}") == "0.0001" and tg.plain("ND") == "nd" and tg.plain("17.7^{a}") == "17.7"


def test_usable():
    good = [["Oligomer", "Cycle 1", "Cycle 2"], ["Gly2", "13.96", "10.26"], ["Gly3", "10.4", "7.7"]]
    assert tg.usable(good)
    split = [["Entry", "x"], ["1 45 °C 4 hrs", "4.5"], ["2 45 °C 1 day", "22.7"], ["3 55 °C 2 days", "30.7"]]
    assert not tg.usable(split)                        # a column split in the wrong place
    assert not tg.usable([["a", "b"], ["1", "2"]])     # one numeric row
    assert tg.usable(good + [["A mixture of ribose 1,2-cyclic phosphate 3 (5 µL, 15 mM)", "", ""]])   # caption prose


def test_text_grids():
    text = ("Results.\nTable 3. Orbital parameters.\n\nParameter | HD 1 b | HD 2 b\n\nP (d) | 12.5 | $7.1_{-0.2}^{+0.3}$\n"
            "e | 0.1 | < 0.05\n\nMore text.")
    grids = tg.text_grids(text)
    assert [g.table_id for g in grids] == ["Table 3"] and grids[0].cell(1, 2) == "$7.1_{-0.2}^{+0.3}$"
    assert "r1: [0] P (d) [1] 12.5" in grids[0].render()


def test_reference_pdfs():
    cases = {"Initial Easy Papers/Truman2024/truman2024.pdf": {"Table 1": ("Gly2", "13.96"), "Table 2": None},
             "Nucleotide Papers/Kim2017/kim2017.pdf": {"Table 1": ("1", "17.7"), "Table 2": ("1", "4.5")},
             "Kim2019/kim2019.pdf": {"Table 1": ("1:1", "1.7")},
             "Initial Easy Papers/faisal2005/faisal2005.pdf": {"Table 1": ("240", "6.84")},
             "Initial Easy Papers/Eder1994/eder1994.pdf": {}}            # a scan: OCR text, no grids
    for rel, want in cases.items():
        pdf = PAPERS / rel
        if not pdf.is_file():
            print(f"SKIP: {rel}")
            continue
        grids = {g.table_id: g for g in _grids(pdf)}
        assert set(grids) == set(want), (rel, set(grids))
        for table, cells in want.items():
            if cells:
                label, value = cells
                assert any(r and r[0] == label and value in r for r in grids[table].rows), (rel, table)
    if (PAPERS / "Initial Easy Papers/Truman2024/truman2024.pdf").is_file():
        t2 = {g.table_id: g for g in _grids(PAPERS / "Initial Easy Papers/Truman2024/truman2024.pdf")}["Table 2"]
        assert any(tg.cell_value(r[0]).value == 1e-4 for r in t2.rows)    # 10^-4 M: the superscript kept


def test_chemistry_mapping():
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    grid = tg.Grid("G1", "Table 1", "4", "", [["Oligomer", "Cycle 1", "Cycle 2"], ["Gly2", "13.96", "10.26"],
                                              ["Gly3", "10.4^{a}", "ND"]])
    answer = ChemistryExtraction.model_validate({"tables": [{"src": "Table 1", "grid": "G1", "c": "high",
        "cols": [{"nm": "Gly-Gly", "r": "sampled", "ph": "aq", "u": "%", "lbl": "Cycle 1", "gc": 1}],
        "rows": [{"set": "S", "sample": "c1", "row": "Gly2", "gr": 1}, {"set": "S", "sample": "c2", "row": "Gly3",
                                                                          "gr": 2}]}]})
    assert answer.solutes == [] and len(answer.tables) == 1          # waits for the grid (saved like this)
    assert answer.fill_grids([grid]) == []
    assert [(s.sample_label, s.concentration_value) for s in answer.solutes] == [("c1", 13.96), ("c2", 10.4)]
    assert answer.solutes[0].source == "Table 1, row Gly2, column Cycle 1" and not answer.tables
    missing = ChemistryExtraction.model_validate({"tables": [{"src": "Table 9", "grid": "G7", "c": "high",
        "cols": [{"nm": "x", "r": "sampled", "ph": "aq", "u": "%", "lbl": "x", "gc": 1}],
        "rows": [{"set": "S", "sample": "a", "row": "1", "gr": 1}]}]})
    assert "G7" in missing.fill_grids([grid])[0]


def test_stage_mapping():
    from parameter_extractor.stages.optional import fill_grids, load_specs
    packs.activate("exoplanets")
    try:
        spec = load_specs()["planet_parameters"]
        _, Result = spec.models()
        grid = tg.Grid("G1", "Table 3", "9", "", [["Parameter", "HD 1 b"], ["P (days)", "12.5 ± 0.1"],
                                                  ["e", "0.10^{+0.02}_{-0.03}"], ["K (m/s)", "< 3.5"]])
        answer = Result.model_validate({"grids": [{"grid": "G1", "rows": [{"r": 1, "set": "HD 1", "sample": "HD 1 b"}],
                                                   "cols": [{"c": 1, "col": "pl_orbper", "u": "days"}]},
                                                  {"grid": "G1", "rows": [{"r": 2, "set": "HD 1", "sample": "HD 1 b"}],
                                                   "cols": [{"c": 1, "col": "pl_orbeccen", "u": ""}]}]})
        assert fill_grids(spec, answer, [grid]) == []
        items = {i.parameter: i for i in answer.parameters}
        assert (items["pl_orbper"].value, items["pl_orbper"].err_plus, items["pl_orbper"].unit) == (12.5, 0.1, "days")
        assert (items["pl_orbeccen"].err_plus, items["pl_orbeccen"].err_minus) == (0.02, -0.03)
        assert items["pl_orbper"].sample_label == "HD 1 b" and items["pl_orbper"].source.startswith("Table 3, row P")
        # a parameter table (rows = parameters, a column per planet), as arXiv prints them
        g2 = tg.Grid("G2", "Table 5", "", "", [["Parameter", "Prior", "Value"],
                                               ["Orbital period (days)", "U[1.2,1.8]", "$1.5574_{-4.2e-7}^{+3.6e-7}$"],
                                               ["Planet mass ( $M_{\\rm J}$ )", "$\\cdots$", "$0.169_{-0.009}^{+0.008}$"]])
        answer = Result.model_validate({"grids": [{"grid": "G2", "prows": [{"r": 1, "col": "pl_orbper", "u": "days"},
                                                                           {"r": 2, "col": "pl_massj", "u": "M_J"},
                                                                           {"r": 2, "col": "pl_unknown", "u": ""}],
                                                   "scols": [{"c": 2, "set": "TOI-1", "sample": "TOI-1 b"}]}]})
        assert fill_grids(spec, answer, [g2]) == []
        items = {i.parameter: i for i in answer.parameters}
        assert (items["pl_massj"].value, items["pl_massj"].err_plus, items["pl_massj"].err_minus) == (0.169, 0.008, -0.009)
        assert items["pl_orbper"].sample_label == "TOI-1 b" and items["pl_orbper"].unit == "days"
    finally:
        packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS:", name)
    print("All table-grid tests passed.")
