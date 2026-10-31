"""
Offline tests for values printed as ranges ('<name>_range_<unit>' = 'low:high'), table crops
(ingestion/table_finder.py, the Tables tab), figures in supplementary information, and which images a
run keeps (RunConfig.save_images / save_all_figure_images). No API calls.

Run with: python tests/test_ranges_tables_images.py
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs
from parameter_extractor.units import format_range, parse_range, range_to_column_unit

EDER = ROOT.parent / "Paper Files" / "Paper Lists" / "Initial Easy Papers" / "eder1994" / "eder1994.pdf"
EDER_REF = ROOT / "runs" / "reference" / "eder1994"


def test_ranges_are_parsed_only_when_unambiguous():
    assert parse_range("5-6 mg") == (5.0, 6.0, "mg") and parse_range("5 mg – 6 mg") == (5.0, 6.0, "mg")
    assert parse_range("10 to 200 s") == (10.0, 200.0, "s") and parse_range("0.1–0.5 M")[:2] == (0.1, 0.5)
    for not_a_range in ("10-4 M", "1 × 10-3 M", "6-5 mg", "2.77", "5 mg - 6 g"):
        assert parse_range(not_a_range) is None, not_a_range          # OCR-lost exponent, reversed, one value
    assert format_range(5, 6) == "5:6" and range_to_column_unit(5, 6, "mg", "g")[0] == "0.005:0.006"


def test_range_columns_and_where_ranges_come_from():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.figure_rows import convert_condition
    from parameter_extractor.ingestion.flatten_to_template import (_solute_value, column_for_solute, with_range,
                                                                    without_range)
    from parameter_extractor.ingestion.new_variables import _categorised, stored_value
    from parameter_extractor.ingestion.normalize import normalize_chemistry
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    from parameter_extractor.schemas.figures import SeriesCondition
    from parameter_extractor.schemas.variables import NewVariable
    assert with_range("solid_material_mass_g") == "solid_material_mass_range_g"
    assert with_range("sampled_2peptide_Gly_%yield") == "sampled_2peptide_Gly_range_%yield"
    assert with_range("initial_pH") == "initial_pH_range" and without_range("initial_pH_range") == "initial_pH"
    registry = VariableRegistry(None)
    assert registry.is_known_column("solid_material_mass_range_g")          # the range of a known quantity
    assert not registry.is_known_column("made_up_range_g")
    # a digitized series' condition (Riggi2023's '5-6 mg' of mineral)
    cond = lambda col, v: convert_condition(SeriesCondition(column=col, value=v, source=""))
    assert cond("solid_material_mass_g", "5-6 mg") == ("solid_material_mass_range_g", "0.005:0.006", "")
    assert cond("initial_pH", "6-7") == ("initial_pH_range", "6:7", "")
    # chemistry: a range in the text (v + hi) and a range table cell ('2-4a')
    chem = ChemistryExtraction.model_validate({
        "tables": [{"src": "Table 1", "c": "high", "cols": [{"nm": "Gly-Gly", "r": "sampled", "ph": "aq", "u": "%",
                                                            "lbl": "% GlyGly"}],
                    "rows": [{"set": "A", "sample": "a", "row": "1", "v": ["2-4a"]}]}],
        "groups": [{"set": "A", "species": [{"nm": "NaCl", "r": "initial", "ph": "aq", "v": 0.1, "hi": 0.5, "u": "M",
                                             "q": "0.1-0.5 M NaCl", "src": "Methods", "c": "high"}]}]})
    normalize_chemistry(chem)
    got = {column_for_solute(s): _solute_value(s) for s in chem.solutes}
    assert got == {"initial_NaCl_aq_range_mM": "100:500", "sampled_2peptide_Gly_range_%yield": "2:4"}
    assert all(s.concentration_mM is None for s in chem.solutes)           # never used in calculations
    # a suggested variable's value ('10-200 s')
    v = _categorised(NewVariable(kind="parameter", name="residence time", alias_name="residence time",
                                 proposed_column="residence_time", value_text="10-200 s", origin="t"), "conditions")
    assert v.proposed_column == "residence_time_range_hr" and not v.format_note
    assert stored_value(v, v.proposed_column)[0] == "0.00277778:0.0555556"


def test_stage_values_with_hi_and_negative_values():
    """`hi` makes a range; a negative value with no `hi` (st_radv -27.8) is not one."""
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.stages.optional import load_specs, stage_values
    spec = load_specs()["experimental_conditions"]
    Item, _ = spec.models()
    base = dict(u="°C", q="q", src="s", c="high")
    ranged, _ = stage_values(spec, Item.model_validate(dict(col="initial_temperature_C", v=80, hi=90, **base)))
    assert {k: v.value for k, v in ranged.items()} == {"initial_temperature_range_C": "80:90"}
    single, _ = stage_values(spec, Item.model_validate(dict(col="initial_temperature_C", v=-5, **base)))
    assert {k: v.value for k, v in single.items()} == {"initial_temperature_C": -5}


def test_tables_are_cropped():
    if not EDER.is_file():
        print("SKIP: needs eder1994.pdf"); return
    from parameter_extractor.ingestion.pdf_parser import parse_pdf
    from parameter_extractor.ingestion.table_finder import find_tables
    parsed = parse_pdf(str(EDER))
    with tempfile.TemporaryDirectory() as tmp:
        tables = find_tables(str(EDER), sorted(parsed.table_pages), Path(tmp), captions=parsed.table_pages)
        assert [(t["table_id"], t["page"]) for t in tables] == [("Table 1", 3), ("Table 2", 4), ("Table 3", 4)]
        from PIL import Image
        sizes = [Image.open(t["image"]).size for t in tables]
        assert all(w > 1000 for w, h in sizes) and all(h < 450 for w, h in sizes), sizes   # full width, table only


def test_supplement_figures_are_offered():
    from test_supplements_averages import _pdf
    from parameter_extractor.ingestion.figure_finder import find_figures
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _pdf(d / "paper_SI.pdf", ["Methods in more detail", "Figure S1. 1H NMR spectrum of the product"])
        _pdf(d / "paper.pdf", ["Figure S1. shows the spectrum (cited from the SI)"])
        [fig] = find_figures(str(d / "paper_SI.pdf"), d / "figures", supplement=True, page_offset=5)
        assert (fig.figure_id, fig.page, fig.page_label, fig.tag) == ("Fig. S1", 7, "S2", "S1")
        assert Path(fig.crop_image).name == "fig-S1.png"
        assert find_figures(str(d / "paper.pdf"), d / "main") == []          # 'Figure S1' isn't the paper's Fig. 1
        from parameter_extractor.stages.figure_planner import figure_passages
        text = ["Spectra are in Figure S1 and Fig. 1.", "Unrelated"]
        assert "Figure S1" in figure_passages(text, 1, supplement=True)


def test_images_kept_by_the_options():
    if not (EDER.is_file() and EDER_REF.is_dir()):
        print("SKIP: needs eder1994.pdf and runs/reference/eder1994"); return
    from test_pipeline_offline import make_replay
    from parameter_extractor import api_client
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.pipeline import run_pipeline
    for options, figures_kept, tables_kept in (({}, 0, 3), ({"save_all_figure_images": True}, 5, 3),
                                               ({"save_images": False}, 0, 0)):
        with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", make_replay(EDER_REF)):
            result = run_pipeline(EDER, RunConfig.from_settings(api_key="x", output_dir=Path(tmp),
                                                                registry_path=None, **options))
            crops = list((result.run_dir / "figures").glob("fig-*.png"))
            assert len(crops) == figures_kept, (options, crops)
            assert len(list((result.run_dir / "tables").glob("*.png"))) == tables_kept, options
            assert len(result.tables) == tables_kept and result.csv_path.read_text() == \
                (EDER_REF / "expected_extracted.csv").read_text()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All range / table / image tests passed.")
