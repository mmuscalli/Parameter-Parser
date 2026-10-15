"""
Offline replay of the third reference paper, kim2019 (Astrobiology; ribonucleotide
synthesis by dry-down -- not peptides): the saved model responses in
runs/kim2019_auto/ go through the real pipeline, which must reproduce the
committed CSV exactly. Covers stock-solution concentrations, the mixture
concentrations calculated from them, concentrations calculated from molar
ratios (written by the model the other way round), PDF text quirks (tight word spacing, a
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
        assert all(r["stock_CaCl2_aq_mM"] == "15.0" and r["initial_CaCl2_aq_mM"] == "3.63636" for r in rows)
        flags = json.loads(result.flags_path.read_text())["paper_level"]
        derived = [f["message"] for f in flags if f["kind"] == "derived_value"]
        assert any("15 mM x 8 µL / 33 µL total" in m for m in derived)

        new = {v.alias_name: v for v in result.new_variables}
        # cytosine: stock stated for the 1:1 sets only; 1:2 and 1:3 calculated from the molar ratio
        cyt = {(v.alias_name, v.set_label): (v.value, v.origin) for v in result.new_variables
               if v.alias_name in ("initial cytosine", "stock cytosine")}
        assert cyt[("stock cytosine", "3:Cytosine 1:1, 100 C")] == (3.75, "chemistry")
        assert cyt[("stock cytosine", "3:Cytosine 1:2, 85 C")] == (7.5, "calculated")
        assert cyt[("stock cytosine", "3:Cytosine 1:3, 125 C")] == (11.25, "calculated")
        assert cyt[("initial cytosine", "3:Cytosine 1:1, 100 C")] == (2.27273, "calculated")
        assert cyt[("initial cytosine", "3:Cytosine 1:3, 100 C")] == (6.81818, "calculated")
        assert not any(f["kind"] == "conflicting_values" for f in flags)       # 1:1 stated values fit the ratio
        # one grouped flag for the heating temperature copied into 10 sets; missing concentrations
        # have their own flag; methodology's copies of the solution volumes are dropped, and each
        # volume is offered once, from the chemistry record
        assert sum("sampled_temperature_C has confidence 'medium' in 10 sets" in f["message"] for f in flags) == 1
        assert sorted(f["message"].split()[0] for f in flags if f["kind"] == "concentration_not_stated") == [
            "acetamide", "guanine", "uracil"]
        assert sum(f["kind"] == "duplicate_removed" for f in flags) == 4
        volumes = sorted(v.name for v in result.new_variables if v.name.startswith("volume added"))
        assert volumes == ["volume added: calcium chloride solution", "volume added: nucleobase solution",
                           "volume added: ribose 1,2-cyclic phosphate stock"]
        names = {v.name for v in result.new_variables}
        assert not names & {"nucleobase solution volume", "calcium chloride solution volume",
                            "reaction volume (ribose 1,2-cyclic phosphate solution)", "guanine dissolution medium"}
        assert "redissolution volume before analysis" in names                # not a repeat: kept
        yields = sorted(v.value for v in result.new_variables if v.alias_name == "sampled cytidine 2'-phosphate %")
        assert yields == sorted([1.7, 2.7, 0.4, 0.8, 2.8, 3.5, 5.3, 0.4, 1.0, 5.9, 3.8, 5.4, 7.7])


if __name__ == "__main__":
    test_kim2019_replay_reproduces_reference()
    print("PASS: test_kim2019_replay_reproduces_reference")
