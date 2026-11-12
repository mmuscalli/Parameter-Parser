"""
Offline tests for Mickey's Cleaves2008 round (2026-11-12): values the paper calculated (calculated_ columns), rows with
products but no starting composition, scientific notation on table images, "Replace whole column with value" and
Ctrl+Z in the Flagged values window, a row's table / figure for any of its cells, and "Find similar points" clicked
outside a plot frame (it crashed).

Run with: python tests/test_cleaves_round.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client, corrections as corr, flag_targets as ft, packs, run_folder  # noqa: E402
from parameter_extractor.pipeline import run_pipeline, starting_composition_flags  # noqa: E402
from test_pipeline_offline import PDF, _config, _have_inputs, _replay_send  # noqa: E402

RIGGI = Path(__file__).resolve().parents[2] / "Paper Files" / "Test Paper List" / "Riggi2023.pdf"


def test_values_the_paper_calculated():
    """Cleaves2008 Table 1 'Calculated equilibrium concentrations': `calc` puts a value in calculated_<name>_<phase>_
    <measure>, known wherever the measured / starting column is, in its own block, out of the peptide totals."""
    from parameter_extractor import variable_categories as vc
    from parameter_extractor.column_order import ColumnOrder
    from parameter_extractor.ingestion.flatten_to_template import column_for_solute, species_alias_name
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
    packs.activate("prebiotic_chemistry")
    reg = VariableRegistry(None, pack="prebiotic_chemistry")
    e = SoluteEntry.model_validate({"nm": "Gly-Gly", "r": "sampled", "ph": "aq", "v": 7e-14, "u": "M", "mM": 7e-11,
                                    "calc": True, "q": "", "src": "", "c": "high"})
    assert column_for_solute(e, reg) == "calculated_Gly-Gly_aq_mM" and e.variable == "Gly-Gly calc"
    assert species_alias_name(e) == "calculated Gly-Gly"
    assert reg.is_known_column("calculated_Gly_aq_mM") and not reg.is_known_column("calculated_Zz9_aq_mM")
    assert vc.for_source("species", "calculated") == "calculated_values"
    assert ColumnOrder(packs.current()).category_of("calculated_Gly-Gly_aq_mM") == "calculated_values"
    # a table column marked calc: every cell of it
    chem = ChemistryExtraction.model_validate({"paper_id": "x", "tables": [{"src": "Table 1", "c": "high", "cols": [
        {"nm": "Gly-Gly", "r": "sampled", "ph": "aq", "u": "M", "lbl": "Gly2", "calc": True}],
        "rows": [{"set": "S", "sample": "a", "row": "25 C", "v": ["7e-14"]}]}]})
    assert [s.calculated for s in chem.solutes] == [True]
    from parameter_extractor.calculators.peptide_totals import fill_total_peptide_yield
    from parameter_extractor.schemas.row_schema import ExtractedRow
    row = ExtractedRow(full_id="001001001", set_id="001001", sample_id="001", set_type="Independent", entry_number=1,
                       paper_title="t", authors=[], year_published=2008, journal_published="j", experiment_type="Batch",
                       solution_type="Wet", extra={"calculated_Gly-Gly_aq_%yield": 5.0})
    fill_total_peptide_yield([row])
    assert "total_sampled_peptides_yield" not in row.extra                    # calculated values aren't measured totals


def test_products_without_a_starting_composition():
    from parameter_extractor.schemas.row_schema import ExtractedRow
    base = dict(set_type="Independent", paper_title="t", authors=[], year_published=2008, journal_published="j",
                experiment_type="Batch", solution_type="Wet")
    rows = [ExtractedRow(full_id=f"00100{s}00{i}", set_id=f"00100{s}", sample_id=f"00{i}", entry_number=i, **base,
                         extra={"data_location": loc, "sampled_Gly-Gly_aq_%yield": 1.0, **extra})
            for s, loc, extra in (("1", "Figure. 2", {}), ("2", "Table. 1", {"initial_Gly_aq_mM": 100.0}))
            for i in (1, 2)]
    flags = starting_composition_flags(rows)
    assert len(flags) == 1 and flags[0].message.startswith("Figure 2: 2 row(s)") and "001001001" in flags[0].message
    obs = [{"full_id": r.full_id, "set_id": r.set_id, "column": "sampled_Gly-Gly_aq_%yield", "value": "1.0"}
           for r in rows]
    cells, precise = ft.located(flags[0], ft.Index(obs))                     # placed on the rows it lists
    assert precise and {f for f, _c in cells} == {"001001001", "001001002"}


def test_scientific_notation_on_table_images():
    from parameter_extractor.ingestion.table_locate import Word, locate, numbers_in
    values = numbers_in("25°C, 3×10-4 M 3e-4")                              # one number each, not 3, 10, -4
    assert len(values) == 3 and all(abs(v - 3e-4) < 1e-12 for v in values[:2]) and values[2] == 25.0
    assert numbers_in("10-9 M")[0] == 1e-9 and numbers_in("1.2 x 10^-3") == [0.0012]
    w = lambda t, x, y=100: Word(t, (x, y, x + 30, y + 20))                    # noqa: E731
    words = [w("3×10", 60), w("−4", 92, 95), w("M", 130), w("7×10−14", 300),       # a raised exponent; one word
             w("3", 500, 200), w("×", 512, 200), w("10−4", 524, 200), w("5×10−14", 300, 200)]
    boxes, _ = locate(words, "7e-11", "25°C, 3×10-4 M 7e-14")
    assert set(boxes) == {(300, 100, 330, 120), (60, 95, 122, 120)}          # the value and its row label
    boxes, _ = locate(words, "5e-11", "25°C, 3×10-4 M 5e-14")
    assert boxes == [(300, 200, 330, 220)]


def test_log_valued_axes_get_their_own_column():
    """Cleaves2008 Fig. 2 ('Log % yield'): plotted logarithms go in '<name>_log10_<unit>' as plotted (Mickey: their own
    column; converting is left to the user) -- from the plan's `log_values`, the axis title, or the digitizer's box;
    a unit multiplier becomes an offset; not counted as yields; known with the yield column; unit 'log10(%)'."""
    from types import SimpleNamespace as N
    from parameter_extractor.ingestion.figure_rows import build_figure_rows
    from parameter_extractor.ingestion.flatten_to_template import log_base, row_to_template_dict, with_log
    from parameter_extractor.ingestion.observations import observed_unit, unit_for_column
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.figures import (AxisCalibration, AxisVariable, CalibrationPoint, DigitizedFigure,
                                                     DigitizedPanel, DigitizedPoint, DigitizedSeries)
    from parameter_extractor.schemas.methodology import empty_methodology
    from parameter_extractor.schemas.paper_metadata import PaperMetadata
    title = lambda label, **k: N(label=label, log_values=k.get("plan", False), log_values_set=k.get("user"))  # noqa
    assert log_base(title("Log % yield or log % recovery")) == "log10" and log_base(title("ln k")) == "ln"
    assert log_base(title("Yield (%) (log scale)")) == "" and log_base(title("% yield")) == ""
    assert log_base(title("Q", plan=True)) == "log10" and log_base(title("Log % yield", user=False)) == ""
    assert with_log("sampled_Gly-Gly_aq_%yield") == "sampled_Gly-Gly_aq_log10_%yield"
    packs.activate("prebiotic_chemistry")
    reg = VariableRegistry(None, pack="prebiotic_chemistry")
    assert reg.is_known_column("sampled_Gly-Gly_aq_log10_%yield")
    assert unit_for_column("sampled_Gly-Gly_aq_log10_%yield") == "%"           # conversions: the column's unit
    assert observed_unit("sampled_Gly-Gly_aq_log10_%yield") == "log10(%)"      # the observations file says what it is
    cal = lambda a, b, lo, hi: AxisCalibration(p1=CalibrationPoint(px=a[0], py=a[1], value=lo),  # noqa: E731
                                               p2=CalibrationPoint(px=b[0], py=b[1], value=hi))
    panel = DigitizedPanel(x_cal=cal((0, 100), (100, 100), 0, 10), y_cal=cal((0, 100), (0, 0), -3, 2),
                           x=AxisVariable(label="time (h)", column="duration_hr"),
                           y=AxisVariable(label="Log % yield", column="sampled_Gly-Gly_aq_%yield"))
    conc = DigitizedPanel(x_cal=cal((0, 100), (100, 100), 0, 10), y_cal=cal((0, 100), (0, 0), -3, 2),
                          x=AxisVariable(label="time (h)", column="duration_hr"),
                          y=AxisVariable(label="Gly2 (M)", column="sampled_Gly-Gly_aq_mM", multiplier=1000,
                                         log_values=True))
    fig = DigitizedFigure(figure_id="Fig. 2", number=2, page=5, caption="c", render_scale=1.0, page_image="",
                          panels=[panel, conc], series=[
                              DigitizedSeries(label="gly2", points=[DigitizedPoint(px=20, py=20)]),
                              DigitizedSeries(label="gly2 conc", panel=1, points=[DigitizedPoint(px=20, py=20)])])
    meta = PaperMetadata(paper_id="p", paper_title="t", authors=["A"], year_published=2008, journal_published="j")
    rows, problems, _ = build_figure_rows([fig], meta, empty_methodology("p"), "001", 1, 1, registry=reg)
    a, b = (row_to_template_dict(r) for r in rows)
    assert a.get("sampled_Gly-Gly_aq_log10_%yield") == 1.0 and "sampled_Gly-Gly_aq_%yield" not in a
    assert b.get("sampled_Gly-Gly_aq_log10_mM") == 4.0                         # log10 of M + 3 = log10 of mM
    from parameter_extractor.calculators.peptide_totals import fill_total_peptide_yield
    fill_total_peptide_yield(rows)
    assert "total_sampled_peptides_yield" not in row_to_template_dict(rows[0])


def _window(tmp):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.flagged_values import FlaggedValuesWindow
    with patch.object(api_client, "_send", _replay_send):
        result = run_pipeline(PDF, _config(Path(tmp)))
    return app, result, FlaggedValuesWindow(run_folder.load_result(result.run_dir))


def test_replace_a_whole_column_and_undo():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, result, w = _window(tmp)
        column = "vessel_material"
        before = {r["full_id"]: r.get(column, "") for r in w.rows}
        n = w.replace_column(column, "glass flask")
        assert n == sum(v != "glass flask" for v in before.values())
        assert all(r.get(column) == "glass flask" for r in w.rows)
        assert len(corr.load(result.run_dir)) == n and "Ctrl+Z" in w.note_label.text()
        assert w.replace_column(column, "glass flask") == 0                  # nothing left to change
        assert w.undo() and not corr.load(result.run_dir)                    # back as extracted
        assert {r["full_id"]: r.get(column, "") for r in w.rows} == before
        # undo after several steps goes back one step at a time
        fid = w.rows[0]["full_id"]
        w.change_cells([(fid, "initial_temperature_C", w.rows[0]["initial_temperature_C"])], "70")
        w.change_cells([(fid, "initial_temperature_C", "70.0")], "75")
        assert corr.load(result.run_dir)[(fid, "initial_temperature_C")].value == "75.0"
        w.undo()
        assert corr.load(result.run_dir)[(fid, "initial_temperature_C")].value == "70.0"
        w.undo()
        assert not corr.load(result.run_dir) and not w.undo()
        w.close()
        app.processEvents()


def test_any_cell_of_a_row_shows_its_table():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, result, w = _window(tmp)
        fid = next(f for f, _c in w.cell_flags if w._row_place(f)[0])          # a row with a flagged value from a table
        path, caption, entry = w._image_for(None, (fid, "full_id"))           # its id cell: no value, no location
        assert path and "this row's source" in caption
        w.close()
        app.processEvents()


def test_find_similar_points_outside_a_frame():
    """'Find similar points' clicked where no plot frame was found used a method that no longer existed."""
    if not RIGGI.is_file():
        print(f"SKIP: needs {RIGGI}")
        return
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from test_auto_points import _editor
    with tempfile.TemporaryDirectory() as tmp:
        ed = _editor(RIGGI, "3", tmp)
        ed.add_series()
        assert isinstance(ed.find_points_like(3.0, 3.0), int)                  # the page corner: outside every frame


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All Cleaves-round tests passed.")
