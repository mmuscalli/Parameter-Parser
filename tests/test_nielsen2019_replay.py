"""
Offline replay of the exoplanet pack's second reference paper, nielsen2019
(A&A 623, A100; HD 1397 b, the first TESS planet with an EXOFASTv2 joint fit
of the transits, CORALIE + MINERVA-Australis RVs, the SED and MIST models --
an exoplanet expert's main case for the fitting-model columns). The saved
model responses in runs/nielsen2019_auto/ go through the real pipeline, which
must reproduce the committed CSV exactly; the NASA Exoplanet Archive check runs
against the saved archive rows. No API calls, no network. A few seconds.

Run with: python tests/test_nielsen2019_replay.py
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

PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Nielsen2019" / "nielsen2019.pdf"
REF = ROOT / "runs" / "nielsen2019_auto"


def test_nielsen2019_replay_reproduces_reference():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    saved = json.loads((REF / "archive_rows.json").read_text())
    try:
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(api_client, "_send", make_replay(REF)), \
                patch.object(exoplanet_archive, "fetch_parameter_sets", lambda names, ref: saved):
            result = run_pipeline(PDF, RunConfig.from_settings(api_key="replay", output_dir=Path(tmp),
                                                               pack="exoplanets", online_checks=True))
            assert result.csv_path.read_text() == (REF / "nielsen2019_extracted.csv").read_text()
            assert result.observations_path.read_text() == (REF / "nielsen2019_observations.csv").read_text()
            report = json.loads((result.run_dir / "archive_validation.json").read_text())
            assert report == json.loads((REF / "archive_validation.json").read_text())

            row = next(csv.DictReader(open(result.csv_path)))
            # the archive's Nielsen et al. 2019 set: everything compared matches, incl. the transit
            # midpoint printed as BJD_TDB and the depth printed as a fraction (converted to %)
            assert report[0]["status"] == "compared" and not report[0]["differs"]
            assert row["pl_tranmid"] == "2458332.08261" and row["pl_trandep"] == "0.2037"
            # how the values were obtained: one EXOFASTv2 joint star + planet fit
            assert row["pl_fitexofastver"] == row["st_fitexofastver"] == "2"
            assert row["pl_fitstjoint_flag"] == row["st_fitjoint_flag"] == row["pl_fitjoint_flag"] == "1"
            assert (row["pl_fitrv_flag"], row["pl_fittran_flag"], row["pl_fitsed_flag"]) == ("1", "1", "1")
            assert "CORALIE" in row["pl_fitrvinst"] and "MINERVA-Australis" in row["pl_fitrvinst"]
            assert row["pl_fittraninst"].startswith("TESS")
            assert "2MASS J, H, Ks" in row["st_fitbands"] and "WISE W1-W4" in row["st_fitbands"]
            assert row["st_fitmodels"] == "MIST"
            # priors the paper names without numbers: the shape only, the rest as printed
            assert row["sy_plxpriortype"] == row["st_loggpriortype"] == row["st_metpriortype"] == "gaussian"
            assert "Gaussian prior" in row["st_fitpriors"]
            flags = json.loads(result.flags_path.read_text())["paper_level"]
            assert any("SpecMatch-emp" in f["message"] and "produced no row" in f["message"]
                       for f in flags if f["kind"] == "fit_model")
            assert not any("= 0 for" in f["message"] for f in flags)            # text values shown as text
            assert "fit_models" in [u.stage for u in result.usage]
    finally:
        packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    test_nielsen2019_replay_reproduces_reference()
    print("PASS: test_nielsen2019_replay_reproduces_reference")
