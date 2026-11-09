"""
Offline tests for research areas in the variable registry, built-in column choices and the user's variable
categories (Mickey, 2026-11-03): remembered columns / synonyms belong to a pack or to Standard; built-in columns'
category and data type can be changed; categories can be edited and added per area. Covers the registry, the
pipeline helpers (column order, data types, prompt listing) and both windows. No API calls; GUI offscreen.

Run with: python tests/test_research_areas.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import packs, variable_categories as vc
from parameter_extractor.registry import STANDARD, VariableRegistry

# the user's own research areas (Data Packs > New research area) aren't part of what these tests expect: look for
# packs in an empty folder instead of <app data>/packs
_NO_USER_PACKS = Path(tempfile.mkdtemp())
packs.user_packs_dir = lambda: _NO_USER_PACKS

PRE, EXO = "prebiotic_chemistry", "exoplanets"


def test_columns_and_synonyms_belong_to_an_area():
    packs.activate(PRE)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.json"
        reg = VariableRegistry(path)
        reg.add_column("hplc_column", "parameter")                       # remembered for the active pack
        reg.add_alias("parameter", "HPLC column", "hplc_column")
        reg.add_column("data_licence", "parameter", area=STANDARD)       # for every pack
        reg.add_alias("parameter", "reaction volume", "solvent_volume_mL")
        reg.save()
        saved = json.loads(path.read_text())
        assert saved["columns"]["hplc_column"]["pack"] == PRE and saved["columns"]["data_licence"]["pack"] == STANDARD
        assert saved["alias_areas"] == {"parameter:hplc column": PRE, "parameter:reaction volume": PRE}

        exo = VariableRegistry(path, pack=EXO)
        assert not exo.is_known_column("hplc_column") and exo.is_known_column("data_licence")
        assert exo.alias_for("parameter", "HPLC column") is None and "hplc_column" not in exo.known_columns()
        pre = exo.for_pack(PRE)
        assert pre.alias_for("parameter", "HPLC column") == "hplc_column"

        exo.add_column("hplc_column", "parameter")       # accepted in an exoplanet review too: now Standard
        assert exo.column_area("hplc_column") == STANDARD and exo.is_known_column("hplc_column")
        exo.set_column_area("hplc_column", EXO)          # moved: its synonyms follow
        assert exo.alias_area("parameter:hplc column") == EXO and not pre.is_known_column("hplc_column")

        # remembered before research areas: Standard (as before, known everywhere)
        old = Path(tmp) / "old.json"
        old.write_text(json.dumps({"columns": {"stirring": {"kind": "parameter", "added": "2026-10-14"}},
                                   "aliases": {"parameter:stirring": "stirring"}}))
        for pid in (PRE, EXO):
            assert VariableRegistry(old, pack=pid).alias_for("parameter", "stirring") == "stirring"


def test_builtin_choices():
    packs.activate(PRE)
    from parameter_extractor.column_order import ColumnOrder
    from parameter_extractor.schemas.row_schema import ExtractedRow
    from parameter_extractor.value_types import apply_column_types, column_type
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.json"
        reg = VariableRegistry(path)
        assert ColumnOrder(registry=reg).category_of("replicates") == "methodology"
        reg.set_builtin("replicates", value_type="text", category="analysis")
        reg.set_builtin("paper_title", category="other")          # a column every pack has: kept for Standard
        reg.save()
        saved = json.loads(path.read_text())["builtin_columns"]
        assert saved == {PRE: {"replicates": {"type": "text", "category": "analysis"}},
                         STANDARD: {"paper_title": {"category": "other"}}}
        reg = VariableRegistry(path)
        assert column_type("replicates", reg) == "text" and column_type("replicates") == "integer"
        order = ColumnOrder(registry=reg)
        assert order.category_of("replicates") == "analysis" and order.category_of("paper_title") == "other"
        assert VariableRegistry(path, pack=EXO).builtin_categories() == {"paper_title": "other"}
        try:
            reg.set_builtin("not_a_column", category="other")
        except ValueError:
            pass
        else:
            raise AssertionError("only built-in columns")
        reg.set_builtin("replicates", "", "")                     # back to the defaults
        assert reg.builtin_choice("replicates") == {} and PRE not in reg._store.builtin

        row = lambda i, value: ExtractedRow(full_id=f"r{i}", set_id="s", sample_id=f"r{i}", set_type="Independent",
                                            entry_number=i, paper_title="t", authors=["A"], year_published=2023,
                                            journal_published="j", experiment_type="Batch", solution_type="Wet",
                                            initial_temperature_C=value)
        rows = [row(1, 25.0), row(2, 80.5)]
        problems = apply_column_types(rows, {"initial_temperature_C": "integer"})
        assert rows[0].initial_temperature_C == 25 and rows[1].initial_temperature_C is None
        assert len(problems) == 1 and "r2: 80.5" in problems[0]


def test_category_edits():
    pack = packs.activate(PRE)
    local = {STANDARD: {"changed": {"metadata": {"label": "Study details", "table_order": 5}},
                        "added": [{"id": "safety", "label": "Safety", "description": "hazards and precautions",
                                   "value_type": "text", "max_words": 8, "table_order": 95, "model_assigns": True}]},
             PRE: {"changed": {"conditions": {"description": "reactor quantities", "model_assigns": False}},
                   "added": [{"id": "light_source", "label": "Light source", "description": "lamps and filters",
                              "value_type": "any", "max_words": 10, "table_order": 35, "model_assigns": True}]}}
    try:
        vc.use_local(local)
        cats = {c.id: c for c in vc.categories(pack)}
        ids = [c.id for c in vc.categories(pack)]
        assert cats["metadata"].label == "Study details" and cats["metadata"].table_order == 5
        assert len(cats["metadata"].columns) > 5                       # the pack's columns kept
        assert ids.index("light_source") < ids.index("metadata") and ids.index("safety") < ids.index("other")
        assert not cats["conditions"].assignable and cats["light_source"].assignable
        listing = vc.prompt_listing(pack)
        assert "`light_source` (lamps and filters" in listing and "`safety`" in listing
        assert "`conditions`" not in listing
        exo = [c.id for c in vc.categories(packs.available()[EXO])]
        assert "safety" in exo and "light_source" not in exo
        from parameter_extractor.column_order import ColumnOrder
        assert ColumnOrder(pack=pack).display[0].id == "metadata"
        from parameter_extractor.stages.optional import load_specs
        Item, Result = load_specs()["experimental_conditions"].models()
        assert "light_source" in json.dumps(Result.model_json_schema())
    finally:
        vc.use_local({})
    assert vc.by_id("metadata").label == "Metadata" and vc.by_id("safety") is None


def test_remembered_variables_window():
    packs.activate(PRE)
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.registry_dialog import RegistryDialog
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.json"
        reg = VariableRegistry(path)
        reg.add_column("hplc_column", "parameter")
        reg.add_alias("parameter", "HPLC column", "hplc_column")
        reg.add_column("data_licence", "parameter", area=STANDARD)
        reg.save()
        dlg = RegistryDialog(path)
        groups = [dlg.columns_tree.topLevelItem(i).text(0) for i in range(dlg.columns_tree.topLevelItemCount())]
        assert groups == ["Standard (every data pack)  (1)", "Prebiotic chemistry  (1)"]
        item = dlg.leaves(dlg.columns_tree, PRE)[0]
        options, _ = dlg.options_for(item, dlg.A_CATEGORY)
        assert ("Analysis", "analysis") in options and ("Metadata", "metadata") in options
        assert not any(cid in ("figure", "assumed", "planet") for _, cid in options)
        std_options = [cid for _, cid in dlg.options_for(dlg.leaves(dlg.columns_tree, STANDARD)[0], dlg.A_CATEGORY)[0]]
        assert std_options == ["", "metadata", "methodology", "other"]
        assert dlg.options_for(item, dlg.A_COLUMN) == ([], False)          # names: Rename… only
        dlg.choose(item, dlg.A_CATEGORY, "analysis")
        dlg.choose(item, dlg.A_TYPE, "text")
        dlg.choose(item, dlg.A_AREA, STANDARD)
        dlg._refresh()
        assert [i.text(0) for i in dlg.leaves(dlg.columns_tree, STANDARD)] == ["data_licence", "hplc_column"]
        assert dlg.leaves(dlg.alias_tree, STANDARD)[0].text(dlg.S_COLUMN) == "hplc_column"   # synonym followed

        # built-in: grouped per area, changes asked about once, shown against the defaults
        assert [g for g, _ in dlg.builtin_columns()] == [STANDARD, EXO, PRE]
        rep = next(i for i in dlg.leaves(dlg.builtin_tree, PRE) if i.text(0) == "replicates")
        assert rep.text(dlg.B_DEFAULT) == "Experimental Methodology · Whole number"
        dlg.builtin_confirmed = True
        dlg.choose(rep, dlg.B_CATEGORY, "analysis")
        dlg.choose(rep, dlg.B_TYPE, "text")
        dlg._refresh()
        rep = next(i for i in dlg.leaves(dlg.builtin_tree, PRE) if i.text(0) == "replicates")
        assert rep.text(dlg.B_CATEGORY) == "Analysis" and rep.text(dlg.B_TYPE) == "Text"
        pl = next(i for i in dlg.leaves(dlg.builtin_tree, EXO) if i.text(0) == "pl_orbper")
        dlg.choose(pl, dlg.B_CATEGORY, "other")
        dlg.filter_edit.setText("replicates")
        shown = [i.text(0) for i in dlg.leaves(dlg.builtin_tree) if not i.isHidden()]
        assert shown[0] == "replicates" and all("replicates" in s for s in shown) and len(shown) < 10
        dlg._save()
        saved = json.loads(path.read_text())
        assert saved["columns"]["hplc_column"] == {**saved["columns"]["hplc_column"], "pack": STANDARD,
                                                   "category": "analysis", "type": "text"}
        assert saved["builtin_columns"] == {PRE: {"replicates": {"category": "analysis", "type": "text"}},
                                            EXO: {"pl_orbper": {"category": "other"}}}
        # one area at a time (opened from a research area's window): that area's groups and the Standard ones
        dlg = RegistryDialog(path, area=EXO)
        visible = lambda tree: [tree.topLevelItem(i).data(0, 0x0100)[1] for i in range(tree.topLevelItemCount())
                                if not tree.topLevelItem(i).isHidden()]
        assert dlg.area_combo.currentData() == EXO and visible(dlg.builtin_tree) == [STANDARD, EXO]
        dlg.area_combo.setCurrentIndex(0)                                    # all research areas
        assert visible(dlg.builtin_tree) == [STANDARD, EXO, PRE]
        assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == [
            "Accepted columns", "Synonyms", "Compound names", "Changes to pack columns"]
        dlg = RegistryDialog(path)
        dlg._reset_all_builtin()
        dlg._save()
        assert "builtin_columns" not in json.loads(path.read_text())


def test_categories_window():
    pack = packs.activate(PRE)
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.categories_dialog import C_ID, CategoriesDialog
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.json"
        try:
            dlg = CategoriesDialog(path)
            assert dlg.area == PRE and [r["id"] for r in dlg.rows()][:3] == ["starting_species", "kinetics", "products"]
            assert not dlg.table.item(0, C_ID).flags() & dlg.table.item(0, C_ID).flags().ItemIsEditable
            dlg.builtin_confirmed = True
            r = [x["id"] for x in dlg.rows()].index("analysis")
            assert dlg.set_row(r, dict(dlg.rows()[r], label="Product analysis", max_words=20))
            dlg.add_category({"id": "light_source", "label": "Light source", "description": "lamps and filters",
                              "table_order": 35})
            assert dlg.problems() == []
            dlg.add_category({"id": "metadata", "label": "Dup", "description": "x"})       # a shared id
            assert any("'metadata' is already used" in p for p in dlg.problems())
            assert dlg.remove_row(len(dlg.rows()) - 1) and not dlg.remove_row(0)          # app's own: kept
            dlg.area_combo.setCurrentIndex(dlg.area_combo.findData(STANDARD))
            assert [r["id"] for r in dlg.rows()] == ["metadata", "methodology", "other"]
            dlg.add_category({"id": "safety", "label": "Safety", "description": ""})
            assert any("needs a description" in p for p in dlg.problems())
            dlg.set_row(3, dict(dlg.rows()[3], description="hazards"))
            dlg._save()
            saved = json.loads(path.read_text())["categories"]
            assert saved[PRE]["changed"] == {"analysis": {"label": "Product analysis", "max_words": 20}}
            assert [c["id"] for c in saved[PRE]["added"]] == ["light_source"]
            assert [c["id"] for c in saved[STANDARD]["added"]] == ["safety"]
            # in use straight away (the window applies them) and from the registry file in later runs
            assert vc.by_id("analysis").label == "Product analysis" and vc.by_id("light_source")
            vc.use_local({})
            assert vc.by_id("light_source") is None
            vc.use_local(VariableRegistry(path).local_categories)
            assert [c.id for c in vc.categories(pack)].index("light_source") == 7

            dlg = CategoriesDialog(path)                     # reset an app category; back to the bundled one
            dlg.builtin_confirmed = True
            r = [x["id"] for x in dlg.rows()].index("analysis")
            dlg.table.setCurrentCell(r, 0)
            dlg._reset_selected()
            dlg.save()
            assert "changed" not in json.loads(path.read_text())["categories"].get(PRE, {})
        finally:
            vc.use_local({})


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All research-area tests passed.")
