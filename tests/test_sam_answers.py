"""
Offline tests for Mickey's answers to the Sam Papers questions (2026-11-03): nucleic-acid naming and oligomer
columns, duration ranges, paper kinds, uncertainties and rates of species values, kinetics units and stage,
whole-number snapping, error bars (digitizer, detection, rows), PubChem synonyms and active compound names.
No API calls, no network.

Run with: python tests/test_sam_answers.py
"""
import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs


def test_oligonucleotide_names():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.names import match_species, oligonucleotide_match
    from parameter_extractor.registry import VariableRegistry, is_oligonucleotide_column
    cases = {"(pA)4": "4mer_A", "(Ap)3": "3mer_A", "(dT)12": "12mer_dT", "A 4-mer": "4mer_A", "4-mer of A": "4mer_A",
             "oligo(A) 10-mer": "10mer_A", "U43": "43mer_U", "adenylate tetramer": "4mer_A",
             "tetraadenylate": "4mer_A", "3mer_AAU": "3mer_AAU"}
    assert {k: oligonucleotide_match(k) for k in cases} == cases
    assert oligonucleotide_match("poly(A)") is None and oligonucleotide_match("pA3'pA") is None
    assert match_species("(pA)4")[0] == "4mer_A"
    assert is_oligonucleotide_column("sampled_4mer_A_%yield") and not is_oligonucleotide_column("sampled_A_%yield")
    reg = VariableRegistry(None)
    assert reg.is_known_column("sampled_12mer_dT_mM") and reg.is_known_column("initial_Gly_mM_err_plus")
    assert not reg.is_known_column("initial_Foo_mM_err_plus")


def test_oligomer_totals():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.calculators.oligomer_totals import fill_oligomer_totals
    from parameter_extractor.ingestion.flatten_to_template import (MAX_OLIGOMER_COLUMN, TOTAL_OLIGOMERS_COLUMN,
                                                                     row_to_template_dict, set_row_value)
    from parameter_extractor.schemas.row_schema import ExtractedRow
    row = ExtractedRow(full_id="r1", set_id="s", sample_id="r1", set_type="Independent", entry_number=1,
                       paper_title="t", authors=["A"], year_published=2024, journal_published="j",
                       experiment_type="Batch", solution_type="Wet")
    for c, v in (("sampled_1mer_A_%yield", 50.0), ("sampled_2mer_A_%yield", 10.5), ("sampled_3mer_A_%yield", 4.25),
                 ("sampled_5mer_A_%yield", "detected")):
        set_row_value(row, c, v)
    totals, lengths, differing = fill_oligomer_totals([row])
    record = row_to_template_dict(row)
    assert totals == ["r1"] and lengths == ["r1"] and not differing
    assert record[TOTAL_OLIGOMERS_COLUMN] == 14.75 and record[MAX_OLIGOMER_COLUMN] == 5      # monomer not counted


def test_structure_plan_fields():
    from parameter_extractor.schemas.structure_plan import PlannedSample, StructurePlan
    s = PlannedSample.model_validate({"label": "3-7 days", "hr": 72, "hi": 168, "src": "Table I"})
    assert (s.duration_hr, s.duration_hr_high) == (72, 168)
    assert StructurePlan(experiment_sets=[], n_rows=0).paper_kind == "experimental"
    assert StructurePlan.model_validate({"sets": [], "n_rows": 0, "kind": "review"}).paper_kind == "review"


def test_species_uncertainties_and_rates():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.flatten_to_template import error_cells
    from parameter_extractor.ingestion.new_variables import proposed_column_for_solute
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.schemas.chemistry import SoluteEntry, _cell_error
    from parameter_extractor.units import convert
    assert _cell_error("29.18 ± 2.40") == 2.4 and _cell_error("29.18") == 0
    e = SoluteEntry(name="Gly", phase="aq", role="initial", concentration_value=0.1, concentration_unit_raw="M",
                    concentration_mM=100.0, err_plus=0.01, err_minus=0.01, quote="0.1 ± 0.01 M", source="T1",
                    confidence="high")
    assert error_cells(e, "initial_Gly_mM") == {"initial_Gly_mM_err_plus": 10.0, "initial_Gly_mM_err_minus": -10.0}
    pct = SoluteEntry(name="RCP", phase="aq", role="sampled", concentration_value=29.18, concentration_unit_raw="%",
                      err_plus=2.4, err_minus=2.4, quote="29.18 ± 2.40", source="T1", confidence="high")
    assert error_cells(pct, "sampled_RCP_%yield")["sampled_RCP_%yield_err_minus"] == -2.4
    rate = SoluteEntry(name="RCP", phase="aq", role="sampled", concentration_value=0.5, concentration_unit_raw="mM/min",
                       measure="rate", quote="0.5 mM min-1", source="T2", confidence="high")
    column = proposed_column_for_solute(rate)
    assert column.endswith("_rate_mM_hr") and unit_for_column(column) == "mM/h"
    assert abs(convert(1, "min-1", "h-1") - 60) < 1e-9 and abs(convert(1, "kcal/mol", "kJ/mol") - 4.184) < 1e-9
    assert unit_for_column("rate_constant_first_order_per_hr") == "h-1"
    assert unit_for_column("activation_energy_kJ_mol_err_plus") == "kJ/mol"


