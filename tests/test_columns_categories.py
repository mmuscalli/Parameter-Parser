"""
The pack editor's Columns tab with the kinds of value (variable categories) in it (gui/category_panel.py; Mickey,
2026-11-19), and the Map's double-click / right-click into the editor's tabs. A copy of the exoplanet pack in a temp
folder; no API calls.

Run with: python tests/test_columns_categories.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from parameter_extractor import packs  # noqa: E402

app = QApplication.instance() or QApplication([])


def _editor(tmp):
    from parameter_extractor.gui.pack_windows import PackEditor
    pack = packs.create_pack("mine", "Mine", base=Path(tmp), source=packs.available()["exoplanets"])
    return pack, PackEditor(pack.folder)


def _save(editor):
    with patch.object(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Save):
        editor.collect()
        assert editor.save()


def test_a_kind_of_value_is_edited_beside_its_columns():
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack, e = _editor(tmp)
        own = [c["id"] for c in json.loads((pack.folder / "pack.json").read_text())["variable_categories"]]
        cid = next(c for c in own if e._category_header(c) is not None and e._category_header(c).childCount())
        e.show_category(cid)
        panel = e.category_panel
        assert panel.cid == cid and panel.label.isEnabled() and panel.remove_btn.isVisible() is not None
        column = e._category_header(cid).child(0)               # a column shows its kind of value too
        e.column_tree.setCurrentItem(column)
        assert panel.cid == cid
        panel.label.setText("Fit models")
        panel.label.editingFinished.emit()
        assert e._category_header(cid).text(0) == "Fit models"
        assert e.structure_page.kind(cid)["label"] == "Fit models"
        panel.fill.setCurrentIndex(panel.fill.findData("paper"))   # the same setting as the Structure tab's
        assert e.structure_page.kind(cid)["fill"] == "paper"
        shared = "metadata"                                       # every pack's: shown, not edited here
        e.show_category(shared)
        assert panel.cid == shared and not panel.label.isEnabled() and panel.level.isEnabled()
        new = e.add_category("Light source")
        assert e._category_header(new) is not None and e.structure_page.kind(new)["level"] == "sample"
        _save(e)
        saved = json.loads((pack.folder / "pack.json").read_text())
        mine = {c["id"]: c for c in saved["variable_categories"]}
        assert mine[cid]["label"] == "Fit models" and mine[cid]["fill"] == "paper"
        assert mine[new]["label"] == "Light source" and mine[new]["model_assigns"] is False
        assert e._category_header(new) is not None                # the tree as saved still has it
        e.remove_category(new)
        _save(e)
        assert new not in {c["id"] for c in json.loads((pack.folder / "pack.json").read_text())["variable_categories"]}
        e.close()


def test_the_map_opens_the_tab_where_a_part_is_edited():
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack, e = _editor(tmp)
        own_step = next(spec["name"] for spec in e.draft.stages.values())
        actions = e._map_actions(f"step:{own_step}")
        assert actions and "Steps tab" in actions[0][0]
        actions[0][1]()
        assert e.tabs.tabText(e.tabs.currentIndex()) == "Steps"
        kind = e.map_canvas.scene().structure.kinds[0].id
        e._map_actions(f"kind:{kind}")[0][1]()
        assert e.tabs.tabText(e.tabs.currentIndex()) == "Columns" and e.category_panel.cid == kind
        e._map_actions("level:set")[0][1]()
        assert e.tabs.tabText(e.tabs.currentIndex()) == "Structure"
        assert "General" in e._map_actions("calcs")[0][0]
        e.close()
    pack = packs.activate("prebiotic_chemistry")                  # a module's step: its module is offered
    from parameter_extractor.gui.pack_windows import PackEditor
    e = PackEditor(pack.folder)
    import pack_facts as pf
    step = pf.module_step_names("prebiotic_chemistry")[0]
    texts = [t for t, _run in e._map_actions(f"step:{step}")]
    assert any("Modules tab" in t for t in texts)
    next(run for t, run in e._map_actions(f"step:{step}") if "Modules tab" in t)()
    assert e.tabs.tabText(e.tabs.currentIndex()) == "Modules"
    e.close()


def test_filled_by_names_the_real_source():
    """column_sources.py: the steps (own and modules'), uncertainties with their value, the built-in steps, the row
    plan, calculations, formulas, the archive -- 'nothing fills this automatically' only when none does."""
    from parameter_extractor import column_sources as cs
    from parameter_extractor.pack_editing import PackDraft
    prebiotic = PackDraft.load(packs.available()["prebiotic_chemistry"].folder)
    found = cs.sources(prebiotic)
    assert any("built-in" in x for x in found["initial_NaCl_aq_mM"])
    assert found["paper_title"] == ["the paper's details (Paper details module, core)"] and \
        "the row plan (Rows module, core)" in found["set_type"]
    for f in prebiotic.manifest.get("formulas", []):
        assert any(x.startswith("formula:") for x in found[f["column"]])
    nothing = [c for c in prebiotic.columns if not found.get(c)]
    assert nothing and all(c not in prebiotic.stage_columns() for c in nothing)
    exo = PackDraft.load(packs.available()["exoplanets"].folder)
    found = cs.sources(exo)
    filled_with = {c for spec in exo.stages.values() for p in spec.get("parameters", []) if p.get("uncertainties")
                   for c in (p["column"] + "err1",)}
    assert filled_with and all(found.get(c) for c in filled_with)               # written with their value
    assert any("Archive" in x for x in found.get("sy_vmag", []))
    assert any(x.startswith("calculated") for x in found.get("pl_masse", []))
    assert not found.get("rowupdate")                                          # the archive's own bookkeeping


def test_columns_nothing_fills_are_set_apart():
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack, e = _editor(tmp)
        tree = e.column_tree
        before = list(e.draft.columns)
        parts = []
        for i in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(i)
            kids = [group.child(j) for j in range(group.childCount())]
            subs = [k.text(0) for k in kids if k.data(0, e.SUBHEADER)]
            columns = e._column_children(group)
            empty = [k for k in columns if k.text(2) == "nothing fills this automatically"]
            if empty:
                assert subs and subs[-1].startswith("Not filled automatically")
                at = kids.index(empty[0])                                     # after the filled ones, greyed
                assert all(k.text(2) != "nothing fills this automatically" for k in columns[:columns.index(empty[0])])
                assert kids[at - 1].data(0, e.SUBHEADER)
                assert empty[0].foreground(0).color() == tree.palette().color(tree.palette().ColorRole.PlaceholderText)
                parts.append(group.text(0))
        assert parts                                                          # the exoplanet pack has some
        assert sorted(e._tree_columns()) == sorted(before)                    # subheaders aren't columns
        e.close()


def test_the_map_counts_what_the_columns_tab_lists():
    """Each kind of value's count on the Map = the columns the Columns tab lists under it: the pack's own, its steps'
    unlisted ones and its linked modules' (read-only there, never saved into the pack)."""
    from parameter_extractor.gui.pack_windows import PackEditor
    from parameter_extractor.gui.structure_canvas import structure_of
    for pid in ("prebiotic_chemistry", "exoplanets"):
        pack = packs.activate(pid)
        e = PackEditor(pack.folder)
        listed = {e.column_tree.topLevelItem(i).data(0, 256): len(e._column_children(e.column_tree.topLevelItem(i)))
                  for i in range(e.column_tree.topLevelItemCount())}
        for k in structure_of(pack).kinds:
            assert k.columns == listed.get(k.id, 0), (pid, k.id, k.columns, listed.get(k.id))
        shown = [c for i in range(e.column_tree.topLevelItemCount())
                 for c in e._column_children(e.column_tree.topLevelItem(i)) if c.data(0, e.MODULE_COLUMN)]
        import pack_facts as pf
        assert bool(shown) == bool(pf.module_ids(pid) or set(e.draft.stage_columns()) - set(e.draft.columns))
        assert not any(c.flags() & c.flags().ItemIsEditable for c in shown)
        assert e._tree_columns() == [c for c in e._tree_columns() if c in set(e.draft.columns)]   # not the pack's
        assert sorted(e._tree_columns()) == sorted(e.draft.columns)
        e.close()
    packs.activate("prebiotic_chemistry")


def test_the_map_exports_as_an_image():
    from PySide6.QtGui import QImage
    from parameter_extractor.gui.pack_windows import PackEditor
    e = PackEditor(packs.available()["exoplanets"].folder)               # a read-only pack exports too
    with tempfile.TemporaryDirectory() as tmp:
        png = e.export_map(Path(tmp) / "map.png")
        img = QImage(str(png))
        assert img.width() > 2000 and img.pixelColor(1, 1).alpha() == 0      # no background
        svg = e.export_map(Path(tmp) / "map.svg")
        assert svg.read_text()[:400].count("<svg") == 1 and "Exoplanets" in svg.read_text()
        assert e.export_map(Path(tmp) / "map").suffix == ".png"
        dark = QImage(str(e.export_map(Path(tmp) / "dark.png", look="dark")))   # light text for a dark slide

        def mean_lightness(image):                                   # of what is drawn (no background)
            seen = [image.pixelColor(x, y).lightness() for x in range(0, image.width(), 9)
                    for y in range(0, image.height(), 9) if image.pixelColor(x, y).alpha() > 200]
            return sum(seen) / len(seen)
        assert dark.pixelColor(1, 1).alpha() == 0
        assert mean_lightness(QImage(str(png))) > 180 > 90 > mean_lightness(dark)   # white cards / dark cards
    e.close()



def test_the_map_heading_row_and_explanations():
    """The pack's name beside the column headings, not on a row of its own; one line under each heading; the
    whole explanation opens from the heading -- not in an exported figure (2026-11-26, Mickey)."""
    from PySide6.QtWidgets import QGraphicsSimpleTextItem, QLabel
    from parameter_extractor.gui import structure_canvas as sc
    pack = packs.available()["prebiotic_chemistry"]
    scene = sc.build_scene(pack)
    texts = {i.text(): i for i in scene.items() if isinstance(i, QGraphicsSimpleTextItem)}
    first = next(t for t in texts if pack.label.startswith(t))                       # the name's first line
    assert texts["Steps"].y() == texts["Levels"].y() == texts[first].y() == 0       # one row: name and headings
    assert {i.data(sc.INFO) for i in scene.items() if i.data(sc.INFO)} == {"steps", "levels"}
    assert len(sc.STEPS_HEAD) < 70 and len(sc.LEVELS_HEAD) < 70                     # a line each (on macOS)
    figure = sc.build_scene(pack, interactive=False)                                 # kept while it's read
    assert not any(i.data(sc.INFO) for i in figure.items())
    canvas = sc.StructureCanvas(pack)
    item = next(i for i in canvas.scene().items() if i.data(sc.INFO) == "levels")
    canvas.resize(1400, 900)
    canvas.fit()
    pos = canvas.mapFromScene(item.sceneBoundingRect().center())
    assert canvas.info_at(pos) == "levels"
    canvas.show_info("levels", canvas.viewport().mapToGlobal(pos))
    shown = canvas._info_popup.findChild(QLabel).text()
    assert "Experiment set" in shown and "one row of the dataset" in shown          # the pack's own words
    canvas._info_popup.close()


def test_the_categories_window_refills_without_leftovers():
    """Choosing another data pack in the Variable categories window: only the new rows' controls are shown (the
    replaced ones used to stay drawn while the window was open from another window)."""
    from PySide6.QtWidgets import QComboBox
    from parameter_extractor.gui.categories_dialog import CategoriesDialog
    packs.activate("prebiotic_chemistry")
    with tempfile.TemporaryDirectory() as tmp:
        dlg = CategoriesDialog(Path(tmp) / "r.json")
        dlg.area_combo.setCurrentIndex(dlg.area_combo.findData("exoplanets"))
        shown = [c for c in dlg.table.findChildren(QComboBox) if c.parentWidget().isVisibleTo(dlg)]
        assert len(shown) == dlg.table.rowCount()
        dlg.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All Columns tab category tests passed.")
