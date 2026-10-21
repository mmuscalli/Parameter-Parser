"""
Offline tests for the exoplanet pack's "one row per solution" rows and its
fitting-model columns (how the values were obtained: data, instruments, joint
fits, software, priors, assumptions -- NEA-style names). The model responses
are teng2023's recorded ones (runs/teng2023_auto/), reshaped the way the new
prompts ask for them: HD 14067 b as two solutions (RV fit, Table 3; joint RV +
astrometry fit, Table 4), plus a hand-written FitModels answer. The PDF only
has to be readable (eder1994, small); no API calls, no network.

Run with: python tests/test_exoplanet_fits.py
"""
import csv
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client, packs
from parameter_extractor.calculators import exoplanet_fits as fits
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pipeline import run_pipeline
from parameter_extractor.schemas.fit_models import FitModels, FitSoftware
from parameter_extractor.validation import exoplanet_archive
from test_pipeline_offline import PDF

REF = ROOT / "runs" / "teng2023_auto"
RV, JOINT = "HD 14067 b [RV fit, Table 3]", "HD 14067 b [joint RV + astrometry fit, Table 4]"
SYSTEMS = ("11 Com", "HD 14067")


def _structure() -> dict:
    s = json.loads((REF / "structure_planner.output.json").read_text())
    s["experiment_sets"] = [e for e in s["experiment_sets"] if e["set_label"] in SYSTEMS]
    for e in s["experiment_sets"]:
        if e["set_label"] == "HD 14067":
            e["samples"] = [dict(e["samples"][0], sample_label=RV, source="Table 3"),
                            dict(e["samples"][0], sample_label=JOINT, source="Table 4")]
    s["total_planned_rows"] = 3
    return s


def _items(name: str) -> dict:
    d = json.loads((REF / f"{name}.output.json").read_text())
    keep = []
    for it in d["parameters"]:
        if it["set_label"] not in SYSTEMS:
            continue
        if it.get("sample_label") == "HD 14067 b":            # each table's values to its own solution
            it["sample_label"] = JOINT if it["source"] == "Table 4" else RV
        keep.append(it)
    d["parameters"] = keep
    return d


def _stellar() -> dict:
    d = _items("stellar_parameters")
    d["parameters"].append({"set_label": "HD 14067", "sample_label": JOINT, "parameter": "st_mass", "value": 2.4,
                            "unit": "", "err_plus": 0.23, "err_minus": -0.22, "limit": "", "text": "",
                            "basis": "stated", "quote": "M pri ( M ) 2 . 40", "source": "Table 4",
                            "confidence": "high", "note": ""})
    return d


FIT_MODELS = {
    "models": [
        {"label": "Keplerian RV fit (Table 3)", "rows": ["11 Com b", RV], "stars": [],
         "datasets": [{"kind": "radial velocity", "facility": "OAO 1.88 m", "instrument": "HIDES",
                       "bands": "I2 cell", "note": ""},
                      {"kind": "radial velocity", "facility": "Xinglong 2.16 m", "instrument": "HRS",
                       "bands": "", "note": ""}],
         "joint": True, "joint_description": "RVs from both instruments with offsets", "star_and_planets_joint": False,
         "software": [{"name": "MCMC code of Sato et al.", "version": "", "role": "fitting code"}],
         "priors": [{"parameter": "pl_orbeccen", "target": "", "shape": "uniform", "center": "", "width": "",
                     "lower": "0", "upper": "1", "unit": "", "as_printed": "U(0, 1)", "source": "Section 4"},
                    {"parameter": "RV jitter (HIDES)", "target": "", "shape": "log-uniform", "center": "",
                     "width": "", "lower": "0.1", "upper": "100", "unit": "m/s", "as_printed": "logU(0.1, 100) m/s",
                     "source": "Section 4"}],
         "assumptions": [{"text": "single Keplerian per planet", "parameter": "", "quote": "single Keplerian",
                          "source": "Section 4"}],
         "quote": "We fitted the RVs with a single Keplerian model", "source": "Section 4", "confidence": "high"},
        {"label": "joint RV + Hipparcos-Gaia astrometry fit (Table 4)", "rows": [JOINT], "stars": ["HD 14067"],
         "datasets": [{"kind": "radial velocity", "facility": "OAO 1.88 m", "instrument": "HIDES", "bands": "",
                       "note": ""},
                      {"kind": "astrometry", "facility": "Hipparcos", "instrument": "", "bands": "", "note": ""},
                      {"kind": "astrometry", "facility": "Gaia EDR3", "instrument": "", "bands": "", "note": ""}],
         "joint": True, "joint_description": "RV and absolute astrometry fit simultaneously",
         "star_and_planets_joint": False,
         "software": [{"name": "orvara", "version": "", "role": "fitting code"}],
         "priors": [{"parameter": "st_mass", "target": "HD 14067", "shape": "gaussian", "center": "2.4",
                     "width": "0.2", "lower": "", "upper": "", "unit": "M_sun", "as_printed": "N(2.4, 0.2) Msun",
                     "source": "Section 6"},
                    {"parameter": "pl_orbtper", "target": JOINT, "shape": "uniform", "center": "", "width": "",
                     "lower": "5000", "upper": "8000", "unit": "JD-2450000", "as_printed": "U(5000, 8000)",
                     "source": "Section 6"}],
         "assumptions": [{"text": "host mass prior from the spectroscopic analysis", "parameter": "st_mass",
                          "quote": "Gaussian prior on the host mass", "source": "Section 6"}],
         "quote": "jointly fit the RV and astrometric data", "source": "Section 6", "confidence": "medium"},
        {"label": "spectroscopic + isochrone stellar parameters", "rows": [], "stars": list(SYSTEMS),
         "datasets": [{"kind": "spectroscopy", "facility": "OAO 1.88 m", "instrument": "HIDES", "bands": "",
                       "note": ""},
                      {"kind": "SED photometry", "facility": "", "instrument": "", "bands": "Hipparcos V, B-V",
                       "note": ""}],
         "joint": False, "joint_description": "", "star_and_planets_joint": False,
         "software": [{"name": "PARSEC", "version": "v1.2S", "role": "stellar evolution models"},
                      {"name": "ATLAS9", "version": "", "role": "stellar atmosphere models"}],
         "priors": [], "assumptions": [{"text": "LTE", "parameter": "", "quote": "assuming LTE", "source": "Sec. 3"}],
         "quote": "stellar parameters were derived from the iodine-free spectra", "source": "Section 3",
         "confidence": "high"},
        {"label": "made-up model naming a row that isn't there", "rows": ["HD 99999 b"], "stars": [],
         "datasets": [], "joint": False, "joint_description": "", "star_and_planets_joint": False,
         "software": [{"name": "EXOFAST", "version": "", "role": "fitting code"}], "priors": [],
         "assumptions": [], "quote": "", "source": "", "confidence": "high"}],
    "notes": ""}


