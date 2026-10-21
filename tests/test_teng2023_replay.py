"""
Offline replay of the exoplanet pack's reference paper, teng2023 (PASJ; 32
systems, sideways tables; re-recorded 2026-10-21 with one row per solution, the
fitting-model stage, posterior modes and table images for every stage, $1.85): the saved model responses in runs/teng2023_auto/
go through the real pipeline, which must reproduce the committed CSV exactly;
the NASA Exoplanet Archive comparison runs against the saved archive rows
(archive_rows.json) instead of the network. Covers units as printed (rad,
JD-2450000, yr), the archive's derived columns, names the archive writes
differently (eps Tau b, omi UMa b, 41 Lyn b = HD 81688 b), stellar-system values
from another reference (sy_plx from TICv8) left out of the comparison, planets
fit two ways (RV-only, Table 3; joint RV + astrometry, Table 4) as two rows,
the archive taking one of them, fitting models, and companions too heavy to be
planets. No API calls, no network. ~1 min (42 heavy pages).

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
                                                               pack="exoplanets", online_checks=True))
            assert result.csv_path.read_text() == (REF / "teng2023_extracted.csv").read_text()
            assert result.observations_path.read_text() == (REF / "teng2023_observations.csv").read_text()
            report = json.loads((result.run_dir / "archive_validation.json").read_text())
            assert report == json.loads((REF / "archive_validation.json").read_text())

            rows = list(csv.DictReader(open(result.csv_path)))
            assert len(rows) == 41
            com = next(r for r in rows if r["pl_name"] == "11 Com b")
            assert (com["pl_orbper"], com["pl_orblper"], com["pl_orbtper"]) == ("323.21", "91.32947254", "2454519.4")
            assert com["pl_bmassprov"] == "Msini" and com["pl_refname"] == "Teng et al. 2023"
            # one row per solution, each with its own values and how they were obtained
            hd14067 = [r for r in rows if r["pl_name"] == "HD 14067 b"]
            rv, joint = sorted(hd14067, key=lambda r: r["pl_fitlabel"].startswith("Joint"))
            assert (rv["pl_orbper"], joint["pl_orbper"]) == ("2725.81", "2744.12325")
            assert (rv["pl_bmassprov"], joint["pl_bmassprov"], joint["pl_massj"]) == ("Msini", "Mass", "15.3")
            assert (rv["pl_fitast_flag"], joint["pl_fitast_flag"]) == ("0", "1")
            assert joint["pl_fitsoftware"].startswith("orvara") and rv["pl_fitsoftware"].startswith("RadVel")
            assert rv["pl_fitstjoint_flag"] == joint["pl_fitstjoint_flag"] == "0"     # no stellar model in the fit
            assert com["st_fitsoftware"] == "isoclassify"
            assert len([r for r in rows if r["pl_name"] == "HD 175679 b"]) == 2

            by_row = {(e["pl_name"], e.get("solution", "")): e for e in report}
            assert sum(e["status"] == "compared" for e in report) == 38
            assert by_row[("ε Tau b", "RV-only Keplerian fits (Table 3)")]["archive_name"] == "eps Tau b"
            lyn = by_row[("41 Lyn b", "RV-only Keplerian fits (Table 3)")]
            assert lyn["archive_name"] == "HD 81688 b" and lyn["matched_by"]
            assert next(e for e in report if e["pl_name"] == "HD 5608 B")["status"] == "planet not in the archive"
            assert "sy_plx" in by_row[("11 Com b", "RV-only Keplerian fits (Table 3)")]["from_other_references"]["TICv8"]
            # the archive took the joint fit: the RV-only rows say so
            rv_e = by_row[("HD 14067 b", rv["pl_fitlabel"])]
            joint_e = by_row[("HD 14067 b", joint["pl_fitlabel"])]
            assert rv_e["archive_solution"] == joint["pl_fitlabel"] and "archive_solution" not in joint_e
            # Table 4's bimodal inclination: overall, prograde and retrograde values all recorded (read from the
            # page image, with uncertainties); the archive's prograde value matches mode 1
            assert (joint["pl_orbincl"], joint["pl_orbinclerr1"], joint["pl_orbinclerr2"]) == ("118.0", "31.0", "-84.0")
            assert (joint["pl_orbinclmode1"], joint["pl_orbinclmode2"], joint["pl_orbinclmodal_flag"]) == ("39.0", "141.0", "1")
            assert joint["pl_orbinclmode1desc"].startswith("i < 90")
            assert not joint_e["differs"] and joint_e["matched_mode"]["pl_orbincl"].startswith("mode 1")
            # minor differences keep the paper's values (here: uncertainties within 20% -- wording is
            # covered in test_exoplanets.py; this run read 75 Cet c's discovery names as the archive does)
            hd120084 = [e for e in report if e["pl_name"] == "HD 120084 b"]
            minor = {m["column"]: m for e in hd120084 for m in e.get("minor", [])}
            assert minor["st_masserr1"]["extracted"] == 0.31 and minor["st_masserr1"]["archive"] == 0.28
            assert not any(d["column"] == "st_masserr1" for e in hd120084 for d in e["differs"])
            # a real misreading is still caught: HD 167042 b's e is +0.033 in the paper, read as +0.003
            assert [d["column"] for d in by_row[("HD 167042 b", "RV-only Keplerian fits (Table 3)")]["differs"]] == [
                "pl_orbeccenerr1"]

            flags = json.loads(result.flags_path.read_text())["paper_level"]
            assert any("so differences here are expected" in f["message"] and "HD 14067 b" in f["message"]
                       for f in flags if f["kind"] == "archive_check")
            assert sum(f["kind"] == "multimodal" for f in flags) == 3
            heavy = sorted(f["message"].split(":")[0] for f in flags if f["kind"] == "out_of_range")
            assert heavy == ["HD 175679 b", "HD 175679 b", "HD 5608 B"]
            assert not [f for f in flags if f["kind"] == "conflicting_values"]       # solutions are separate rows
            assert "fit_models" in [u.stage for u in result.usage]
    finally:
        packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    test_teng2023_replay_reproduces_reference()
    print("PASS: test_teng2023_replay_reproduces_reference")
