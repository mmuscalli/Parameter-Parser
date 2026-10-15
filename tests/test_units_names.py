"""
Offline tests for unit conversion (units.py), species name matching
(names.py), the normalisation pass over chemistry output, and the review
window's "Stored as" preview. No API calls.

Run with: python tests/test_units_names.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor.ingestion.normalize import normalize_chemistry
from parameter_extractor.names import closest_names, match_species
from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
from parameter_extractor.units import convert, parse_quantity, to_column_unit


def test_parse_quantities_as_printed():
    cases = {"1 cm3": (1.0, "mL"), "0.5 mol dm-3": (0.5, "M"), "45 min": (45.0, "min"),
             "130 ºC": (130.0, "°C"), "1 × 10-3 M": (0.001, "M"), "20 µl": (20.0, "µL"),
             "300 rpm": (300.0, "rpm"), "2 cm³": (2.0, "mL"), "1.5 mol·dm⁻³": (1.5, "M"),
             "0.35 cm3 min-1": (0.35, "mL/min"), "70% RH": (70.0, "%"), "1 atm": (1.0, "atm")}
    for text, expected in cases.items():
        assert parse_quantity(text) == expected, (text, parse_quantity(text))
    for refused in ("1-4 cycles", "10–4 M", "montmorillonite", "a few hours", ""):
        assert parse_quantity(refused) is None, refused


def test_conversions():
    assert convert(45, "min", "h") == 0.75 and convert(0.5, "M", "mM") == 500
    assert abs(convert(130, "°C", "K") - 403.15) < 1e-9 and convert(1, "atm", "bar") == 1.01325
    assert convert(1, "mL", "h") is None                                   # incompatible: refused
    assert to_column_unit("45 min", None, "h").value == 0.75
    assert to_column_unit("1 cm3", None, "mL").value == 1.0
    assert to_column_unit(0.5, "mol dm-3", "mM").value == 500.0
    assert to_column_unit("300", None, "rpm").value == 300.0               # bare number: column's unit
    assert to_column_unit("montmorillonite", None, "mL") is None
    assert to_column_unit("5 g", None, "mL") is None                       # wrong dimension: refused


def test_name_matching():
    cases = {"sodium chloride": "NaCl", "NaCl(aq)": "NaCl", "calcium chloride": "CaCl2",
             "CuCl2·2H2O": "CuCl2", "CuCl₂": "CuCl2", "cupric chloride": "CuCl2", "glycine": "Gly",
             "L-alanine": "Ala", "diglycine": "2peptide_Gly", "Gly-Gly-Gly": "3peptide_Gly",
             "(Gly)2": "2peptide_Gly", "Gly14": "14peptide_Gly", "dialanine": "2peptide_Ala",
             "Ca2+": "Ca+2", "Ca++": "Ca+2", "Cl−": "Cl-", "SO4 2-": "SO4-2", "HPO4^2-": "HPO4-2",
             "ammonium chloride": "NH4Cl", "Na⁺": "Na+"}
    for name, expected in cases.items():
        got = match_species(name)
        assert got and got[0] == expected, (name, got)
    for unmatched in ("RbCl", "Ala-Gly", "Foo", "montmorillonite"):
        assert match_species(unmatched) is None, unmatched
    assert closest_names("glycineamide", ["glycinamide", "Gly"]) == ["glycinamide"]


def _entry(name, value, unit, mM, **kw):
    return SoluteEntry(name=name, in_controlled_vocab=False, phase="aq", role=kw.get("role", "initial"),
                       set_label=kw.get("set_label"), concentration_value=value, concentration_unit_raw=unit,
                       concentration_mM=mM, quote="q", source="Table 1", confidence="high")


def test_normalisation_pass():
    chem = ChemistryExtraction(paper_id="p", solutes=[
        _entry("sodium chloride", 0.5, "mol dm-3", 500.0),                 # name matched, mM fine
        _entry("glycine", 1.0, "mol dm-3", 100.0),                         # model's arithmetic wrong
        _entry("CuCl2", 25, "mM", None),                                   # mM missing -> filled
        _entry("diglycine", 2.77, "% (Gly)2", None, role="sampled"),       # %: left alone
        _entry("RbCl", 0.2, "mol dm-3", 200.0),                            # unknown name: kept
    ])
    notes = normalize_chemistry(chem)
    s = chem.solutes
    assert [x.name for x in s] == ["NaCl", "Gly", "CuCl2", "2peptide_Gly", "RbCl"]
    assert s[1].concentration_mM == 1000.0 and "the model had 100 mM" in s[1].conversion_note
    assert s[2].concentration_mM == 25.0 and "computed by the pipeline" in s[2].conversion_note
    assert s[3].concentration_mM is None
    kinds = sorted(n.kind for n in notes)
    assert kinds.count("name_matched") == 3 and kinds.count("unit_corrected") == 1 and kinds.count("unit_filled") == 1
    assert normalize_chemistry(chem) == []                                  # idempotent


def test_review_preview_shows_stored_value():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.variable_review import VariableReviewDialog
    from parameter_extractor.ingestion.new_variables import VariableGroup
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.variables import NewVariable
    g = VariableGroup(kind="parameter", name="reaction volume", alias_name="reaction volume",
                      proposed_column="solvent_volume_mL",
                      values=[NewVariable(kind="parameter", name="reaction volume", value_text="1 cm3", origin="m")])
    dlg = VariableReviewDialog([g], [], VariableRegistry(None))
    dlg._show_values(0)
    assert dlg.values_table.item(0, 2).text() == "(not added)"
    dlg.set_action(0, "existing_column", "solvent_volume_mL")
    assert dlg.values_table.item(0, 2).text().startswith("1  (read from '1 cm3')")
    dlg.set_action(0, "existing_column", "cycle_duration_hr")              # wrong dimension
    assert "not converted" in dlg.values_table.item(0, 2).text()
    assert any("can't be converted" in i for i in dlg.problems())          # blocks "Build dataset"
    g.values[0].value_text = "24 h"
    assert dlg.problems() == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All unit / name tests passed.")
