"""
Offline replay of the second reference paper, truman2024 (a review reproducing
wet-dry cycling data from other studies): the saved model responses in
runs/truman2024_auto/ go through the real pipeline, which must reproduce the
committed CSV exactly. Covers cited-data detection, per-sample cycle numbers,
the wet-dry step, per-sample starting concentrations and pH overrides.
No API calls.

Run with: python tests/test_truman2024_replay.py
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

PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Initial Easy Papers" / "Truman2024" / "truman2024.pdf"
REF = ROOT / "runs" / "truman2024_auto"


def test_truman2024_replay_reproduces_reference():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", make_replay(REF)):
        result = run_pipeline(PDF, RunConfig.from_settings(api_key="replay", output_dir=Path(tmp)))
        assert result.csv_path.read_text() == (REF / "truman2024_extracted.csv").read_text()
        assert result.observations_path.read_text() == (REF / "truman2024_observations.csv").read_text()
        assert "wet_dry" in [u.stage for u in result.usage]

        rows = list(csv.DictReader(open(result.csv_path)))
        assert len(rows) == 11
        assert all(r["original_data_reference"] for r in rows)            # all reproduced from other papers
        table1 = [r for r in rows if r["set_id"] == "001001"]
        assert [r["sampled_Gly-Gly_aq_%yield"] for r in table1] == ["13.96", "10.26", "9.42", "8.36"]
        assert all(r["initial_pH"] == "9.8" for r in table1) and "cycle_number" not in rows[0]
        starting = sorted(float(r["initial_Gly_aq_mM"]) for r in rows if r["sampled_Gly-Gly_aq_mM"])
        assert starting == [0.1, 1.0, 10.0, 100.0]                         # Table 2, per sample
        campbell = [r for r in rows if r["wet_phase_relative_humidity_pct"]]
        assert sorted(r["wet_phase_relative_humidity_pct"] for r in campbell) == ["30.0", "50.0", "70.0"]
        assert all(r["dry_phase_temperature_C"] == "120.0" for r in campbell)

        flags = json.loads(result.flags_path.read_text())["paper_level"]
        # one flag per publication the data is reproduced from (2026-11-03; was one per set: 8)
        refs = {r["original_data_reference"] for r in rows if r["original_data_reference"]}
        assert sum(f["kind"] == "cited_data" for f in flags) == len(refs) < 8
        assert not any(f["kind"] == "assumed_value" for f in flags)
        # Table 1's stated totals are kept. Peptides outside the vocabulary await the review (2026-11-04: (Gly)7,
        # (Gly)9-13 % yields have no column), so before it the accepted yields don't add up to the stated
        # totals -- each row flagged; the Campbell sets name only such lengths, so they have nothing to check
        assert [r["total_sampled_peptides_yield"] for r in table1] == ["47.15", "39.42", "33.45", "28.9"]
        conflicting = [f["message"] for f in flags if f["kind"] == "conflicting_values"]
        assert len(conflicting) == 4 and all("total peptide yield" in m for m in conflicting)
        assert "sampled_(Gly)13_aq_%yield" not in rows[0]                # a new compound: reviewed first
        new_vars = json.loads((result.run_dir / "new_variables.json").read_text())["left_out"]
        assert "sampled_(Gly)13_aq_%yield" in {v["proposed_column"] for v in new_vars}


if __name__ == "__main__":
    test_truman2024_replay_reproduces_reference()
    print("PASS: test_truman2024_replay_reproduces_reference")
    print("All truman2024 replay tests passed.")