def _send(ctx, *, model, system_prompt, content, response_model, **kw):
    name = response_model.__name__
    data = {"StructurePlan": _structure(),
            "PaperMetadata": json.loads((REF / "metadata.output.json").read_text()),
            "PlanetParametersResult": _items("planet_parameters"),
            "StellarParametersResult": _stellar(),
            "SystemAndDiscoveryResult": _items("system_and_discovery"),
            "FitModels": FIT_MODELS}[name]
    out = response_model.model_validate(data)
    return SimpleNamespace(id="fake", stop_reason="end_turn", parsed_output=out,
                           content=[SimpleNamespace(type="text", text=out.model_dump_json())],
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def _run(tmp, **kw):
    saved = json.loads((REF / "archive_rows.json").read_text())
    with patch.object(api_client, "_send", _send), \
            patch.object(exoplanet_archive, "fetch_parameter_sets", lambda names, ref: saved):
        return run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp), pack="exoplanets",
                                                         online_checks=True, **kw))


def test_one_row_per_solution_with_fit_columns():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp)
            with open(result.csv_path) as f:
                reader = csv.DictReader(f)
                header, rows = reader.fieldnames, list(reader)
            assert [r["pl_name"] for r in rows] == ["HD 14067 b", "HD 14067 b", "11 Com b"]
            rv, joint, com = rows
            # each solution has its own values -- never mixed
            assert rv["pl_orbper"] == "2725.81" and joint["pl_orbper"] == "2744.12325"   # 7.513 yr
            assert rv["pl_orbeccen"] == "0.701" and joint["pl_orbeccen"] == "0.65"
            assert joint["pl_massj"] == "15.3" and rv["pl_massj"] == "" and rv["pl_msinij"] == "8.806"
            assert joint["pl_bmassprov"] == "Mass" and rv["pl_bmassprov"] == "Msini"
            assert rv["st_mass"] == "2.4" and joint["st_mass"] == "2.4" and joint["st_masserr1"] == "0.23"
            assert rv["st_masserr1"] != "0.23"                         # the joint fit's own stellar value
            flags = json.loads(result.flags_path.read_text())["paper_level"]
            assert not [f for f in flags if f["kind"] == "conflicting_values"]
            # how the values were obtained
            assert rv["pl_fitlabel"] == com["pl_fitlabel"] == "Keplerian RV fit (Table 3)"
            assert joint["pl_fitlabel"] == "joint RV + Hipparcos-Gaia astrometry fit (Table 4)"
            assert (rv["pl_fitrv_flag"], rv["pl_fitast_flag"], joint["pl_fitast_flag"]) == ("1", "0", "1")
            assert rv["pl_fitrvinst"] == "OAO 1.88 m / HIDES (I2 cell); Xinglong 2.16 m / HRS"
            assert joint["pl_fitastinst"] == "Hipparcos; Gaia EDR3"
            assert joint["pl_fitjoint_flag"] == "1" and joint["pl_fitstjoint_flag"] == "0"
            assert joint["pl_fitsoftware"] == "orvara" and "pl_fitexofastver" not in header   # written only when filled
            assert rv["pl_fitassump"] == "single Keplerian per planet"
            assert (rv["pl_orbeccenpriortype"], rv["pl_orbeccenpriorlo"], rv["pl_orbeccenpriorhi"]) == ("uniform", "0.0", "1.0")
            assert "RV jitter (HIDES): logU(0.1, 100) m/s" in rv["pl_fitpriors"]
            assert joint["pl_orbtperpriorlo"] == "2455000.0" and joint["pl_orbtperpriorhi"] == "2458000.0"
            assert rv["pl_orbtperpriorlo"] == ""                       # targeted at the joint solution only
            # the star: the stellar model on every row, the joint fit's stellar side only on its own row
            assert rv["st_fitlabel"] == com["st_fitlabel"] == "spectroscopic + isochrone stellar parameters"
            assert joint["st_fitlabel"] == ("joint RV + Hipparcos-Gaia astrometry fit (Table 4); "
                                            "spectroscopic + isochrone stellar parameters")
            assert rv["st_fitmodels"] == "PARSEC v1.2S; ATLAS9" and rv["st_fitbands"] == "Hipparcos V, B-V"
            assert (joint["st_masspriortype"], joint["st_masspriorcen"], joint["st_masspriorwid"]) == ("gaussian", "2.4", "0.2")
            assert rv["st_masspriortype"] == ""
            # columns: template block, then the pack's standard columns in their order
            assert header.index("pl_fitlabel") > header.index("paper_title") > header.index("pl_name")
            assert header.index("pl_fitlabel") < header.index("st_fitlabel") < header.index("pl_orbeccenpriortype")
            # flags: unknown row, EXOFAST without a version, a medium-confidence model
            fit_msgs = [f["message"] for f in flags if f["kind"] == "fit_model"]
            assert any("'HD 99999 b'" in m for m in fit_msgs) and any("EXOFAST" in m for m in fit_msgs)
            assert any("joint RV + Hipparcos-Gaia" in f["message"] for f in flags if f["kind"] == "low_confidence")
            assert not any("produced no row" in m for m in fit_msgs)        # every model here is linked
            # the archive check compares each solution with the archive's Teng et al. 2023 set
            report = json.loads((result.run_dir / "archive_validation.json").read_text())
            by_solution = {e.get("solution"): e for e in report if e["pl_name"] == "HD 14067 b"}
            assert set(by_solution) == {"Keplerian RV fit (Table 3)",            # the fitting model's names
                                        "joint RV + Hipparcos-Gaia astrometry fit (Table 4)"}
            joint_e = by_solution["joint RV + Hipparcos-Gaia astrometry fit (Table 4)"]
            rv_e = by_solution["Keplerian RV fit (Table 3)"]
            assert "pl_orbper" in joint_e["matches"] and "pl_orbper" in [d["column"] for d in rv_e["differs"]]
            assert any("HD 14067 b [joint RV + Hipparcos-Gaia" in f["message"] for f in flags
                       if f["kind"] in ("archive_match", "archive_check"))
            # the summary lists the stage
            assert "fit_models" in [u.stage for u in result.usage]
    finally:
        packs.activate("prebiotic_chemistry")


