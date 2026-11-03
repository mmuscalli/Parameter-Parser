"""
Offline tests for column data types (value_types.py; Mickey, 2026-11-03): replicates as a whole number
('triplicate' -> 3) from the conditions step and from figure conditions, and the review window's "Data type"
for new variables -- values converted, unfit values block the build, the type remembered with the column.
No API calls; the GUI part runs offscreen.

Run with: python tests/test_value_types.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs
from parameter_extractor.value_types import coerce, column_type, whole_number


def test_whole_numbers_and_coercion():
    assert [whole_number(x) for x in (3, 3.0, "3", "n = 3", "triplicate experiments; maximum lengths averaged",
                                      "in duplicate", "three runs", "triplicates")] == [3, 3, 3, 3, 3, 2, 3, 3]
    assert [whole_number(x) for x in (2.5, "3 runs of 5 mg", "n/a", "")] == [None, None, None, None]
    assert coerce("triplicate", "integer") == (3, "") and coerce("several", "integer")[0] is None
    assert coerce("5.2", "number") == (5.2, "") and coerce("5.2 mg", "number")[0] is None
    assert coerce(3.0, "text") == ("3", "") and coerce("Present", "yes_no") == ("yes", "")
    assert coerce("maybe", "yes_no")[0] is None and coerce("anything", "any") == ("anything", "")


def test_column_types():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.registry import VariableRegistry
    reg = VariableRegistry(None)
    assert [column_type(c, reg) for c in ("replicates", "cycle_number", "pH_buffer", "initial_temperature_C",
                                          "initial_pH", "unheard_of_column")] == \
        ["integer", "integer", "text", "number", "number", "any"]
    reg.add_column("tube_count", "parameter", value_type="integer")
    assert column_type("tube_count", reg) == "integer"
    reg.set_column_type("tube_count", "any")
    assert column_type("tube_count", reg) == "any" and "type" not in reg.added_columns["tube_count"]
    reg.set_column_type("replicates", "text")                       # built-in: keeps its own
    assert column_type("replicates", reg) == "integer"


def test_replicates_from_the_conditions_step_and_figures():
    """Riggi2023: the conditions step wrote 'triplicate experiments; maximum lengths averaged' (Fig. 3's rows),
    the figure suggestions '3' (Figs. 2, A2) -- all become 3."""
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.figure_rows import convert_condition
    from parameter_extractor.schemas.figures import SeriesCondition
    from parameter_extractor.stages.optional import load_specs, stage_values
    spec = load_specs()["experimental_conditions"]
    Item, _ = spec.models()
    item = lambda **kw: Item.model_validate(dict(col="replicates", u="", q="q", src="Methods", c="high", **kw))
    values, problems = stage_values(spec, item(v=0, txt="triplicate experiments; maximum lengths averaged"))
    assert values["replicates"].value == 3 and not problems and "read from" in values["replicates"].note
    assert stage_values(spec, item(v=2))[0]["replicates"].value == 2
    assert not stage_values(spec, item(v=2.5))[0] and stage_values(spec, item(v=2.5))[1]
    assert not stage_values(spec, item(v=0, txt="several"))[0]
    c = lambda value: convert_condition(SeriesCondition(column="replicates", value=value, source=""))
    assert c("3")[1:] == (3, "") and c("in duplicate")[1:] == (2, "")
    assert c("several")[2].startswith("replicates holds whole numbers")
    assert c("organic pH buffers") != ("pH_buffer", "organic pH buffers", "")       # (another column)
    assert convert_condition(SeriesCondition(column="pH_buffer", value="organic pH buffers", source=""))[1:] == \
        ("organic pH buffers", "")


def test_review_window_data_type():
    packs.activate("prebiotic_chemistry")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.variable_review import VariableReviewDialog
    from parameter_extractor.ingestion.new_variables import apply_decisions, group_new_variables
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.row_schema import ExtractedRow
    from parameter_extractor.schemas.variables import NewVariable
    with tempfile.TemporaryDirectory() as tmp:
        reg = VariableRegistry(Path(tmp) / "registry.json")
        nv = lambda value, rid: NewVariable(kind="parameter", name="tube count", alias_name="tube count",
                                            proposed_column="tube_count", value_text=value, row_ids=[rid],
                                            category="methodology", origin="experimental conditions")
        groups = group_new_variables([nv("triplicate", "r1"), nv("two tubes", "r2")]) + group_new_variables([
            NewVariable(kind="parameter", name="replicate runs", alias_name="replicate runs",
                        proposed_column="replicates", value_text="in duplicate", row_ids=["r1"], category="methodology", origin="experimental conditions")])
        dlg = VariableReviewDialog(groups, [], reg)
        dlg._accept_suggestions()
        assert dlg.type_boxes[1].currentData() == "integer" and not dlg.type_boxes[1].isEnabled()   # built-in
        assert dlg.type_boxes[0].isEnabled()
        dlg.set_value_type(0, "integer")
        assert dlg.problems() == []
        dlg.set_value_type(0, "number")                       # 'triplicate' isn't a number: the build waits
        assert any("can't be stored as number" in p for p in dlg.problems())
        dlg._show_values(0)
        assert dlg.values_table.item(0, 2).text().startswith("⚠")
        dlg.set_value_type(0, "integer")
        rows = [ExtractedRow(full_id=r, set_id="s", sample_id=r, set_type="Independent", entry_number=i,
                             paper_title="t", authors=["A"], year_published=2023, journal_published="j",
                             experiment_type="Batch", solution_type="Wet") for i, r in enumerate(("r1", "r2"), 1)]
        apply_decisions(rows, groups, dlg.decisions(), reg)
        assert [r.extra.get("tube_count") for r in rows] == [3, 2]
        assert rows[0].extra.get("replicates") == 2
        assert reg.added_columns["tube_count"]["type"] == "integer"
        reg.save()
        assert column_type("tube_count", VariableRegistry(Path(tmp) / "registry.json")) == "integer"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All value-type tests passed.")
