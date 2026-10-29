"""
Offline tests for several passes + vote (voting.py, RunConfig.passes), data_location
(ingestion/data_location.py) and the sealed-batch atmospheric start (calculators/pressure.py).
No API calls.

Run with: python tests/test_voting.py
"""
import csv
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client, packs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.ingestion.data_location import location
from parameter_extractor.schemas.chemistry import ChemistryExtraction, SoluteEntry
from parameter_extractor.stages.optional import load_specs
from parameter_extractor.voting import disagreement_flags, vote_chemistry, vote_stage

REF = ROOT / "runs" / "reference" / "eder1994"
PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Initial Easy Papers" / "eder1994" / "eder1994.pdf"


def _conditions(values):
    """An experimental_conditions answer: [(set, column, value, unit or text)]."""
    spec = load_specs()["experimental_conditions"]
    _, Result = spec.models()
    items = []
    for set_label, column, value, extra in values:
        item = {"col": column, "v": value, "u": "", "q": "q", "src": "s", "c": "high", "set_label": set_label}
        if isinstance(extra, str) and column in ("vessel_sealed", "solvent_name"):
            item.update(v=0, txt=extra)
        elif extra:
            item["u"] = extra
        items.append(item)
    return spec, Result.model_validate({"parameters": items})


def test_most_common_given_value_wins_and_dropouts_dont_vote():
    packs.activate("prebiotic_chemistry")
    spec, p1 = _conditions([("A", "initial_temperature_C", 80, "C"), ("A", "initial_pH", 7.0, ""),
                            ("B", "initial_temperature_C", 90, "C")])
    _, p2 = _conditions([("A", "initial_temperature_C", 353.15, "K"),       # the same 80 C, other unit
                         ("A", "initial_pH", 7.5, "")])                      # B's temperature dropped
    _, p3 = _conditions([("A", "initial_temperature_C", 80, "C"), ("A", "initial_pH", 7.5, ""),
                         ("B", "initial_temperature_C", 90, "C")])
    voted, data, notes = vote_stage(spec, [p1, p2, p3])
    got = {(i.set_label, i.parameter): i.value for i in voted.parameters}
    assert got == {("A", "initial_temperature_C"): 80, ("A", "initial_pH"): 7.5, ("B", "initial_temperature_C"): 90}
    assert {(d.what, d.kind) for d in notes} == {("initial_pH", "differ"), ("initial_temperature_C", "missing")}
    assert spec.models()[1].model_validate(data).parameters[1].value == 7.5     # the saved answer reloads
    flags = disagreement_flags(notes)
    assert any("initial_pH differs between passes in 1 place" in f and "kept 7.5 (2 of 3" in f for f in flags)
    assert any("found by only some of the 3 passes" in f and "found by 2 of 3" in f for f in flags)


def test_tie_goes_to_the_earliest_pass_and_species_names_are_matched():
    common = dict(phase="aq", quote="q", source="s", confidence="high", conversion_note=None, set_label="A")
    def chem(*entries):
        return ChemistryExtraction(solutes=[SoluteEntry(**common, **e) for e in entries])
    a = chem(dict(name="Gly-Gly", role="initial", concentration_value=10, concentration_unit_raw="mM"))
    b = chem(dict(name="glycylglycine", role="initial", concentration_value=10, concentration_unit_raw=None),
             dict(name="NaCl", role="initial", concentration_value=1, concentration_unit_raw="M"))
    voted, data, notes = vote_chemistry([a, b])
    gly = next(s for s in voted.solutes if s.name in ("Gly-Gly", "glycylglycine"))
    assert gly.concentration_unit_raw == "mM"               # same species and value; the copy with a unit kept
    assert [s.name for s in voted.solutes].count("NaCl") == 1
    assert [d.what for d in notes] == ["NaCl (initial)"]    # only in one of the passes
    assert ChemistryExtraction.model_validate(data).solutes[0].concentration_value == 10


def test_three_passes_through_the_pipeline():
    """eder1994's reference answers as every pass: same CSV as one pass, each pass kept, no disagreements."""
    if not (PDF.is_file() and REF.is_dir()):
        print("SKIP: needs eder1994.pdf and runs/reference/eder1994"); return
    from test_pipeline_offline import make_replay
    from parameter_extractor.pipeline import run_pipeline
    seen = []
    replay = make_replay(REF)

    def send(ctx, **kw):
        seen.append(getattr(api_client._streamed, "pass_suffix", ""))
        return replay(ctx, **kw)
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", send):
        result = run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp), registry_path=None,
                                                           passes=3))
        assert result.csv_path.read_text() == (REF / "expected_extracted.csv").read_text()
        assert sorted(s for s in seen if s) == sorted([".pass1", ".pass2", ".pass3"] * 2)   # chemistry + conditions
        for stage in ("chemistry", "experimental_conditions"):
            assert all((result.run_dir / f"{stage}.pass{i}.output.json").is_file() for i in (1, 2, 3))
            assert json.loads((result.run_dir / f"{stage}.audit.json").read_text())["voted_from"] == 3
        assert not [f for f in result.paper_flags if f.kind == "pass_disagreement"]
        summary = json.loads((result.run_dir / "run_summary.json").read_text())
        assert summary["config"]["passes"] == 3


def test_data_location_format():
    assert location("Table 1, Na+ 3.33 mol dm-3 row, t = 97.3 h") == "Table. 1"
    assert location("Fig. 3a") == "Figure. 3a" and location("Figure 2 (b)") == "Figure. 2b"
    assert location("Supplementary Table 3") == "Table. S3" and location("Table S2, row 4") == "Table. S2"
    assert location("", "Results section, paragraph 2") == "Text: Results section"
    assert location("Experimental", "Table 2") == "Table. 2"      # the first source naming one wins
    if REF.is_dir():
        rows = list(csv.DictReader(open(REF / "expected_extracted.csv")))
        assert {r["data_location"] for r in rows} == {"Table. 1", "Table. 2"}


def test_sealed_batch_starts_at_atmospheric_pressure():
    from parameter_extractor.calculators.pressure import assume_atmospheric_start
    from parameter_extractor.schemas.row_schema import ExtractedRow
    base = dict(set_type="Independent", entry_number=1, paper_title="t", authors=["A"], year_published=2020,
                journal_published="j", solution_type="Wet")
    rows = [ExtractedRow(full_id=f"00100{i}001", set_id=f"00100{i}", sample_id="001", experiment_type=e,
                         initial_pressure_bar=p, extra={"vessel_sealed": v} if v else {}, **base)
            for i, (e, v, p) in enumerate([("Batch", "sealed", None), ("Batch", "sealed", None),
                                           ("Batch", "sealed", 20.0), ("Batch", "open", None),
                                           ("Flowthrough", "sealed", None), ("Batch", "", None)], start=1)]
    [message] = assume_atmospheric_start(rows)
    assert [r.initial_pressure_bar for r in rows] == [1.0, 1.0, 20.0, None, None, None]
    assert "2 row(s) in 2 set(s)" in message and "1 bar (atmospheric)" in message
    assert rows[0].provenance["initial_pressure_bar"].origin.startswith("assumed")
    assert assume_atmospheric_start(rows[-1:], paper_wide_sealed="sealed")           # a digitized row
    assert rows[-1].initial_pressure_bar == 1.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All voting / location / pressure tests passed.")
