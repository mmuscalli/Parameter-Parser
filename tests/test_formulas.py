"""
Formulas: calculations a research area declares without code (formulas.py, 2026-11-05) -- the expression language
(a whitelist, never eval), filling rows (missing inputs, check / keep / replace, order), grouped flags, the pack
check, the registry, a run through a pack made from the template, and the editor's Formulas tab. No API calls.

Run with: python tests/test_formulas.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from parameter_extractor import packs
from parameter_extractor.formulas import MISSING, FormulaError, apply_formulas, evaluate, formula_flags, parse


def test_expressions():
    v = {"temperature_C": 80, "sampled_Gly-Gly_aq_%yield": 2.5, "sampled_Gly-Gly-Gly_aq_%yield": 0.5, "pH": 6,
         "note": "detected", "zero": 0}
    cases = {"temperature_C + 273.15": 353.15, "`sampled_Gly-Gly_aq_%yield` * 2": 5.0,
             'sum_of("^sampled_.*_%yield$")': 3.0, 'count_of("^sampled_")': 2.0, 'mean_of("_%yield$")': 1.5,
             "first(nothing, temperature_C)": 80.0, "ifelse(pH < 7, 1, 0)": 1.0, "round(1/3, 3)": 0.333,
             "log10(1000)": 3.0, "max(pH, 7) - min(pH, 7)": 1.0, "2 * pi > 6 and not 0": 1.0, "-pH ** 2": -36.0}
    for expression, expected in cases.items():
        assert abs(evaluate(expression, v) - expected) < 1e-9, expression
    for expression in ("nothing + 1", "note * 2", 'sum_of("^none")', "ifelse(nothing > 1, 1, 0)"):
        assert evaluate(expression, v) is MISSING, expression
    for bad in ("__import__('os')", "temperature_C.real", "open('f')", "[1, 2]", "lambda: 1", "'text'",
                "a if b else c", "sum_of(pH)", "round(x=1)", "ifelse(1, 2)", 'sum_of("[")', "", "1 +"):
        try:
            parse(bad)
        except FormulaError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    try:
        evaluate("1 / zero", v)
        raise AssertionError("divided by zero")
    except ZeroDivisionError:
        pass


def _rows():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.flatten_to_template import set_row_value
    from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
    rows = []
    for i, (t, stated) in enumerate(((80.0, None), (100.0, 400.0), (None, None))):
        row = ExtractedRow(full_id=f"00100100{i + 1}", set_id="001001", sample_id=f"00{i + 1}",
                           set_type="Independent", entry_number=i + 1, paper_title="t", authors=["A"],
                           year_published=2024, journal_published="j", experiment_type="Batch", solution_type="Wet")
        if t is not None:
            set_row_value(row, "temperature_C", t, CellSource(origin="experimental conditions", confidence="medium"))
        if stated is not None:
            set_row_value(row, "temperature_K", stated, CellSource(origin="experimental conditions"))
        set_row_value(row, "zero_mM", 0.0)
        rows.append(row)
    return rows


def test_rows_filled_checked_and_flagged():
    from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
    formulas = [{"column": "temperature_K", "expression": "temperature_C + 273.15", "description": "in kelvin"},
                {"column": "temperature_F", "expression": "temperature_K * 9 / 5 - 459.67"},     # uses the one above
                {"column": "ratio", "expression": "1 / zero_mM"}]
    rows = _rows()
    outcomes = apply_formulas(rows, formulas)
    records = [row_to_template_dict(r) for r in rows]
    assert [r.get("temperature_K") for r in records] == [353.15, 400.0, None]      # stated 400 kept (check)
    assert records[0]["temperature_F"] == 176.0 and records[1]["temperature_F"] == 260.33
    assert outcomes[0].filled == ["001001001"] and outcomes[0].differing == [("001001002", 400.0, 373.15)]
    assert len(outcomes[2].failed) == 3 and outcomes[2].failed[0][1] == "division by zero"
    prov = rows[0].provenance["temperature_K"]
    assert prov.origin == "calculated" and "temperature_C = 80" in prov.source and prov.confidence == "medium"
    kinds = [f.kind for f in formula_flags(outcomes)]
    assert kinds == ["derived_value", "conflicting_values", "derived_value", "not_calculated"]
    # keep: no comparison; replace: the formula's value wins
    rows = _rows()
    o = apply_formulas(rows, [dict(formulas[0], if_present="keep")])[0]
    assert o.differing == [] and row_to_template_dict(rows[1])["temperature_K"] == 400.0
    rows = _rows()
    apply_formulas(rows, [dict(formulas[0], if_present="replace")])
    assert row_to_template_dict(rows[1])["temperature_K"] == 373.15


def test_check_and_registry():
    from parameter_extractor.pack_editing import PackDraft, check
    from parameter_extractor.registry import VariableRegistry
    with tempfile.TemporaryDirectory() as tmp:
        packs.add_search_dir(Path(tmp))
        pack = packs.create_pack("formula_area", "Formulas", base=Path(tmp))
        d = PackDraft.load(pack.folder)
        assert any("template's example formula" in p.message for p in check(d))
        d.manifest["formulas"] = [
            {"column": "a_K", "expression": "b_K + 1"},                                    # b_K filled later
            {"column": "b_K", "expression": "temperature_C + 273.15", "description": "kelvin"},
            {"column": "c", "expression": "c + 1", "description": "x"},                     # its own column
            {"column": "d", "expression": "open(1)", "description": "x"},
            {"column": "e", "expression": "no_such_column * 2", "description": "x", "if_present": "sometimes"},
            {"column": "b_K", "expression": "1", "description": "x"}]                       # same column twice
        messages = [str(p) for p in check(d)]
        for expect in ("filled by a LATER formula", "uses its own column", "unknown function 'open'",
                       "doesn't have: no_such_column", "'if a value exists' must be one of",
                       "another formula fills the same column"):
            assert any(expect in m for m in messages), (expect, messages)
        assert "temperature_K" in VariableRegistry(None, pack=pack).standard_columns       # a known column


def test_a_pack_with_formulas_runs():
    """The template's example formula through a whole (stand-in) run: the column is filled and flagged."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_template_pack import test_a_pack_created_from_the_template_runs
    test_a_pack_created_from_the_template_runs()           # it asserts temperature_K = 353.15 on every row


