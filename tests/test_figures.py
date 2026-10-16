"""
Offline tests for figure detection, calibration maths, rows from digitized
figures, and a full replayed run that includes a digitized figure. No API
calls.

Run with: python tests/test_figures.py
"""
import csv
import json
import math
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.digitizing.calibration import CalibrationError, pixel_to_data
from parameter_extractor.ingestion.figure_finder import find_figures
from parameter_extractor.ingestion.figure_rows import build_figure_rows
from parameter_extractor.pipeline import extract, finish
from parameter_extractor.schemas.figures import (
    AxisCalibration, AxisVariable, CalibrationPoint as C, DigitizedFigure, DigitizedPanel,
    DigitizedPoint, DigitizedSeries, FigurePlan, SpeciesAmount,
)
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from test_pipeline_offline import PDF, REPLAY_DIR, _replay_send


def _panel(x_col="duration_hr", y_col="sampled_2peptide_Gly_%yield", y_mult=1.0, log_y=False):
    # x: 0..30 over px 100..400; y: 0..1.2 over py 500..200 (pixel y grows downward)
    return DigitizedPanel(
        name="main",
        x_cal=AxisCalibration(p1=C(px=100, py=500, value=0), p2=C(px=400, py=500, value=30)),
        y_cal=AxisCalibration(p1=C(px=100, py=500, value=1 if log_y else 0),
                              p2=C(px=100, py=200, value=1000 if log_y else 1.2), log=log_y),
        x=AxisVariable(label="t/h", column=x_col),
        y=AxisVariable(label="% Gly-Gly", column=y_col, multiplier=y_mult))


def _figure(page_image="page.png", **panel_kw) -> DigitizedFigure:
    return DigitizedFigure(
        figure_id="Fig. 5", number=5, page=5, caption="test", render_scale=3.0, page_image=page_image,
        panels=[_panel(**panel_kw)],
        series=[
            DigitizedSeries(label="Na+", points=[DigitizedPoint(px=400, py=250), DigitizedPoint(px=250, py=350)],
                            initial_species=[SpeciesAmount(name="NaCl", concentration_mM=3000),
                                             SpeciesAmount(name="Gly", concentration_mM=1000)],
                            initial_temperature_C=80.0, initial_pH=2.6),
            DigitizedSeries(label="empty series"),
        ])


def test_finds_all_eder1994_figures():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp:
        figs = find_figures(str(PDF), Path(tmp))
        assert [(f.number, f.page) for f in figs] == [(1, 3), (2, 3), (3, 4), (4, 4), (5, 5)], figs
        by = {f.number: f for f in figs}
        assert by[1].figure_bbox[0] > 290 and by[4].figure_bbox[0] > 290     # right column
        assert by[3].figure_bbox[2] < 300 and by[5].figure_bbox[2] < 300     # left column
        assert by[2].caption.startswith("Fig. 2 The pH dependence")         # letter-spaced OCR repaired
        assert all(Path(f.crop_image).is_file() and Path(f.page_image).is_file() for f in figs)


def test_calibration_level_rotated_and_log():
    p = _panel()
    assert pixel_to_data(p, 250, 350) == (15.0, 0.6)

    def rot(px, py, deg=3, cx=100, cy=500):
        a = math.radians(deg); dx, dy = px - cx, py - cy
        return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)
    r = lambda c: C(px=rot(c.px, c.py)[0], py=rot(c.px, c.py)[1], value=c.value)
    pr = DigitizedPanel(x_cal=AxisCalibration(p1=r(p.x_cal.p1), p2=r(p.x_cal.p2)),
                        y_cal=AxisCalibration(p1=r(p.y_cal.p1), p2=r(p.y_cal.p2)))
    x, y = pixel_to_data(pr, *rot(250, 350))
    assert abs(x - 15) < 1e-9 and abs(y - 0.6) < 1e-9

    x, y = pixel_to_data(_panel(log_y=True), 250, 350)
    assert abs(y - 10 ** 1.5) < 1e-9
    try:
        pixel_to_data(DigitizedPanel(), 1, 1)
    except CalibrationError:
        pass
    else:
        raise AssertionError("uncalibrated panel should raise")


