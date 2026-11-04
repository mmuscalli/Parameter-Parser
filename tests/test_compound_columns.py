"""
One column format for every compound (Mickey, 2026-11-04): '<role>_<name>_<phase>_<measure>', peptides named by
their sequence ('Gly-Gly', '(Gly)4', 'cyclo_Gly-Gly') instead of '<n>peptide_<AA>'; old columns convert (datasets,
saved digitizations, the registry). No API calls, no network.

Run with: python tests/test_compound_columns.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs


def test_peptide_names():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.names import match_species, peptide_length, peptide_name
    assert [peptide_name(c) for c in (["Gly"] * 2, ["Gly"] * 3, ["Gly"] * 4, ["Gly"] * 10, ["Gly"] + ["Ala"] * 4,
                                      ["Gly", "Ala", "Ala"])] == \
        ["Gly-Gly", "Gly-Gly-Gly", "(Gly)4", "(Gly)10", "Gly-(Ala)4", "Gly-Ala-Ala"]
    cases = {"diglycine": "Gly-Gly", "triglycine": "Gly-Gly-Gly", "tetraglycine": "(Gly)4", "Gly14": "(Gly)14",
             "(Gly)4": "(Gly)4", "Gly-Gly-Gly-Gly": "(Gly)4", "glycylglycine": "Gly-Gly",
             "DKP_Gly": "cyclo_Gly-Gly", "glycine diketopiperazine": "cyclo_Gly-Gly",
             # names recorded before 2026-11-04 (old answers, old datasets)
             "2peptide_Gly": "Gly-Gly", "10peptide_Gly": "(Gly)10"}
    assert {k: match_species(k)[0] for k in cases} == cases
    assert peptide_length("(Gly)10") == 10 and peptide_length("cyclo_Gly-Gly") == 2 and peptide_length("NaCl") is None


def test_one_column_format():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.flatten_to_template import column_for_solute, proposed_column_for_solute, \
        species_column
    from parameter_extractor.schemas.chemistry import SoluteEntry
    assert species_column("initial", "Gly") == "initial_Gly_aq_mM"
    assert species_column("sampled", "Gly-Gly", "aq", "%yield") == "sampled_Gly-Gly_aq_%yield"
    assert species_column("initial", "CO", "gas") == "initial_CO_gas_mM"
    assert species_column("initial", "FeS", "solid") == "initial_FeS_s_mM"
    e = lambda name, role="sampled", unit="%", phase="aq", **kw: SoluteEntry(
        name=name, role=role, phase=phase, concentration_value=1.0, concentration_unit_raw=unit,
        concentration_mM=None if unit == "%" else 1.0, quote="q", source="T1", confidence="high", **kw)
    assert column_for_solute(e("Gly-Gly")) == "sampled_Gly-Gly_aq_%yield"
    assert column_for_solute(e("(Gly)14")) is None                                 # not in the vocabulary: reviewed
    assert column_for_solute(e("Gly", "initial", "mM")) == "initial_Gly_aq_mM"
    assert column_for_solute(e("CO", "initial", "mM", "gas")) == "initial_CO_gas_mM"
    assert column_for_solute(e("CO", "initial", "mM")) is None                   # dissolved CO: a new variable
    assert proposed_column_for_solute(e("CO", "initial", "mM")) == "initial_CO_aq_mM"
    assert proposed_column_for_solute(e("4mer_A")) == "sampled_4mer_A_aq_%yield"
    assert column_for_solute(e("Gly-Gly", average=True)) is None              # averages: reviewed, as for any compound
    assert proposed_column_for_solute(e("Gly-Gly", average=True)) == "sampled_Gly-Gly_aq_avg_%yield"


def test_old_columns_convert():
    from parameter_extractor.ingestion.flatten_to_template import current_column_name as new
    cases = {"sampled_2peptide_Gly_%yield": "sampled_Gly-Gly_aq_%yield",
             "sampled_10peptide_Gly_mM": "sampled_(Gly)10_aq_mM",
             "sampled_DKP_Gly_%yield": "sampled_cyclo_Gly-Gly_aq_%yield",
             "sampled_cyclo_Val-Gly_mM": "sampled_cyclo_Val-Gly_aq_mM",
             "initial_Gly_mM": "initial_Gly_aq_mM", "initial_Gly_mM_err_plus": "initial_Gly_aq_mM_err_plus",
             "sampled_2peptide_Gly_avg_%yield": "sampled_Gly-Gly_aq_avg_%yield",
             "sampled_4mer_A_%yield": "sampled_4mer_A_aq_%yield", "sampled_foo_rate_mM_hr": "sampled_foo_aq_rate_mM_hr",
             "sampled_nicotinamide_%recovered": "sampled_nicotinamide_aq_%recovered"}
    unchanged = ["initial_NaCl_aq_mM", "initial_CO_gas_mM", "initial_SO2_gas_mL", "initial_temperature_C",
                 "initial_pH", "sampled_Gly-Gly_aq_%yield", "initial_NaCl_aq_range_mM", "total_sampled_peptides_yield",
                 "added_ImpA_stock_volume_uL", "max_peptide_length"]
    assert {c: new(c) for c in cases} == cases
    assert [new(c) for c in unchanged] == unchanged


def test_vocabulary_is_consistent():
    """Every compound column of the pack is its species' column in the one format; peptide columns are
    recognised by the convention."""
    packs.activate("prebiotic_chemistry")
    import re
    from parameter_extractor.registry import VariableRegistry, is_peptide_column
    pack = packs.current()
    names = set(pack.species_names)
    compound = [c for c in pack.template_columns
                if re.fullmatch(r"(initial|sampled|stock)_(.+)_(aq|gas|s)(_avg)?_(mM|%yield|%recovered|ratio)", c)]
    assert compound and all(re.fullmatch(r"(?:initial|sampled|stock)_(.+)_(?:aq|gas|s)_.+", c).group(1) in names
                            for c in compound)
    assert not any(re.search(r"\d+peptide_|DKP_", c) for c in pack.template_columns + list(names))
    assert {"Gly-Gly", "(Gly)10", "cyclo_Gly-Gly", "cyclo_Ala-Ala"} <= names
    assert is_peptide_column("sampled_Gly-Gly_aq_%yield") and is_peptide_column("sampled_cyclo_Val-Gly_aq_mM")
    assert not is_peptide_column("sampled_Gly-Gly-Gly-Gly_aq_mM")       # not the convention's form: '(Gly)4'
    assert not is_peptide_column("sampled_Gly_aq_mM") and not is_peptide_column("sampled_2peptide_Gly_%yield")
    reg = VariableRegistry(None)
    assert reg.is_known_column("stock_Gly-Gly_aq_mM") and reg.is_known_column("sampled_(Gly)13_aq_mM_err_minus")
    cids = json.loads(pack.species_cids_path.read_text())["species"]
    assert cids["Gly-Gly"]["cid"] == 11163 and "2peptide_Gly" not in cids


def test_registry_migrates_with_a_backup():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.registry import VariableRegistry
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "variable_registry.json"
        old = {"columns": {"sampled_10peptide_Gly_%yield": {"kind": "species", "pack": "prebiotic_chemistry"},
                           "initial_RbCl_aq_mM": {"kind": "species"}},
               "aliases": {"species:sampled 10peptide_gly %": "sampled_10peptide_Gly_%yield",
                           "species:sampled gly %": "sampled_Gly_%yield"},
               "alias_labels": {}, "alias_areas": {}, "species_ids": {"11163": "2peptide_Gly"},
               "compounds": {"prebiotic_chemistry": {"2peptide_Gly": {"active": "glycylglycine"}}}}
        path.write_text(json.dumps(old))
        reg = VariableRegistry(path)
        assert set(reg.all_columns) == {"sampled_(Gly)10_aq_%yield", "initial_RbCl_aq_mM"}
        assert reg.all_aliases["species:sampled gly %"] == "sampled_Gly_aq_%yield"
        assert reg.compounds()["Gly-Gly"]["active"] == "glycylglycine" and reg.species_ids["11163"] == "Gly-Gly"
        reg.save()
        backup = path.with_name("variable_registry.before-compound-columns-2026-11-04.json")
        assert json.loads(backup.read_text()) == old
        assert "sampled_(Gly)10_aq_%yield" in json.loads(path.read_text())["columns"]
        VariableRegistry(path).save()                                    # nothing left to migrate: unchanged
        assert json.loads(backup.read_text()) == old


def test_old_dataset_converts_and_active_names_follow():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.compound_names import convert_dataset_csv
    from parameter_extractor.registry import VariableRegistry
    with tempfile.TemporaryDirectory() as tmp:
        reg = VariableRegistry(Path(tmp) / "r.json")
        reg.set_active_name("Gly-Gly", "glycylglycine")
        old = Path(tmp) / "old.csv"
        old.write_text("full_id,initial_Gly_mM,sampled_2peptide_Gly_%yield,sampled_Gly-Gly_aq_%yield\n1,5,2.77,\n2,,,3.1\n")
        renames = convert_dataset_csv(old, Path(tmp) / "new.csv", reg)
        assert (Path(tmp) / "new.csv").read_text().splitlines() == \
            ["full_id,initial_Gly_aq_mM,sampled_glycylglycine_aq_%yield", "1,5,2.77", "2,,3.1"]
        assert renames["sampled_2peptide_Gly_%yield"] == "sampled_glycylglycine_aq_%yield"


def test_repeated_units_are_shortened_for_any_compound():
    """Mickey, 2026-11-04: the peptide rule for every polymer -- 4 or more identical hyphen-joined units."""
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.flatten_to_template import species_column
    from parameter_extractor.ingestion.normalize import normalize_chemistry
    from parameter_extractor.names import compact_repeats
    from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
    assert [compact_repeats(n) for n in ("TEST-TEST-TEST-TEST", "TEST-TEST-TEST", "A-B-B-B-B-C", "2-amino-2-methyl",
                                         "Gly-Gly-Gly-Gly-Gly", "NaCl")] == \
        ["(TEST)4", "TEST-TEST-TEST", "A-(B)4-C", "2-amino-2-methyl", "(Gly)5", "NaCl"]
    assert species_column("sampled", "Lys-Lys-Lys-Lys") == "sampled_(Lys)4_aq_mM"
    e = SoluteEntry(name="EG-EG-EG-EG-EG", role="sampled", phase="aq", concentration_value=1.0,
                    concentration_unit_raw="%", quote="q", source="T1", confidence="high")
    notes = normalize_chemistry(ChemistryExtraction(solutes=[e]))
    assert e.name == "(EG)5" and any("repeated units" in n.message for n in notes)


def test_new_peptides_are_reviewed():
    """Mickey, 2026-11-04: peptides outside the vocabulary are new compounds -- reviewed, not written directly."""
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.flatten_to_template import column_for_solute
    from parameter_extractor.ingestion.new_variables import collect_new_variables
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
    from parameter_extractor.schemas.methodology import empty_methodology
    reg = VariableRegistry(None)
    assert reg.is_known_column("sampled_Gly-Gly_aq_%yield")                  # in the pack's vocabulary
    assert not reg.is_known_column("sampled_(Gly)14_aq_%yield") and not reg.is_known_column("sampled_Gly-Ala_aq_mM")
    e = lambda name: SoluteEntry(name=name, role="sampled", phase="aq", set_label="A", concentration_value=2.0,
                                 concentration_unit_raw="%", quote="q", source="T1", confidence="high")
    assert column_for_solute(e("Gly-Ala")) is None
    found = collect_new_variables(empty_methodology("p"), ChemistryExtraction(solutes=[e("Gly-Ala"), e("Gly-Gly")]),
                                  reg, None)
    assert [(v.name, v.proposed_column) for v in found] == [("Gly-Ala", "sampled_Gly-Ala_aq_%yield")]


def test_new_oligonucleotides_are_reviewed():
    """Mickey, 2026-11-04: new compounds of ANY type are reviewed -- oligonucleotides too."""
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.registry import VariableRegistry, is_oligonucleotide_column
    reg = VariableRegistry(None)
    assert is_oligonucleotide_column("sampled_4mer_A_aq_%yield") and not reg.is_known_column("sampled_4mer_A_aq_%yield")


def test_new_peptide_on_a_figure_axis():
    """A figure whose y axis is a compound with no column yet: its rows are built (conditions, durations, ...),
    the values wait in the review under the same column the chemistry step would propose, and accepting them
    writes them onto those rows."""
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.figure_rows import build_figure_rows
    from parameter_extractor.ingestion.flatten_to_template import proposed_column_for_solute, row_to_template_dict
    from parameter_extractor.ingestion.new_variables import VariableDecision, apply_decisions, group_new_variables
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.chemistry import SoluteEntry
    from parameter_extractor.schemas.figures import (AxisCalibration, AxisVariable, CalibrationPoint, DigitizedFigure,
                                                     DigitizedPanel, DigitizedPoint, DigitizedSeries)
    from parameter_extractor.schemas.methodology import empty_methodology
    from parameter_extractor.schemas.paper_metadata import PaperMetadata
    cal = lambda a, b: AxisCalibration(p1=CalibrationPoint(px=a[0], py=a[1], value=0),
                                       p2=CalibrationPoint(px=b[0], py=b[1], value=10))
    panel = DigitizedPanel(x_cal=cal((0, 100), (100, 100)), y_cal=cal((0, 100), (0, 0)),
                           x=AxisVariable(label="time (h)", column="duration_hr"),
                           # the planner's suggestion, spelled out: canonicalised to the chemistry step's '(Lys)4'
                           y=AxisVariable(label="% Lys4", column=None, new_column="sampled_Lys-Lys-Lys-Lys_aq_%yield"))
    fig = DigitizedFigure(figure_id="Fig. 3", number=3, page=4, caption="c", render_scale=1.0, page_image="",
                          panels=[panel], series=[DigitizedSeries(label="80 C", points=[
                              DigitizedPoint(px=20, py=60), DigitizedPoint(px=50, py=30)])])
    meta = PaperMetadata(paper_id="p", paper_title="t", authors=["A"], year_published=2023, journal_published="j")
    reg = VariableRegistry(None)
    rows, problems, new_vars = build_figure_rows([fig], meta, empty_methodology("p"), "001", 1, 1, registry=reg)
    assert not problems and [r.duration_hr for r in rows] == [2.0, 5.0]             # the rows exist already
    table_entry = SoluteEntry(name="Lys-Lys-Lys-Lys", role="sampled", phase="aq", concentration_value=1.0,
                              concentration_unit_raw="%", quote="q", source="T1", confidence="high")
    groups = group_new_variables(new_vars)
    assert [g.proposed_column for g in groups] == [proposed_column_for_solute(table_entry)] == \
        ["sampled_(Lys)4_aq_%yield"]
    assert "sampled_(Lys)4_aq_%yield" not in row_to_template_dict(rows[0])          # held until accepted
    apply_decisions(rows, groups, [VariableDecision(groups[0].alias_name, groups[0].kind, "new_column",
                                                    "sampled_(Lys)4_aq_%yield", remember=False)], reg)
    assert [row_to_template_dict(r)["sampled_(Lys)4_aq_%yield"] for r in rows] == [4.0, 7.0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All compound-column tests passed.")