def test_formulas_tab():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import PackEditor
    from parameter_extractor.pack_editing import PackDraft
    with tempfile.TemporaryDirectory() as tmp:
        packs.add_search_dir(Path(tmp))
        pack = packs.create_pack("tab_area", "Tab", base=Path(tmp))
        editor = PackEditor(pack.folder)
        assert editor.tabs.tabText(editor.tabs.count() - 1).startswith("Check")
        assert "Formulas" in [editor.tabs.tabText(i) for i in range(editor.tabs.count())]
        assert editor.f_table.rowCount() == 1                                       # the template's example
        editor._add_formula({})
        editor.f_table.item(1, 0).setText("yield_fraction")
        editor.f_table.item(1, 1).setText("product_yield_pct / 100")
        editor.f_table.setCurrentCell(1, 1)
        editor._show_formula_inputs()
        assert editor.f_inputs.rowCount() == 1 and editor.f_inputs.item(0, 0).text() == "product_yield_pct"
        editor.f_inputs.item(0, 1).setText("42")
        assert editor.f_result.text() == "Result: yield_fraction = 0.42"
        editor.f_table.item(1, 1).setText("product_yield_pct /")
        editor._try_formula()
        assert "not a usable formula" in editor.f_result.text()
        editor.f_table.item(1, 1).setText("product_yield_pct / 100")
        editor._move_formula(-1)
        assert editor.save()
        saved = PackDraft.load(pack.folder).manifest["formulas"]
        assert [f["column"] for f in saved] == ["yield_fraction", "temperature_K"]
        assert saved[0] == {"column": "yield_fraction", "expression": "product_yield_pct / 100", "description": "",
                            "if_present": "check"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All formula tests passed.")