def test_misplaced_marker_does_not_leak_into_the_other_axis():
    """Mickey's truman2024 report: with Y2 clicked a few pixels off the axis, moving the
    cursor straight up made x drift. Each axis is now read only from its own markers."""
    p = _panel()
    p.y_cal.p2 = C(px=108, py=200, value=1.2)                  # 8 px right of the true axis
    xs = [pixel_to_data(p, 250, py)[0] for py in (480, 350, 220, 120)]
    assert all(abs(x - 15.0) < 1e-9 for x in xs), xs
    p = _panel()
    p.x_cal.p2 = C(px=400, py=494, value=30)                   # X2 6 px high
    ys = [pixel_to_data(p, px, 350)[1] for px in (120, 250, 390)]
    assert all(abs(y - 0.6) < 1e-9 for y in ys), ys
    try:
        bad = _panel(); bad.y_cal.p2 = C(px=400, py=505, value=1.2)   # Y markers along the x axis
        pixel_to_data(bad, 1, 1)
    except CalibrationError as e:
        assert "same direction" in str(e)
    else:
        raise AssertionError("axes in the same direction should be refused")


def _meta_and_method():
    meta = PaperMetadata.model_validate_json((REPLAY_DIR / "metadata.output.json").read_text())
    meth = Methodology.model_validate_json((REPLAY_DIR / "methodology.output.json").read_text())
    return meta, meth


def test_rows_from_a_digitized_figure():
    meta, meth = _meta_and_method()
    rows, problems, new_vars = build_figure_rows([_figure()], meta, meth, "001", first_set_index=14,
                                       first_entry_number=43)
    assert problems == [] and len(rows) == 2
    r1, r2 = rows                                   # sorted by x: (15 h, 0.6 %) then (30 h, 1.0 %)
    assert (r1.set_id, r1.full_id, r1.entry_number) == ("001014", "001014001", 43)
    assert r1.set_type == "Time Series"
    assert (r1.duration_hr, r1.sampled_2peptide_Gly_pct_yield) == (15.0, 0.6)
    assert (r2.duration_hr, r2.sampled_2peptide_Gly_pct_yield) == (30.0, 1.0)
    assert r1.species_mM == {"initial_NaCl_aq_mM": 3000, "initial_Gly_mM": 1000}
    assert r1.extra == {"initial_pH": 2.6} and r1.initial_temperature_C == 80.0
    assert r1.extraction_confidence == "digitized" and "Fig. 5" in r1.source_notes
    assert r1.paper_title == meta.paper_title


def test_multiplier_other_columns_and_unusable_series():
    meta, meth = _meta_and_method()
    fig = _figure(y_col="sampled_4peptide_Gly_%yield", y_mult=0.001)
    fig.panels.append(DigitizedPanel(name="uncalibrated"))
    fig.series.append(DigitizedSeries(label="orphan", panel=1, points=[DigitizedPoint(px=1, py=1)]))
    rows, problems, new_vars = build_figure_rows([fig], meta, meth, "001", 1, 1)
    assert rows[0].extra["sampled_4peptide_Gly_%yield"] == 0.0006
    assert len(problems) == 1 and "orphan" in problems[0]


def test_series_conditions_and_own_y_column():
    """alargov2002 Fig. 3: pressure given per panel in the caption ("a) 22.2 MPa"); Gly-Gly and
    diketopiperazine plotted against one shared y axis."""
    from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
    from parameter_extractor.schemas.figures import SeriesCondition
    meta, meth = _meta_and_method()
    fig = _figure(y_col="sampled_2peptide_Gly_mM")
    na = fig.series[0]
    na.conditions = [SeriesCondition(column="initial_pressure_bar", value="22.2 MPa", source="caption"),
                     SeriesCondition(column="flow_rate_mL_min", value="10 mL min-1"),
                     SeriesCondition(column="experiment_type", value="hand-operated injection system"),
                     SeriesCondition(column="injection_volume_mL", value="12 mL")]
    dkp = na.model_copy(update=dict(label="DKP", y_column="sampled_DKP_Gly_mM", conditions=[]))
    fig.series = [na, dkp]
    rows, problems, new_vars = build_figure_rows([fig], meta, meth, "001", 1, 1)
    gg, dk = row_to_template_dict(rows[0]), row_to_template_dict(rows[2])
    assert gg["initial_pressure_bar"] == 222.0 and gg["flow_rate_mL_min"] == 10.0
    assert rows[0].provenance["initial_pressure_bar"].source.endswith("caption, from '22.2 MPa'")
    assert gg["experiment_type"] == meth.experiment_type.value                 # not overwritten by text
    assert any("experiment_type takes only Batch or Flowthrough" in p for p in problems)
    assert [v.name for v in new_vars] == ["injection_volume_mL"]              # unknown column: review
    assert gg["sampled_2peptide_Gly_mM"] is not None and dk.get("sampled_2peptide_Gly_mM") is None
    assert dk["sampled_cyclo_Gly-Gly_mM"] is not None                         # its own column (new name)
    assert dk.get("initial_pressure_bar") == meth.initial_pressure_bar.value  # no condition: paper-wide


