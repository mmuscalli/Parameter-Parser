"""
Offline tests for the long-format record (observations.csv): every value has a
row, column, unit and provenance; the wide template CSV is generated from it
unchanged. No API calls.

Run with: python tests/test_observations.py
"""
import csv
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.ingestion.figure_rows import build_figure_rows
from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
from parameter_extractor.ingestion.new_variables import VariableDecision
from parameter_extractor.ingestion.observations import (observations_to_records, rows_to_observations,
                                                        unit_for_column)
from parameter_extractor.pipeline import extract, finish, run_pipeline
from test_figures import _figure, _meta_and_method
from test_new_variables import _add_extras
from test_pipeline_offline import PDF, REPLAY_DIR, _replay_send


def test_units_from_column_names():
    cases = {"initial_NaCl_aq_mM": "mM", "sampled_2peptide_Gly_%yield": "%", "initial_temperature_C": "°C",
             "duration_hr": "h", "initial_pressure_bar": "bar", "solvent_volume_mL": "mL",
             "flow_rate_mL_min": "mL/min", "flow_cycle_duration_sec": "s", "initial_pH": "pH",
             "stirring_rate_rpm": "rpm", "vessel_material": "", "paper_title": ""}
    assert {c: unit_for_column(c) for c in cases} == cases


def test_every_value_has_provenance_and_csv_round_trips():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", _replay_send):
        result = run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp)))
        assert result.csv_path.read_text() == (REPLAY_DIR / "eder1994_auto_extracted.csv").read_text()
        obs = list(csv.DictReader(open(result.observations_path)))
        # + a calculated total per row; - one per row since the 2 authors became one author_list (2026-10-22)
        assert len(obs) == 948 + 42 - 42 and all(o["origin"] for o in obs)
        totals = [o for o in obs if o["column"] == "total_sampled_peptides_yield"]
        assert all(o["origin"] == "calculated" for o in totals) and totals[0]["value"] == "2.834"

        by = {(o["full_id"], o["column"]): o for o in obs}
        y = by[("001001001", "sampled_2peptide_Gly_%yield")]
        assert (y["value"], y["unit"], y["origin"], y["confidence"]) == ("2.77", "%", "chemistry", "high")
        assert "2.77" in y["quote"] and y["source"].startswith("Table 1")
        t = by[("001001001", "initial_temperature_C")]
        assert t["origin"] == "experimental conditions" and t["unit"] == "°C"

        # pivoting the observations back gives exactly the wide records
        rows = result.rows
        pivot = observations_to_records(rows_to_observations(rows))
        direct = [{k: v for k, v in row_to_template_dict(r).items() if v not in (None, "")} for r in rows]
        assert pivot == direct


def test_provenance_of_figure_and_accepted_values():
    meta, meth = _meta_and_method()
    rows, _, _ = build_figure_rows([_figure()], meta, meth, "001", 14, 43)
    prov = rows[0].provenance
    assert prov["duration_hr"].origin == "Fig. 5 (digitized)" and prov["duration_hr"].confidence == "digitized"
    assert "point 1" in prov["duration_hr"].source
    assert prov["initial_NaCl_aq_mM"].origin == "Fig. 5 series conditions"
    assert prov["initial_pH"].origin == "Fig. 5 series conditions"

    if not PDF.is_file():
        return
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", _replay_send):
        ex = extract(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp),
                                                  registry_path=Path(tmp) / "r.json"))
        _add_extras(ex)
        result = finish(ex, review=lambda groups, *_: [
            VariableDecision("stirring rate", "parameter", "new_column", "stirring_rate_rpm")])
        obs = [o for o in csv.DictReader(open(result.observations_path)) if o["column"] == "stirring_rate_rpm"]
        assert len(obs) == len(result.rows) and obs[0]["unit"] == "rpm"
        assert obs[0]["origin"] == "methodology (new variable 'stirring rate')"
        assert obs[0]["quote"] == "stirred at 300 rpm"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All observation tests passed.")
