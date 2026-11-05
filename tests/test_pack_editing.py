"""
Making and editing research areas in the app (2026-11-05, menu Data Packs): pack_editing.PackDraft (load, change,
save), pack_editing.check (errors, warnings, notes), packs.create_pack from the template or a copy of a pack, and the
windows (gui/pack_windows.py: New research area, the editor's tabs, read-only built-in packs). No API calls.

Run with: python tests/test_pack_editing.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from parameter_extractor import packs
from parameter_extractor.pack_editing import PackDraft, check


def editor_calcs():
    from parameter_extractor.pack_editing import CALCULATIONS
    return CALCULATIONS


def _levels(problems, level):
    return [p for p in problems if p.level == level]


def test_built_in_packs_check_clean():
    """The app's own packs: no errors or warnings (only notes) -- the check isn't crying wolf."""
    for pack_id in ("prebiotic_chemistry", "exoplanets"):
        problems = check(PackDraft.load(packs.available()[pack_id].folder))
        assert not _levels(problems, "error") and not _levels(problems, "warning"), (pack_id, problems)
        assert PackDraft.load(packs.available()[pack_id].folder).builtin


def test_check_finds_problems():
    with tempfile.TemporaryDirectory() as tmp:
        pack = packs.create_pack("checked_area", "Checked", base=Path(tmp))
        d = PackDraft.load(pack.folder)
        assert not _levels(check(d), "error")
        d.columns = d.columns + ["temperature_C"]                                   # listed twice
        d.manifest["postprocess"] = ["mixing", "no_such_step"]
        spec = d.stages["example_measurements.json"]
        spec["parameters"][0]["unit"] = "bar"                                       # temperature_C in bar
        spec["parameters"].append({"column": "mass_g", "unit": "g"})                # no description
        spec["trigger"] = {}                                                        # never runs
        d.manifest["category_columns"]["nowhere"] = {"columns": ["temperature_C"]}
        messages = [str(p) for p in check(d)]
        expect = ["'temperature_C' is listed twice", "unknown calculation 'no_such_step'",
                  "'mixing' works on the results of the 'chemistry' step", "named in °C but the parameter's unit is bar",
                  "'mass_g' has no description", "it never runs", "isn't a category"]
        for e in expect:
            assert any(e in m for m in messages), (e, messages)
        empty = PackDraft.load(pack.folder)
        empty.columns, empty.stages = [], {}
        assert {"the dataset has no columns.", "nothing extracts values: add a stage."} <= {p.message for p in check(empty)}


def test_draft_saves_and_is_used():
    with tempfile.TemporaryDirectory() as tmp:
        packs.add_search_dir(Path(tmp))
        pack = packs.create_pack("saved_area", "Saved", base=Path(tmp))
        d = PackDraft.load(pack.folder)
        file = d.new_stage("soil_properties", "Soil properties")
        d.stages[file]["parameters"] = [{"column": "soil_carbon_pct", "unit": "%", "description": "organic carbon"}]
        d.remove_stage("example_measurements.json")
        d.columns = ["soil_carbon_pct", "depth_cm"]
        d.rules["structure_planner"] = "- One row per soil sample and depth."
        d.rules["figure_planner"] = ""
        d.manifest["label"] = "Soils"
        d.save()
        from parameter_extractor.stages.optional import load_specs
        reloaded = packs.available()["saved_area"]
        assert reloaded.label == "Soils" and reloaded.template_columns == ["soil_carbon_pct", "depth_cm"]
        assert list(load_specs(reloaded)) == ["soil_properties"]                     # the cache was cleared
        assert not (pack.folder / "stages" / "example_measurements.json").exists()
        assert (pack.folder / "prompts" / "structure_planner.rules.md").read_text().startswith("- One row")
        assert "_about_id" in json.loads((pack.folder / "pack.json").read_text())   # explanations kept
        assert not _levels(check(PackDraft.load(pack.folder)), "error")
        try:
            PackDraft.load(packs.available()["exoplanets"].folder).save()
            raise AssertionError("saved a built-in pack")
        except PermissionError:
            pass


def test_copy_of_a_built_in_pack():
    with tempfile.TemporaryDirectory() as tmp:
        copy = packs.create_pack("my_exoplanets", "My exoplanets", base=Path(tmp),
                                 source=packs.available()["exoplanets"], units={"sample": "planet solution"})
        d = PackDraft.load(copy.folder)
        assert not d.builtin and d.manifest["units"]["sample"] == "planet solution"
        assert len(d.stages) == 3 and copy.template_columns == packs.available()["exoplanets"].template_columns


def test_windows():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import NewPackDialog, PackEditor, suggest_id
    assert suggest_id("Soil carbon cycling!") == "soil_carbon_cycling" and suggest_id("2D materials") == "area_2d_materials"
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        new = NewPackDialog()
        new.label_edit.setText("Soil carbon")
        assert new.id_edit.text() == "soil_carbon"
        new.sample_edit.setText("soil sample")
        new.create()
        assert new.created is not None and new.created.manifest.units["sample"] == "soil sample"
        assert "soil_carbon" in packs.available()

        editor = PackEditor(new.created.folder)
        editor.label_edit.setText("Soil carbon cycling")
        editor.column_list.addItem("depth_cm")
        # calculations: none suits the template's (no) built-in steps -> all under "Other calculations"; ticking one
        # moves it up (2026-11-05)
        assert editor.calc_list.count() == 0 and editor.other_calc_list.count() == len(editor_calcs())
        editor.other_calc_list.item(0).setCheckState(Qt.CheckState.Checked)      # normalize_species
        app.processEvents()
        assert [editor.calc_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(editor.calc_list.count())] \
            == ["normalize_species"]
        editor.builtin_boxes["chemistry"].setChecked(True)                        # its calculations come up
        assert editor.calc_list.count() == 10 and editor.other_calc_list.count() == 4
        editor.builtin_boxes["chemistry"].setChecked(False)
        assert not editor.advanced_box.isVisibleTo(editor) and editor.help_buttons()
        editor.tabs.setCurrentIndex(2)
        editor._add_parameter({"column": "depth_cm", "unit": "cm", "description": "sampling depth"})
        editor.s_keywords.setText("soil, depth")
        # rules are rows (the file's '- ' lines): the template's two example rules, then ours instead
        editor.tabs.setCurrentIndex(3)
        assert len(editor.rules_items()) == 2 and editor.rules_items()[0].startswith("EXAMPLE RULES")
        editor.set_rules_items(["One row per soil sample.", "A depth profile is one set."])
        editor._add_rule("Controls get no rows.", edit=False)
        editor.rules_table.setCurrentCell(2, 0)
        editor._move_rule(-1)
        assert editor.rules_items() == ["One row per soil sample.", "Controls get no rows.",
                                        "A depth profile is one set."]
        problems = editor.run_check()
        assert any("normalize_species" in p.message for p in problems)              # needs the chemistry step
        with patch("parameter_extractor.gui.pack_windows.QMessageBox.warning", lambda *a, **k: None):
            assert editor.save()
        d = PackDraft.load(new.created.folder)
        assert d.manifest["label"] == "Soil carbon cycling" and d.columns[-1] == "depth_cm"
        spec = d.stages["example_measurements.json"]
        assert spec["parameters"][-1] == {"column": "depth_cm", "unit": "cm", "description": "sampling depth"}
        assert spec["trigger"] == {"always": True, "keywords": ["soil", "depth"]}
        assert d.rules["structure_planner"] == ("- One row per soil sample.\n- Controls get no rows.\n"
                                                "- A depth profile is one set.\n")
        assert spec["parameters"][0].get("uncertainties") is True                   # untouched fields kept

        built_in = PackEditor(packs.available()["prebiotic_chemistry"].folder)
        assert built_in.read_only and not built_in.save_btn.isEnabled() and built_in.label_edit.isReadOnly()
        assert built_in.rules_combo.isEnabled()                                     # its rules can be looked at


def test_delete_pack():
    with tempfile.TemporaryDirectory() as tmp:
        packs.add_search_dir(Path(tmp))
        pack = packs.create_pack("doomed_area", "Doomed", base=Path(tmp))
        packs.activate("doomed_area")
        assert packs.delete_pack("doomed_area") == pack.folder.resolve()
        assert not pack.folder.exists() and "doomed_area" not in packs.available()
        assert packs.current().id == packs.DEFAULT_PACK                     # the active one was it: back to default
        for protected in ("prebiotic_chemistry", "exoplanets"):
            try:
                packs.delete_pack(protected)
                raise AssertionError(f"removed {protected}")
            except PermissionError:
                pass
        try:
            packs.delete_pack("_template")                                  # not even listed
            raise AssertionError("removed the template")
        except ValueError:
            pass
        assert packs.TEMPLATE_DIR.is_dir() and packs.available()["exoplanets"].folder.is_dir()


def test_remove_needs_two_confirmations():
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui import pack_windows
    from parameter_extractor.gui.pack_windows import DeleteConfirmDialog, remove_pack
    with tempfile.TemporaryDirectory() as tmp:
        packs.add_search_dir(Path(tmp))
        pack = packs.create_pack("test_case", "Test case", base=Path(tmp))
        dlg = DeleteConfirmDialog(pack)
        assert not dlg.remove_btn.isEnabled()
        for typed, ok in (("delete", False), ("DELETE ", False), ("DELET", False), ("DELETE", True)):
            dlg.word_edit.setText(typed)
            assert dlg.remove_btn.isEnabled() is ok, typed

        def first_answer(role):                    # which button the warning's user presses
            return lambda box: next(b for b in box.buttons() if box.buttonRole(b) == role)
        destructive, cancel = QMessageBox.ButtonRole.DestructiveRole, QMessageBox.ButtonRole.RejectRole
        accepted, rejected = QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected
        for first, second, removed in ((cancel, accepted, False), (destructive, rejected, False),
                                       (destructive, accepted, True)):
            with patch.object(pack_windows, "choose_pack", lambda *a, **k: pack), \
                    patch.object(QMessageBox, "exec", lambda self: 0), \
                    patch.object(QMessageBox, "clickedButton", first_answer(first)), \
                    patch.object(DeleteConfirmDialog, "exec", lambda self, code=second: code):
                assert (remove_pack(None) == "test_case") is removed
            assert pack.folder.exists() is not removed


def test_rules_rows_round_trip():
    from parameter_extractor.pack_editing import items_to_rules, rules_to_items
    text = ("- First rule, which goes on\n  over two lines.\n- Second rule.\n\nA paragraph without a dash\n"
            "continues here.\n")
    assert rules_to_items(text) == ["First rule, which goes on over two lines.", "Second rule.",
                                    "A paragraph without a dash continues here."]
    assert items_to_rules(["  a  b ", "", "c"]) == "- a b\n- c\n" and items_to_rules([]) == ""
    for path in sorted((packs.BUILTIN_DIR).glob("*/prompts/*.rules.md")):        # the real files survive
        items = rules_to_items(path.read_text())
        assert items and rules_to_items(items_to_rules(items)) == items, path


def test_formula_columns_list():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import PackEditor
    with tempfile.TemporaryDirectory() as tmp:
        packs.add_search_dir(Path(tmp))
        pack = packs.create_pack("cols_area", "Cols", base=Path(tmp))
        editor = PackEditor(pack.folder)
        editor.show()
        editor.tabs.setCurrentIndex(4)
        app.processEvents()
        names = [editor.f_columns.item(i).text() for i in range(editor.f_columns.count())]
        assert {"temperature_C", "product_yield_pct", "temperature_K", "paper_title"} <= set(names)
        editor.f_column_filter.setText("product")
        assert [n for i, n in enumerate(names) if not editor.f_columns.item(i).isHidden()] == ["product_yield_pct"]
        # no editor open: appended to the selected formula
        editor.f_table.setCurrentCell(0, 1)
        editor.insert_formula_column("product_yield_pct")
        assert editor.f_table.item(0, 1).text() == "temperature_C + 273.15 product_yield_pct"
        # the Formula cell open: typed in at its cursor; odd names get backticks
        editor.f_table.item(0, 1).setText("2 * ")
        editor.f_table.editItem(editor.f_table.item(0, 1))
        app.processEvents()
        assert editor._formula_editor is not None
        editor._formula_editor.end(False)
        editor.insert_formula_column("sampled_Gly-Gly_aq_%yield")
        assert editor._formula_editor.text() == "2 * `sampled_Gly-Gly_aq_%yield`"
        assert editor.f_columns.focusPolicy() == editor.f_columns.focusPolicy().NoFocus
        editor.close()


def test_menu():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.setOrganizationName("ParameterExtractorPackTests")   # its own prefs: runs in parallel with test_gui_offline
    from parameter_extractor.gui import main_window
    w = main_window.MainWindow()
    titles = [a.text() for a in w.menuBar().actions()]
    assert titles[:3] == ["File", "Variables", "Data Packs"], titles
    menu = next(a.menu() for a in w.menuBar().actions() if a.text() == "Data Packs")
    assert [a.text() for a in menu.actions() if a.text()] == ["New research area…", "Edit research area…",
                                                             "Copy a research area…", "Check research area…",
                                                             "Remove research area…", "Open research areas folder"]
    w._set_inputs_enabled(False)                                                     # locked during a run
    assert not w.new_pack_action.isEnabled() and not w.edit_pack_action.isEnabled()
    assert not w.remove_pack_action.isEnabled()
    w._set_inputs_enabled(True)
    w.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All pack-editing tests passed.")
