"""
Offline tests for ambient conditions (calculators/ambient.py: 'ambient temperature' -> 25 °C, 'ambient
pressure' -> 1 bar, flagged) and the positive / negative control parameters, including their way onto rows
digitized from figures (Riggi2023, 2026-11-01). No API calls.

Run with: python tests/test_ambient_controls.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import packs
from parameter_extractor.calculators.ambient import apply_ambient


def _answer(rows, other=()):
    from parameter_extractor.stages.optional import load_specs
    spec = load_specs()["experimental_conditions"]
    _, Result = spec.models()
    return spec, Result.model_validate({"rows": rows, "other": list(other), "notes": ""})


def _v(col, v=0, u="", txt="", b="stated", q="q", n=""):
    item = {"col": col, "v": v, "u": u, "b": b, "q": q, "src": "Methods", "c": "high"}
    item.update({k: x for k, x in (("txt", txt), ("n", n)) if x})
    return item


def test_ambient_statement_left_in_other_becomes_values():
    """Riggi2023's answer: 'temperature conditions: ambient temperature and pressure' among `other`, and a
    1 bar quoted from the Discussion."""
    packs.activate("prebiotic_chemistry")
    quote = "Experiments were conducted at ambient temperature and pressure."
    spec, result = _answer(
        [{"set": "", "sample": "", "values": [_v("initial_pressure_bar", 1, "bar", q="enhancing ... RNA at 1 bar")]}],
        [{"nm": "temperature conditions", "cat": "conditions", "v": "ambient temperature and pressure", "q": quote,
          "src": "Methods", "c": "high"},
         {"nm": "light conditions", "cat": "conditions", "v": "dark, undisturbed", "q": "dark", "src": "Methods",
          "c": "high"}])
    messages = apply_ambient(spec, result)
    got = {v.parameter: (v.value, v.unit, v.basis, v.quote) for v in result.parameters}
    assert got["initial_temperature_C"] == (25.0, "°C", "derived", quote)
    assert got["sampled_temperature_C"][:3] == (25.0, "°C", "derived")
    assert got["initial_pressure_bar"][0] == 1.0 and got["initial_pressure_bar"][3] != quote    # stated: kept
    assert [o.name for o in result.other] == ["light conditions"]      # the ambient entry became the values
    assert len(messages) == 1 and messages[0].startswith("Ambient temperature = 25 °C by convention")
    assert "every experiment" in messages[0]


def test_ambient_pressure_and_assumed_room_temperature():
    packs.activate("prebiotic_chemistry")
    spec, result = _answer(
        [{"set": "", "sample": "", "values": [_v("initial_temperature_C", 25, "°C", b="assumed", q="at r.t. for 2 d")]},
         {"set": "B", "sample": "", "values": [_v("initial_temperature_C", 80, "°C", q="heated to 80 °C")]}],
        [{"nm": "pressure", "cat": "conditions", "v": "atmospheric pressure", "q": "under atmospheric pressure",
          "src": "Methods", "c": "high"}])
    messages = apply_ambient(spec, result)
    got = {(v.set_label, v.parameter): (v.value, v.basis) for v in result.parameters}
    assert got[("", "initial_temperature_C")] == (25, "derived")       # an 'assumed' r.t. is the convention
    assert got[("B", "initial_temperature_C")] == (80, "stated")       # stated for set B: wins there
    assert got[("", "initial_pressure_bar")] == (1.0, "derived") and not result.other
    assert len(messages) == 2 and any("1 bar" in m for m in messages)
    # a paper that says nothing about ambient conditions gets nothing
    spec, quiet = _answer([{"set": "", "sample": "", "values": [_v("initial_pH", 7)]}])
    assert apply_ambient(spec, quiet) == [] and {v.parameter for v in quiet.parameters} == {"initial_pH"}


def test_controls_are_parameters_and_reach_digitized_rows():
    packs.activate("prebiotic_chemistry")
    from parameter_extractor.ingestion.figure_rows import build_figure_rows
    from parameter_extractor.registry import VariableRegistry
    from parameter_extractor.schemas.figures import (AxisCalibration, AxisVariable, CalibrationPoint,
                                                     DigitizedFigure, DigitizedPanel, DigitizedPoint, DigitizedSeries,
                                                     SeriesCondition)
    from parameter_extractor.schemas.methodology import empty_methodology
    from parameter_extractor.schemas.paper_metadata import PaperMetadata
    from parameter_extractor.schemas.row_schema import CellSource
    from parameter_extractor.stages.optional import load_specs
    spec = load_specs()["experimental_conditions"]
    assert {"positive_control", "negative_control"} <= set(spec.columns)
    assert VariableRegistry(None).is_known_column("positive_control")
    cal = AxisCalibration(p1=CalibrationPoint(px=0, py=100, value=0), p2=CalibrationPoint(px=0, py=0, value=6))
    panel = DigitizedPanel(y_cal=cal, x=AxisVariable(label="mineral", column="solid_material_name", categorical=True),
                           y=AxisVariable(label="length", column="max_peptide_length"))
    halite = SeriesCondition(column="negative_control", value="15 mM ImpA in saturated NaCl, no solid", source="")
    fig = DigitizedFigure(figure_id="Fig. 3", number=3, page=8, caption="c", render_scale=1.0, page_image="",
                          panels=[panel], series=[DigitizedSeries(label="kaolinite", points=[DigitizedPoint(px=1, py=50)]),
                                                  DigitizedSeries(label="halite", points=[DigitizedPoint(px=2, py=50)],
                                                                  conditions=[halite])])
    src = CellSource(origin="experimental conditions (whole paper)", source="Methods")
    paper_wide = {"positive_control": ("15 mM ImpA + 5-6 mg treated montmorillonite", src),
                  "negative_control": ("15 mM ImpA, no mineral", src)}
    meta = PaperMetadata(paper_id="p", paper_title="t", authors=["A"], year_published=2023, journal_published="j")
    rows, problems, _ = build_figure_rows([fig], meta, empty_methodology("p"), "001", 1, 1,
                                          registry=VariableRegistry(None), paper_wide=paper_wide)
    assert not problems
    assert [r.extra["negative_control"] for r in rows] == ["15 mM ImpA, no mineral",
                                                         "15 mM ImpA in saturated NaCl, no solid"]   # the series' own wins
    assert {r.extra["positive_control"] for r in rows} == {"15 mM ImpA + 5-6 mg treated montmorillonite"}
    assert rows[0].provenance["positive_control"].origin.endswith("(whole paper)")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All ambient / control tests passed.")