def test_kinetics_stage():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor import variable_categories as vc
    from parameter_extractor.schemas.structure_plan import PlannedSample, PlannedSet, StructurePlan
    from parameter_extractor.stages.optional import load_specs
    spec = load_specs()["kinetics"]
    plan = StructurePlan(experiment_sets=[PlannedSet(set_label="A", set_type="Time Series",
                                                     varying_condition_summary="time", source_table_or_section="T1",
                                                     samples=[PlannedSample(sample_label="1 h", source="T1")])],
                         n_rows=1)
    assert spec.triggered(plan, "The pseudo-first-order rate constant was 0.2 h-1.")
    assert not spec.triggered(plan, "Glycine was heated for 3 days.")
    assert "rate_constant_first_order_per_hr" in [p.column for p in spec.parameters]
    assert vc.by_id("kinetics") is not None


def test_whole_number_snapping():
    from parameter_extractor.digitizing.calibration import pixel_to_data, snap
    from parameter_extractor.schemas.figures import AxisCalibration, AxisVariable, CalibrationPoint, DigitizedPanel
    panel = DigitizedPanel(name="a", x=AxisVariable(label="x", column=None), y=AxisVariable(label="n", column=None, decimals=1, whole_within_px=3),
                           x_cal=AxisCalibration(p1=CalibrationPoint(px=0, py=500, value=0), p2=CalibrationPoint(px=500, py=500, value=10)),
                           y_cal=AxisCalibration(p1=CalibrationPoint(px=0, py=500, value=0), p2=CalibrationPoint(px=0, py=0, value=10)))
    # 1 unit = 50 px: 2.04 (2 px off 2) -> 2; 3.5 stays 3.5; 2.1 (5 px off) -> 2.1
    for value, expected in ((2.04, 2.0), (3.5, 3.5), (2.1, 2.1)):
        px, py = snap(panel, 100, 500 - value * 50)
        assert abs(pixel_to_data(panel, px, py)[1] - expected) < 1e-6, (value, pixel_to_data(panel, px, py))


def test_error_bars_detected_and_written():
    import numpy as np
    from parameter_extractor.digitizing.auto_detect import Found, find_error_bars
    from parameter_extractor.ingestion.figure_rows import _error_bar
    from parameter_extractor.schemas.figures import AxisVariable, DigitizedPoint
    rgb = np.full((300, 300, 3), 255, np.uint8)
    rgb[100:200, 150] = 0                      # whisker 100..200 through a marker at y 150
    rgb[100, 144:157] = 0                      # caps
    rgb[199, 144:157] = 0
    rgb[145:156, 145:156] = 0                  # the marker
    found = [Found(x=150, y=150, kind="marker", color=(0, 0, 0), size=11, box=(145, 145, 155, 155))]
    bars = find_error_bars(rgb, (20, 20, 280, 280), found)
    assert 0 in bars, bars
    hi, lo = bars[0]
    assert abs(hi - 100) <= 2 and abs(lo - 199) <= 2
    pt = DigitizedPoint(px=150, py=150, err_hi_py=100, err_lo_py=200)
    to_data = lambda p: (p.px, (300 - p.py) / 10)          # 10 px per unit
    assert _error_bar(pt, 15.0, to_data, AxisVariable(label="y", column=None)) == {"_err_plus": 5.0, "_err_minus": -5.0}
    assert _error_bar(DigitizedPoint(px=1, py=2), 15.0, to_data, AxisVariable(label="y", column=None)) == {}


def test_useful_synonyms():
    from parameter_extractor.pubchem import useful_synonyms
    got = useful_synonyms(["sodium chloride", "Sodium Chloride", "7647-14-5", "UNII-451W47IQ8X", "451W47IQ8X",
                           "CHEBI:26710", "RefChem:1234", "FAPWRFPIFSIZLT-UHFFFAOYSA-N", "Table salt", "x" * 60])
    assert got == ["sodium chloride", "Table salt"]
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.compound_names import bundled
    nacl = bundled()["NaCl"]
    assert nacl["cid"] == 5234 and "sodium chloride" in nacl["synonyms"]
    assert not any(s.startswith(("UNII", "CHEBI")) for e in bundled().values() for s in e["synonyms"])