def test_stage_switched_off():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(tmp, optional_stages={"fit_models": "off"})
            assert "fit_models" not in [u.stage for u in result.usage]
            with open(result.csv_path) as f:
                header = csv.DictReader(f).fieldnames
            assert "pl_fitrv_flag" not in header and "pl_fitlabel" in header   # the [solution] label still
    finally:
        packs.activate("prebiotic_chemistry")


def test_exofast_versions_and_labels():
    sw = lambda name, version="": FitSoftware(name=name, version=version, role="fitting code")
    assert fits.exofast_version([sw("EXOFASTv2")]) == (2, True)
    assert fits.exofast_version([sw("EXOFAST", "v1")]) == (1, True)
    assert fits.exofast_version([sw("EXOFAST", "2")]) == (2, True)
    assert fits.exofast_version([sw("EXOFAST")]) == (None, True)
    assert fits.exofast_version([sw("juliet", "2.1")]) == (None, False)
    assert fits.split_solution("HD 14067 b [joint fit, Table 4]") == ("HD 14067 b", "joint fit, Table 4")
    assert fits.split_solution("11 Com b") == ("11 Com b", "")
    packs.activate("exoplanets")
    try:
        cols = [c for c, _ in fits.fit_columns()]
        assert len(cols) == len(set(cols)) and "pl_orbeccenpriorwid" in cols and "st_tefpriorcen" not in cols
        assert all("_" not in c[3:].replace("_flag", "") for c in cols if c.startswith(("pl_fit", "st_fit")))
        assert FitModels.model_validate(FIT_MODELS).models[1].priors[0].shape == "gaussian"
    finally:
        packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All exoplanet fitting-model tests passed.")
