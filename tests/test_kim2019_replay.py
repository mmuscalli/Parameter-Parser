"""
Offline replay of the third reference paper, kim2019 (Astrobiology; ribonucleotide
synthesis by dry-down -- not peptides): the saved model responses in
runs/kim2019_auto/ go through the real pipeline, which must reproduce the
committed CSV exactly. Covers stock-solution concentrations and the mixture
concentrations calculated from them, PDF text quirks (tight word spacing, a
mid-line table caption, µ in a symbol font), and a paper whose species are
almost all outside the template. No API calls, no PubChem.

Run with: python tests/test_kim2019_replay.py
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

from parameter_extractor import api_client
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pipeline import run_pipeline
from test_pipeline_offline import make_replay

PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Kim 2019" / "kim2019.pdf"
REF = ROOT / "runs" / "kim2019_auto"


def test_kim2019_replay_reproduces_reference():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", make_replay(REF)):
        result = run_pipeline(PDF, RunConfig.from_settings(api_key="replay", output_dir=Path(tmp)))
        assert result.csv_path.read_text() == (REF / "kim2019_extracted.csv").read_text()
        assert result.observations_path.read_text() == (REF / "kim2019_observations.csv").read_text()

        rows = list(csv.DictReader(open(result.csv_path)))
        assert len(rows) == 15
        assert all(r["stock_CaCl2_aq_mM"] == "15.0" and r["initial_CaCl2_aq_mM"] == "3.636" for r in rows)
        flags = json.loads(result.flags_path.read_text())["paper_level"]
        derived = [f["message"] for f in flags if f["kind"] == "derived_value"]
        assert any("15 mM x 8 µL / 33 µL total" in m for m in derived)

        new = {v.alias_name: v for v in result.new_variables}
        assert new["initial cytosine"].origin == "calculated" and new["initial cytosine"].value == 2.273
        assert new["stock cytosine"].value == 3.75
        yields = sorted(v.value for v in result.new_variables if v.alias_name == "sampled cytidine 2'-phosphate %")
        assert yields == sorted([1.7, 2.7, 0.4, 0.8, 2.8, 3.5, 5.3, 0.4, 1.0, 5.9, 3.8, 5.4, 7.7])


if __name__ == "__main__":
    test_kim2019_replay_reproduces_reference()
    print("PASS: test_kim2019_replay_reproduces_reference")
