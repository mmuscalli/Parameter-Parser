"""
Offline tests for the built-in step pages (step_info.py; Mickey, 2026-11-11: what the chemistry step contains wasn't
shown anywhere): what a built-in step reads, records, fills and is told, for a data pack, read-only, in the pack
editor's Steps tab and from a module's page.

Run with: python tests/test_step_info.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pack_facts as pf  # noqa: E402
from parameter_extractor import modules as module_store, packs, step_info  # noqa: E402
from parameter_extractor.stages import chemistry_extractor  # noqa: E402


def test_the_chemistry_step_as_a_pack_runs_it():
    pack = pf.linked("prebiotic_chemistry", "solution_chemistry", "peptides_oligomers")
    before = packs.current().id
    info = step_info.describe("chemistry", pack)
    assert packs.current().id == before                       # the active pack is put back
    assert info.source == "the Solution chemistry module"
    fields = [name for _depth, name, _desc in info.records]
    assert any(name.startswith("nm (name)") for name in fields), fields[:20]      # short names read out
    assert not any("{default" in desc for _d, _n, desc in info.records)
    # the rules a module adds are listed, and they are in the instructions the model gets
    peptide_rules = module_store.available()["peptides_oligomers"].manifest.prompt_rules["chemistry"]
    listed = dict(info.rules)
    assert listed["the Peptides and oligomers module"] == peptide_rules
    assert all(rule in info.instructions for rule in peptide_rules)
    # the instructions are exactly a run's, with the paper and the plan as placeholders
    packs._current = pack
    try:
        expected = chemistry_extractor.prompt_text(step_info.PAPER_PLACEHOLDER, step_info.PLAN_PLACEHOLDER,
                                                   pack.species_names, grids=False)
    finally:
        packs._current = None
    assert info.instructions == expected and step_info.PAPER_PLACEHOLDER in info.instructions
    assert {"normalize_species", "mixing"} <= {name for name, _ in info.calculations}
    assert str(len(pack.species_names)) in info.vocabulary
    page = step_info.as_html(info)
    for part in ("Columns it fills", "What it records", "Rules added to its instructions",
                 "as the model receives them", "initial_&lt;compound&gt;_&lt;phase&gt;_mM"):
        assert part in page, part


def test_other_built_in_steps_and_packs_without_them():
    exo = packs.available()["exoplanets"]
    assert step_info.built_in_steps(exo) == ["fit_models"]
    info = step_info.describe("fit_models", exo)
    assert info.records and info.source == "this data pack" and info.rules == []
    pre = pf.linked("prebiotic_chemistry", "analysis")
    analysis = step_info.describe("analysis", pre)
    assert "techniques" in analysis.vocabulary and analysis.source == "the Analysis methods module"
    try:
        step_info.describe("structure_planner", pre)
        raise AssertionError("only the described built-in steps")
    except ValueError:
        pass


def test_the_pack_editor_shows_built_in_steps():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import PackEditor
    pack = pf.linked("prebiotic_chemistry", "solution_chemistry", "peptides_oligomers")
    e = PackEditor(pack.folder)
    names = [e.builtin_list.item(r).data(Qt.ItemDataRole.UserRole) for r in range(e.builtin_list.count())]
    assert "chemistry" in names and names == step_info.built_in_steps(pack)
    e.tabs.setCurrentIndex(e.tab_index("Steps"))
    e.builtin_list.setCurrentRow(names.index("chemistry"))
    app.processEvents()
    assert e.stage_stack.currentIndex() == 1 and "Columns it fills" in e.builtin_view.toPlainText()
    assert "Shown as this data pack is saved" in e.builtin_view.toPlainText()
    if e.stage_list.count():                                 # back to a configurable step: its form
        e.stage_list.setCurrentRow(0)
        assert e.stage_stack.currentIndex() == 0 and e.builtin_list.currentRow() == -1
    # a module's page: the step it adds rules to, one click away
    t = e.module_table
    rows = {t.item(r, 0).data(Qt.ItemDataRole.UserRole): r for r in range(t.rowCount())}
    e.tabs.setCurrentIndex(e.tab_index("Modules"))
    t.setCurrentCell(rows["peptides_oligomers"], 0)
    app.processEvents()
    from PySide6.QtWidgets import QPushButton
    buttons = [b for b in e.module_scroll.widget().findChildren(QPushButton) if b.text().startswith("View the")]
    assert buttons and "compounds and their amounts" in buttons[0].text()
    buttons[0].click()
    app.processEvents()
    assert e.tabs.currentIndex() == e.tab_index("Steps") and e.stage_stack.currentIndex() == 1
    assert e.builtin_list.currentItem().data(Qt.ItemDataRole.UserRole) == "chemistry"
    e.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All built-in step page tests passed.")
