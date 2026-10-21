"""
Offline replay of the exoplanet pack's reference paper, teng2023 (PASJ; 32
systems, 38 planets/companions, sideways tables): the saved model responses in
runs/teng2023_auto/ go through the real pipeline, which must reproduce the
committed CSV exactly; the NASA Exoplanet Archive comparison runs against the
saved archive rows (archive_rows.json) instead of the network. Covers units as
printed (rad, JD-2450000, yr), the archive's derived columns, names the archive
writes differently (eps Tau b, omi UMa b, 41 Lyn b = HD 81688 b), stellar-system
values from another reference (sy_plx from TICv8) left out of the comparison,
a parameter given by two fits (Table 3 orbit, Table 4 joint fit) and companions
too heavy to be planets. Recorded before the fitting-model stage existed, so it
runs with that stage turned off (RunConfig.optional_stages, as the GUI's
toggle does). No API calls, no network. ~1 min (42 heavy pages).

Run with: python tests/test_teng2023_replay.py
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
from parameter_extractor.pipeline import run_pipeline
from parameter_extractor.validation import exoplanet_archive
from test_pipeline_offline import make_replay

PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Teng2023" / "teng2023.pdf"
REF = ROOT / "runs" / "teng2023_auto"


def test_teng2023_replay_reproduces_reference():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    saved = json.loads((REF / "archive_rows.json").read_text())
    try:
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(api_client, "_send", make_replay(REF)), \
                patch.object(exoplanet_archive, "fetch_parameter_sets", lambda names, ref: saved):
            result = run_pipeline(PDF, RunConfig.from_settings(api_key="replay", output_dir=Path(tmp),
                                                               pack="exoplanets", online_checks=True,
                                                               optional_stages={"fit_models": "off"}))
            assert result.csv_path.read_text() == (REF / "teng2023_extracted.csv").read_text()
            assert result.observations_path.read_text() == (REF / "teng2023_observations.csv").read_text()
            report = json.loads((result.run_dir / "archive_validation.json").read_text())
            assert report == json.loads((REF / "archive_validation.json").read_text())

            rows = {r["pl_name"]: r for r in csv.DictReader(open(result.csv_path))}
            assert len(rows) == 38
            com = rows["11 Com b"]
            assert (com["pl_orbper"], com["pl_orblper"], com["pl_orbtper"]) == ("323.21", "91.32947254", "2454519.4")
            assert com["pl_bmassprov"] == "Msini" and com["pl_refname"] == "Teng et al. 2023"

            by_name = {e["pl_name"]: e for e in report}
            assert sum(e["status"] == "compared" for e in report) == 36
            assert by_name["ε Tau b"]["archive_name"] == "eps Tau b"
            assert by_name["41 Lyn b"]["archive_name"] == "HD 81688 b" and by_name["41 Lyn b"]["matched_by"]
            assert by_name["HD 5608 B"]["status"] == "planet not in the archive"   # the stellar companion, not 'b'
            assert "sy_plx" in by_name["11 Com b"]["from_other_references"]["TICv8"]
            assert not by_name["11 Com b"]["differs"]
            differing = {e["pl_name"] for e in report if e.get("differs")}
            assert differing == {"HD 14067 b", "HD 120084 b"}       # the archive took Table 4's joint fit

            flags = json.loads(result.flags_path.read_text())["paper_level"]
            conflicts = [f["message"] for f in flags if f["kind"] == "conflicting_values"]
            assert any("HD 14067 b has two values for pl_orbper" in m and "Table 4" in m for m in conflicts)
            assert not any("HD 175679 b has two values for pl_orblper" in m for m in conflicts)   # -12.7 = 347.3 deg
            heavy = sorted(f["message"].split(":")[0] for f in flags if f["kind"] == "out_of_range")
            assert heavy == ["HD 175679 b", "HD 5608 B"]
    finally:
        packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    test_teng2023_replay_reproduces_reference()
    print("PASS: test_teng2023_replay_reproduces_reference")
