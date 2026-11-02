"""
Offline tests for the dataset's column order (column_order.py, Mickey 2026-11-02): row identifiers, then
one block per variable category in its table_order -- configured in the categories, not coded -- then
provenance. No API calls.

Run with: python tests/test_column_order.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs
from parameter_extractor.column_order import ColumnOrder


def test_prebiotic_blocks_and_derived_columns():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.flatten_to_template import template_columns
    from parameter_extractor.registry import standard_columns
    order = ColumnOrder(chosen={"light_conditions": "methodology", "mixing_rate_rpm": "conditions"})
    extra = ["initial_ImpA_aq_mM", "stock_ImpA_aq_mM", "added_ImpA_stock_volume_uL", "light_conditions",
             "mixing_rate_rpm", "solid_material_mass_range_g", "sampled_2peptide_Gly_avg_%yield",
             "max_linear_oligomer_length_avg_nt", "unclaimed_thing", "source_notes", "extraction_confidence"]
    cols = order.ordered(template_columns() + standard_columns() + extra)
    assert cols[:4] == ["entry_number", "full_id", "set_id", "sample_id"]
    assert cols[-2:] == ["source_notes", "extraction_confidence"]
    labels = [label for label, _ in order.groups(cols)]
    assert labels == ["Row", "Metadata", "Experimental Methodology", "Reaction Conditions", "Analysis",
                      "Solution Preparation", "Starting Species", "Products", "Other", "Provenance"]
    block = {c: label for label, cs in order.groups(cols) for c in cs}
    assert block["light_conditions"] == block["positive_control"] == "Experimental Methodology"   # chosen
    assert block["mixing_rate_rpm"] == block["solid_material_mass_range_g"] == "Reaction Conditions"
    assert block["stock_ImpA_aq_mM"] == block["initial_NaCl_aq_mM"] == "Starting Species"
    assert block["sampled_2peptide_Gly_avg_%yield"] == block["max_linear_oligomer_length_avg_nt"] == "Products"
    assert block["added_ImpA_stock_volume_uL"] == "Solution Preparation" and block["unclaimed_thing"] == "Other"
    i = cols.index("initial_temperature_C")      # a value, its uncertainties, then other estimates
    assert cols[i:i + 4] == ["initial_temperature_C", "initial_temperature_C_err_plus",
                             "initial_temperature_C_err_minus", "initial_temperature_C_alt1"]
    j = cols.index("solid_material_mass_g")              # a range sits right after its value
    assert cols[j + 1:j + 3] == ["solid_material_mass_range_g", "solid_material_mass_g_alt1"]
    # 'Other' is a category the model may choose (the shared file)
    from parameter_extractor.variable_categories import assignable
    assert "other" in [c.id for c in assignable()]


def test_registry_remembers_the_category():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.registry import VariableRegistry
    with tempfile.TemporaryDirectory() as tmp:
        reg = VariableRegistry(Path(tmp) / "r.json")
        reg.add_column("vortex_time_s", "parameter", category="methodology")
        reg.save()
        reg = VariableRegistry(Path(tmp) / "r.json")
        assert ColumnOrder(registry=reg).label_of("vortex_time_s") == "Experimental Methodology"


def test_exoplanet_blocks():
    try:
        packs.activate("exoplanets")
        order = ColumnOrder()
        cols = order.ordered(["pl_orbpererr2", "st_teff", "pl_orbper", "pl_name", "sy_dist", "disc_year",
                              "pl_fitlabel", "pl_orbpererr1", "hostname", "full_id", "paper_title"])
        assert cols == ["full_id", "pl_name", "hostname", "paper_title", "disc_year", "pl_orbper", "pl_orbpererr1",
                        "pl_orbpererr2", "st_teff", "sy_dist", "pl_fitlabel"]
        assert [l for l, _ in order.groups(cols)] == ["Row", "Metadata", "Discovery", "Planet parameters",
                                                      "Stellar parameters", "System and position", "Fitting models"]
        from parameter_extractor.variable_categories import assignable
        assert not {"planet", "star", "system"} & {c.id for c in assignable()}    # column groups only
    finally:
        packs.activate("prebiotic_chemistry")


def test_a_pack_configures_its_own_blocks():
    """A new pack: its own column-only category and columns added to a shared one, in pack.json."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "order_demo"
        folder.mkdir()
        (folder / "pack.json").write_text(json.dumps({
            "id": "order_demo", "label": "Order demo", "template": "template.json",
            "variable_categories": [{"id": "samples", "label": "Samples", "model_assigns": False,
                                     "table_order": 15, "patterns": ["^sample_"]}],
            "category_columns": {"methodology": {"columns": ["instrument", "method"]},
                                 "metadata": {"columns": ["site"], "table_order": 5}}}))
        (folder / "template.json").write_text(json.dumps({
            "all_columns": ["full_id", "method", "sample_mass_g", "result_value", "site", "instrument"],
            "species_names": []}))
        packs.add_search_dir(Path(tmp))
        try:
            pack = packs.activate("order_demo")
            order = ColumnOrder(pack)
            cols = order.ordered(pack.template_columns + ["paper_title"])
            assert cols == ["full_id", "site", "paper_title", "sample_mass_g", "instrument", "method", "result_value"]
            assert [l for l, _ in order.groups(cols)] == ["Row", "Metadata", "Samples", "Experimental Methodology",
                                                          "Other"]
        finally:
            packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All column order tests passed.")
