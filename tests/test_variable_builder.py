"""
Offline tests for Build columns… (variable_builder.py, gui/variable_builder.py; Mickey, 2026-11-24): compounds typed by
the user identified by the app's name rules and a stand-in PubChem, their columns in the app's compound format, a
value's column by the app's conventions, and the dialog writing all of it into a user's data pack. No network.

Run with: python tests/test_variable_builder.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs  # noqa: E402
from parameter_extractor import variable_builder as vb  # noqa: E402


class FakePubChem:
    """Names -> CIDs as PubChem has them (glycine 750, sodium chloride 5234, ribose 5-phosphate 77982)."""
    HITS = {"glycine": (750, "Glycine"), "nacl": (5234, "Sodium Chloride"), "sodium chloride": (5234, "Sodium Chloride"),
            "ribose 5-phosphate": (77982, "Ribose 5-phosphate")}

    def lookup(self, name):
        hit = self.HITS.get(name.lower())
        return SimpleNamespace(cid=hit[0], title=hit[1]) if hit else None

    def synonyms(self, cid):
        return [f"synonym of {cid}"]

    def save(self):
        pass


def test_compounds_identified_and_their_columns():
    found = vb.identify(["glycine", "mgcl2", "diglycine", "ribose 5-phosphate", "sodium chloride", "nothing known"],
                        FakePubChem(), [{"name": "NaCl", "cid": 5234}])
    by = {m.entered: m for m in found}
    assert by["glycine"].name == "Gly" and by["glycine"].cid == 750 and "name rules" in by["glycine"].how
    assert by["mgcl2"].name == "MgCl2" and "element case" in by["mgcl2"].how
    assert by["diglycine"].name == "Gly-Gly"
    assert by["ribose 5-phosphate"].cid == 77982 and by["ribose 5-phosphate"].synonyms == ["synonym of 77982"]
    assert by["sodium chloride"].name == "NaCl" and by["sodium chloride"].known        # the pack's own, same CID
    assert by["nothing known"].cid == 0 and "not identified" in by["nothing known"].how
    cols = vb.compound_columns("Gly-Gly", ["initial", "sampled", "stock"], "aq", ["mM", "%yield"])
    assert cols == ["initial_Gly-Gly_aq_mM", "sampled_Gly-Gly_aq_mM", "sampled_Gly-Gly_aq_%yield", "stock_Gly-Gly_aq_mM"]
    assert vb.compound_columns("CO2", ["sampled"], "gas", ["mM"]) == ["sampled_CO2_gas_mM"]


def test_values_follow_the_apps_conventions():
    assert vb.value_column("reaction temperature", "K").column == "initial_temperature_C"     # the app's own column
    v = vb.value_column("stirring rate", "rpm")
    assert (v.column, v.unit) == ("stirring_rate_rpm", "rpm")
    assert vb.value_column("catalyst loading", "mg").column == "catalyst_loading_g"           # stored in g
    assert vb.value_column("light source", "", "text").column == "light_source"
    assert "elsewhere" in vb.value_column("reaction time", "min").note                         # duration_hr is a row column
    assert vb.parameter_entry(v, uncertainties=True) == {"column": "stirring_rate_rpm", "description": "stirring rate",
                                                         "unit": "rpm", "uncertainties": True}
    assert vb.valid_column("a b") and not vb.valid_column("ok_col")


def test_the_dialog_writes_them_into_a_data_pack():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui import variable_builder as gvb
    from parameter_extractor.pack_editing import PackDraft
    from parameter_extractor import pubchem as pubchem_module
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = packs.create_pack("built_cols", "Built columns", base=Path(tmp))
        draft = PackDraft.load(pack.folder)
        step = next(iter(draft.stages))
        with patch.object(pubchem_module, "PubChem", lambda *_a, **_k: FakePubChem()):
            dlg = gvb.VariableBuilderDialog(pack.folder, start="compounds")
            dlg.names_edit.setPlainText("glycine\nribose 5-phosphate\nnothing known")
            dlg.pubchem_box.setChecked(True)
            dlg._identify()
        assert dlg.table.rowCount() == 3
        assert dlg.table.item(2, gvb.C_USE).checkState() == Qt.CheckState.Unchecked  # not identified: not ticked
        dlg.measure_boxes["%yield"].setChecked(False)
        app.processEvents()
        assert dlg.compound_columns() == ["initial_Gly_aq_mM", "sampled_Gly_aq_mM", "initial_ribose_5-phosphate_aq_mM",
                                          "sampled_ribose_5-phosphate_aq_mM"]
        dlg.tabs.setCurrentIndex(1)
        dlg.v_name.setText("stirring rate")
        dlg.v_quantity.setCurrentIndex(dlg.v_quantity.findData(next(q for q, us in vb.units_by_quantity().items() if "rpm" in us)))
        dlg.v_unit.setCurrentIndex(max(0, dlg.v_unit.findData("rpm")))
        dlg.v_step.setCurrentIndex(dlg.v_step.findData(step))
        dlg._add_value()
        dlg.v_name.setText("light source")
        dlg.v_kind.setCurrentIndex(1)
        dlg.v_step.setCurrentIndex(dlg.v_step.findData(gvb.NO_STEP))
        dlg._add_value()
        assert dlg.value_list.count() == 2
        dlg._apply()
        assert dlg.result() == dlg.DialogCode.Accepted and dlg.applied
        saved = PackDraft.load(pack.folder)
        assert {"Gly", "ribose 5-phosphate"} <= set(saved.species) and "nothing known" not in saved.species
        cids = saved.cids_file["species"]
        assert cids["Gly"]["cid"] == 750 and cids["Gly"]["title"] == "Glycine"
        assert "initial_Gly_aq_mM" in saved.columns and "sampled_Gly_aq_mM" in saved.columns
        assert "light_source" in saved.columns
        assert any(p["column"] == "stirring_rate_rpm" and p.get("unit") == "rpm"
                   for p in saved.stages[step]["parameters"])
        loaded = packs.Pack(pack.folder)                                           # vocabulary-defined from now on
        assert "initial_Gly_aq_mM" in loaded.template_columns and "Gly" in loaded.species_names


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All variable-builder tests passed.")