def test_active_compound_names():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.compound_names import CompoundNames, convert_dataset_csv, renames_for
    from parameter_extractor.ingestion.flatten_to_template import write_template_csv
    from parameter_extractor.registry import VariableRegistry
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "reg.json"
        reg = VariableRegistry(path)
        names = CompoundNames(reg)
        assert names.default_for("Table salt") == "NaCl" and names.default_for("glycine") == "Gly"
        assert renames_for(["initial_NaCl_aq_mM"], reg) == {}           # nothing chosen: no renames
        reg.set_active_name("NaCl", "sodium chloride")
        reg.remember_compound("ImpZ", 999, ["ImpZ", "imidazolide Z"])   # accepted in a review
        reg.save()
        reg = VariableRegistry(path)
        assert reg.compounds()["ImpZ"]["synonyms"] == ["imidazolide Z"]
        columns = ["initial_NaCl_aq_mM", "initial_NaCl_aq_mM_err_plus", "stock_NaCl_aq_mM", "initial_NaClO4_aq_mM",
                   "sampled_2peptide_Gly_mM", "initial_Gly_mM"]
        assert renames_for(columns, reg) == {"initial_NaCl_aq_mM": "initial_sodium_chloride_aq_mM",
                                             "initial_NaCl_aq_mM_err_plus": "initial_sodium_chloride_aq_mM_err_plus",
                                             "stock_NaCl_aq_mM": "stock_sodium_chloride_aq_mM"}
        names = CompoundNames(reg)
        assert names.to_default("initial_sodium_chloride_aq_mM") == "initial_NaCl_aq_mM"
        assert names.harmonize("initial_Table_salt_aq_mM") == "initial_sodium_chloride_aq_mM"
        # the dataset CSV: same place in the column order, the active name in the header
        out = Path(tmp) / "x.csv"
        write_template_csv([{"full_id": "1", "initial_NaCl_aq_mM": 5.0}], out, registry=reg)
        header = next(csv.reader(open(out)))
        assert "initial_sodium_chloride_aq_mM" in header and "initial_NaCl_aq_mM" not in header
        # an older CSV with both spellings: merged under the active name, and back
        old = Path(tmp) / "old.csv"
        old.write_text("full_id,initial_NaCl_aq_mM,initial_sodium_chloride_aq_mM\n1,5,\n2,,7\n")
        convert_dataset_csv(old, Path(tmp) / "new.csv", reg)
        assert (Path(tmp) / "new.csv").read_text().splitlines() == ["full_id,initial_sodium_chloride_aq_mM", "1,5", "2,7"]
        convert_dataset_csv(Path(tmp) / "new.csv", Path(tmp) / "back.csv", reg, to="default")
        assert (Path(tmp) / "back.csv").read_text().splitlines()[0] == "full_id,initial_NaCl_aq_mM"
        reg.set_active_name("NaCl", "NaCl")                              # back to the default
        assert "NaCl" not in {n for n, c in reg.compounds().items() if c.get("active")}


def test_offline_synonym_matching():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.normalize import normalize_chemistry
    from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
    e = SoluteEntry(name="Trisodium trimetaphosphate", phase="aq", role="initial", concentration_value=10,
                    concentration_unit_raw="mM", quote="q", source="Methods", confidence="high")
    notes = normalize_chemistry(ChemistryExtraction(solutes=[e]))
    assert e.name == "sodium_triMP" and any("PubChem synonym" in n.message for n in notes), (e.name, notes)


def test_compounds_tab():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.registry_dialog import RegistryDialog
    from parameter_extractor.registry import VariableRegistry
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "reg.json"
        dlg = RegistryDialog(path)
        leaves = dlg.leaves(dlg.compound_tree, "prebiotic_chemistry")
        nacl = next(i for i in leaves if i.text(dlg.C_NAME) == "NaCl")
        options, editable = dlg.options_for(nacl, dlg.C_ACTIVE)
        assert options[0] == ("NaCl  (default)", "NaCl") and ("sodium chloride", "sodium chloride") in options
        dlg.choose(nacl, dlg.C_ACTIVE, "sodium chloride")
        app.processEvents()
        dlg._save()
        assert VariableRegistry(path, "prebiotic_chemistry").compounds()["NaCl"]["active"] == "sodium chloride"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All Sam-answers tests passed.")