def test_replayed_run_with_a_digitized_figure():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", _replay_send):
        ex = extract(PDF, RunConfig.from_settings(api_key="replay", output_dir=Path(tmp)))
        assert [f.figure_id for f in ex.figures] == ["Fig. 1", "Fig. 2", "Fig. 3", "Fig. 4", "Fig. 5"]
        fig5 = next(f for f in ex.figures if f.number == 5)
        fig = _figure(page_image=fig5.page_image)
        fig.figure_bbox = fig5.figure_bbox
        fig.plan = FigurePlan(figure_id="Fig. 5", is_data_plot=True, plot_kind="scatter",
                              duplicates_tabulated_data=True, duplicate_note="Table 2")
        result = finish(ex, [fig], skipped_figures=["Fig. 1", "Fig. 2"])

        with open(result.csv_path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 44 and rows[-1]["full_id"] == "001014002"
        assert rows[-1]["initial_pH"] == "2.6" and rows[0]["initial_pH"] == ""
        assert rows[-1]["extraction_confidence"] == "digitized"

        figdir = result.run_dir / "figures"
        assert (figdir / "fig-5.digitized.json").is_file() and (figdir / "fig-5.digitized.png").is_file()
        record = json.loads((figdir / "fig-5.digitized.json").read_text())
        assert record["series"][0]["points"][0]["x_axis_value"] == 30.0

        status = {f["figure_id"]: f["status"] for f in result.figures}
        assert status == {"Fig. 1": "skipped", "Fig. 2": "skipped", "Fig. 3": "not digitized",
                          "Fig. 4": "not digitized", "Fig. 5": "digitized"}
        summary = json.loads((result.run_dir / "run_summary.json").read_text())
        last = summary["figures"][-1]
        assert {k: last[k] for k in ("figure_id", "status", "series", "points")} == {
            "figure_id": "Fig. 5", "status": "digitized", "series": 1, "points": 2}
        assert Path(last["annotated_image"]).is_file() and Path(last["image"]).is_file(), last
        assert any(f.kind == "possible_duplicate" for f in result.paper_flags)


def test_plan_figure_waits_for_structure_and_fails_cleanly():
    import threading, time
    from datetime import datetime
    from parameter_extractor import pipeline
    from parameter_extractor.errors import PipelineError
    from parameter_extractor.ingestion.pdf_parser import ParsedPaper
    from parameter_extractor.schemas.figures import FigureCandidate
    from parameter_extractor.schemas.structure_plan import StructurePlan

    fig = FigureCandidate(figure_id="Fig. 1", number=1, page=1, caption="", figure_bbox=(0, 0, 1, 1),
                          caption_bbox=(0, 0, 1, 1), page_image="", crop_image="", render_scale=3.0)
    parsed = ParsedPaper(paper_id="p", source_pdf="p.pdf", page_count=1, has_text_layer=True, text="t",
                         page_texts=["t"])
    structure = StructurePlan.model_validate_json((REPLAY_DIR / "structure_planner.output.json").read_text())
    calls = []
    fake_planner = lambda ctx, figure, pages, struct, *a: calls.append(struct) or "PLAN"

    def make():
        return pipeline.Extraction(ctx=None, pdf_path=Path("p.pdf"), started=datetime.now(), parsed=parsed,
                                   vocab={"species_names": [], "all_columns": []}, figures=[fig])

    with patch.object(pipeline, "run_figure_planner", fake_planner):
        ex, out = make(), []
        t = threading.Thread(target=lambda: out.append(pipeline.plan_figure(ex, fig)))
        t.start(); time.sleep(0.2)
        assert t.is_alive() and not calls, "should wait for the experiment structure"
        ex.structure = structure; ex.structure_ready.set()
        t.join(2)
        assert out == ["PLAN"] and calls == [structure]

        ex, errs = make(), []
        def run():
            try:
                pipeline.plan_figure(ex, fig)
            except PipelineError as e:
                errs.append(str(e))
        t = threading.Thread(target=run); t.start(); time.sleep(0.1)
        ex.failure = "Couldn't reach the Anthropic API."; ex.structure_ready.set()
        t.join(2)
        assert errs and "Couldn't reach" in errs[0]


def test_figure_passages_only_mention_the_figure():
    from parameter_extractor.stages.figure_planner import figure_passages
    pages = ["intro line\n" * 20 + "as shown in F i g . 2 the rate\nnext line\n" + "filler\n" * 20,
             "Figs. 1 and 2 compare\n", "no mention here\n"]
    text = figure_passages(pages, 2)
    assert "F i g . 2" in text and "Figs. 1 and 2" in text and "no mention" not in text
    assert text.count("intro line") == 4                       # window, not the whole page
    assert figure_passages(pages, 7) == "(the text doesn't mention this figure)"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All figure tests passed.")
