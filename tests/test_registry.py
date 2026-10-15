"""
Offline tests for the local variable registry and the "Remembered variables"
window: rename/remove added columns, change/remove synonyms, Save vs Cancel,
built-in columns protected, and the effect on the next run. No API calls.

Run with: python tests/test_registry.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor.registry import VariableRegistry


def _seeded(path: Path) -> VariableRegistry:
    reg = VariableRegistry(path)
    reg.add_column("initial_RbCl_aq_mM", "species")
    reg.add_alias("species", "initial RbCl", "initial_RbCl_aq_mM")
    reg.add_alias("species", "initial rubidium chloride", "initial_RbCl_aq_mM")
    reg.add_column("stirring_rate_rpm", "parameter")
    reg.add_alias("parameter", "stirring rate", "stirring_rate_rpm")
    reg.add_alias("parameter", "reaction volume", "solvent_volume_mL")      # mapped to a template column
    reg.save()
    return VariableRegistry(path)


def test_registry_management():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.json"
        reg = _seeded(path)
        assert reg.aliases_to("initial_RbCl_aq_mM") == ["species:initial rbcl", "species:initial rubidium chloride"]

        reg.rename_column("stirring_rate_rpm", "stirring_speed_rpm")
        assert reg.alias_for("parameter", "stirring rate") == "stirring_speed_rpm"
        for bad in ("solvent_volume_mL", "initial_RbCl_aq_mM"):                    # existing names
            try:
                reg.rename_column("stirring_speed_rpm", bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"rename onto existing '{bad}' should fail")
        try:
            reg.rename_column("duration_hr", "x")                                  # template: protected
        except ValueError:
            pass
        else:
            raise AssertionError("template columns can't be renamed")
        assert reg.remove_column("duration_hr") == []                              # template: untouched
        assert reg.is_known_column("duration_hr")

        removed = reg.remove_column("initial_RbCl_aq_mM")
        assert len(removed) == 2 and reg.alias_for("species", "initial RbCl") is None
        reg.remove_alias("parameter:reaction volume")
        reg.set_alias_column("parameter:stirring rate", "solvent_volume_mL")
        reg.save()

        saved = json.loads(path.read_text())
        assert set(saved["columns"]) == {"stirring_speed_rpm"}
        assert saved["aliases"] == {"parameter:stirring rate": "solvent_volume_mL"}


def test_registry_window_save_and_cancel():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("SKIP: PySide6 not installed"); return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.registry_dialog import RegistryDialog
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.json"
        _seeded(path)
        before = path.read_text()

        dlg = RegistryDialog(path)
        cols = [dlg.columns_table.item(r, 0).text() for r in range(dlg.columns_table.rowCount())]
        assert cols == ["initial_RbCl_aq_mM", "stirring_rate_rpm"]
        assert dlg.columns_table.item(0, 3).text() == ("RbCl (starting concentration), "
                                                       "rubidium chloride (starting concentration)")
        names = sorted(dlg.alias_table.item(r, 0).text() for r in range(dlg.alias_table.rowCount()))
        assert names == ["RbCl (starting concentration)", "reaction volume",
                         "rubidium chloride (starting concentration)", "stirring rate"]
        assert dlg.alias_table.rowCount() == 4
        dlg.remove_column("initial_RbCl_aq_mM")
        dlg.reject()                                                               # Cancel: nothing saved
        assert path.read_text() == before

        dlg = RegistryDialog(path)
        dlg.remove_column("initial_RbCl_aq_mM")
        assert dlg.rename_column("stirring_rate_rpm", "stirring_speed_rpm")
        dlg.remove_alias("parameter:reaction volume")
        assert dlg.alias_table.rowCount() == 1
        dlg._save()
        saved = json.loads(path.read_text())
        assert saved["columns"].keys() == {"stirring_speed_rpm"}
        assert saved["aliases"] == {"parameter:stirring rate": "stirring_speed_rpm"}
        assert saved["alias_labels"] == {"parameter:stirring rate": "stirring rate"}

        empty = RegistryDialog(Path(tmp) / "none.json")                           # no file yet
        assert empty.columns_table.rowCount() == 0 and empty.alias_table.rowCount() == 0


def test_removed_choice_is_reviewed_again():
    """After removing a remembered column, the variable goes back to the review."""
    from test_new_variables import PDF, _run
    from parameter_extractor.ingestion.new_variables import VariableDecision
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.json"
        _run(Path(tmp), path, review=lambda *a: [
            VariableDecision("initial RbCl", "species", "new_column", "initial_RbCl_aq_mM")])
        reg = VariableRegistry(path)
        reg.remove_column("initial_RbCl_aq_mM")
        reg.save()
        seen = []
        _run(Path(tmp), path, review=lambda groups, *a: seen.extend(g.alias_name for g in groups) or [])
        assert "initial RbCl" in seen


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All registry tests passed.")
