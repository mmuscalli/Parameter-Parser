"""
Offline tests for the 2026-11-03 token pass and the new prebiotic parameters: table crops sent instead of
whole table pages (with the whole-page fallback), slimmer tool schemas, the figure planner's column list,
conditions said once per figure, and pH_buffer / reagent_suppliers / replicates / stirring_agitation.
No API calls.

Run with: python tests/test_token_pass.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs

EDER = ROOT.parent / "Paper Files" / "Paper Lists" / "Initial Easy Papers" / "Eder1994" / "eder1994.pdf"


def test_table_crops_replace_whole_pages():
    if not EDER.is_file():
        print("SKIP: needs eder1994.pdf"); return
    from PIL import Image
    from parameter_extractor.api_client import _piece_label
    from parameter_extractor.ingestion.pdf_parser import parse_pdf, rasterize_table_pages
    parsed = parse_pdf(str(EDER))
    with tempfile.TemporaryDirectory() as tmp:
        pages = rasterize_table_pages(parsed, Path(tmp) / "pages", crop_tables=False)
        crops = rasterize_table_pages(parsed, Path(tmp) / "crops")
        assert sorted(crops) == sorted(pages) == [3, 4]
        assert [p.name for p in crops[4]] == ["page-4-table2.jpg", "page-4-table3.jpg"]
        area = lambda d: sum(Image.open(p).size[0] * Image.open(p).size[1] for v in d.values() for p in v)
        assert area(crops) < 0.35 * area(pages)                  # eder1994: ~10K -> ~2.5K image tokens
        assert _piece_label(crops[3][0]) == "Page 3, Table 1 (the table cropped from the page):"
        for name in ("page-2-tableS1-1of2.jpg", "page-2-table1-1of2.jpg"):     # a supplement's table: 'S' once
            assert _piece_label(Path("x/SI") / name).startswith("Supplementary information page S2, Table S1, piece 1 of 2")
    # a page where a captioned table isn't found goes whole
    parsed.table_pages[4] = list(parsed.table_pages[4]) + ["Table 9 Something not on the page"]
    with tempfile.TemporaryDirectory() as tmp:
        crops = rasterize_table_pages(parsed, Path(tmp))
        assert [p.name for p in crops[3]] == ["page-3-table1.jpg"]
        assert all(p.name.startswith("page-4") and "table" not in p.name for p in crops[4])


def test_tool_schemas_without_titles_and_docstrings():
    from parameter_extractor.api_client import model_facing_schema
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    full = ChemistryExtraction.model_json_schema()
    slim = model_facing_schema(full)
    text = json.dumps(slim)
    assert '"title"' not in text and "2026-10-27" not in text            # no generated titles / developer notes
    assert slim["$defs"]["SoluteEntry"]["properties"]["avg"]["description"] == \
        full["$defs"]["SoluteEntry"]["properties"]["avg"]["description"]   # field descriptions stay
    assert len(text) < 0.85 * len(json.dumps(full))


def test_figure_planner_columns_and_shared_conditions():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.gui.digitizer import _with_shared
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.figures import SeriesCondition
    from parameter_extractor.stages.figure_planner import planner_columns
    cols = planner_columns(list(dict.fromkeys(packs.current().vocab["all_columns"]
                                              + VariableRegistry(None).known_columns())))
    assert {"initial_temperature_C", "solid_material_name", "sampled_2peptide_Gly_%yield", "negative_control",
            "pH_buffer"} <= set(cols)
    assert not {"full_id", "paper_title", "data_location", "initial_temperature_C_err_plus",
                "initial_temperature_C_alt1", "source_notes"} & set(cols)
    shared = [SeriesCondition(column="solid_material_mass_g", value="5-6 mg", source="Methods"),
              SeriesCondition(column="solid_material_type", value="clay", source="")]
    own = [SeriesCondition(column="solid_material_name", value="pyrite", source=""),
           SeriesCondition(column="solid_material_type", value="sulfide", source="")]
    merged = [(c.column, c.value) for c in _with_shared(own, shared)]
    assert merged == [("solid_material_name", "pyrite"), ("solid_material_type", "sulfide"),
                      ("solid_material_mass_g", "5-6 mg")]                # the series' own value wins


def test_new_prebiotic_parameters():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.column_order import ColumnOrder
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.stages.optional import load_specs
    spec = load_specs()["experimental_conditions"]
    new = {"pH_buffer": "Solution Preparation", "reagent_suppliers": "Metadata",
           "replicates": "Experimental Methodology", "stirring_agitation": "Experimental Methodology"}
    assert set(new) <= set(spec.columns)
    order, registry = ColumnOrder(), VariableRegistry(None)
    assert {c: order.label_of(c) for c in new} == new and all(registry.is_known_column(c) for c in new)
    assert "pH buffers" in spec.open_ended_hint and "stirring / agitation" in spec.open_ended_hint   # not `other`
    cols = order.ordered(["paper_title", "reagent_suppliers", "data_location"])
    assert cols == ["paper_title", "data_location", "reagent_suppliers"]                  # after the paper's


def test_structure_plan_short_names():
    """The model answers with short names; the code, saved answers and other prompts keep the full ones,
    and plans recorded with the full names still load (2026-11-03)."""
    from parameter_extractor.schemas.structure_plan import StructurePlan
    short = {"sets": [{"set": "A", "type": "Time Series", "varies": "T = 80 C", "src": "Table 1", "ds": "",
                       "samples": [{"label": "t = 1 h", "hr": 1.0, "src": "Table 1, row 1"}]}],
             "n_rows": 1, "excluded": ["Fig. 2: figure only"], "notes": None}
    plan = StructurePlan.model_validate(short)
    assert plan.experiment_sets[0].samples[0].duration_hr == 1.0 and plan.excluded_data == ["Fig. 2: figure only"]
    saved = json.loads(plan.model_dump_json())
    assert "experiment_sets" in saved and saved["experiment_sets"][0]["samples"][0]["sample_label"] == "t = 1 h"
    assert StructurePlan.model_validate(saved) == plan                         # full names load too
    schema = StructurePlan.model_json_schema()
    assert schema["required"] == ["sets", "n_rows"] and "paper_id" not in schema["properties"]
    assert set(schema["$defs"]["PlannedSample"]["properties"]) == {"label", "hr", "src"}


def test_written_out_powers_in_table_cells():
    from parameter_extractor.schemas.chemistry import _cell_number
    assert [_cell_number(t) for t in ("10^-4", "10⁻⁴", "1e-4", "2 × 10^-3")] == [1e-4, 1e-4, 1e-4, 0.002]
    assert _cell_number("10-4") is None and _cell_number("10−4") is None     # a lost superscript: never guessed


def test_figure_suggestions_on_the_cached_paper_are_an_option():
    """Off by default (measured 2026-11-03: costlier from the 2nd figure on, and +3.5K tokens in every run's
    cached prefix); when on, the figure tool joins the shared tool list of papers with figures."""
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.pipeline import _paper_tools
    packs.activate("prebiotic_chemistry")
    off = RunConfig(api_key="x", output_dir=Path("/tmp"))
    on = RunConfig(api_key="x", output_dir=Path("/tmp"), figure_suggestions_on_paper=True)
    assert not off.figure_suggestions_on_paper
    assert "figure_planner" not in _paper_tools(packs.current(), off, [], has_figures=True)
    assert "figure_planner" in _paper_tools(packs.current(), on, [], has_figures=True)
    assert "figure_planner" not in _paper_tools(packs.current(), on, [], has_figures=False)


def test_series_conditions_with_restatements_and_ambient():
    from parameter_extractor.ingestion.figure_rows import convert_condition
    from parameter_extractor.schemas.figures import SeriesCondition
    packs.activate("prebiotic_chemistry")
    c = lambda col, v: convert_condition(SeriesCondition(column=col, value=v, source=""))[:2]
    assert c("duration_hr", "72 hr (3 days)") == ("duration_hr", 72.0)
    assert c("initial_temperature_C", "ambient") == ("initial_temperature_C", 25.0)
    assert c("initial_pressure_bar", "1 bar (ambient)") == ("initial_pressure_bar", 1.0)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All token-pass tests passed.")
