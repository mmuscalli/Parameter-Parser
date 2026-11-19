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
