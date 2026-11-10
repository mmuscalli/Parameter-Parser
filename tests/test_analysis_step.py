"""
The analysis step (Mickey, 2026-11-07): analytical techniques and their instrument settings ->
analysis_<technique>_<setting>[_<unit>] columns, from the prebiotic pack's vocabulary (analysis_vocab.json).
Uses Riggi2023's Table 2 (MALDI-TOF MS settings) and kim2017's HPLC as answers; no API calls.

Run with: python tests/test_analysis_step.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pack_facts as pf  # noqa: E402
from parameter_extractor import analysis_vocab as av, packs
from parameter_extractor.calculators.analysis_columns import apply_analysis, convert
from parameter_extractor.ingestion.observations import unit_for_column
from parameter_extractor.registry import VariableRegistry
from parameter_extractor.schemas.analysis import AnalysisResult
from parameter_extractor.schemas.row_schema import ExtractedRow

packs.activate(pf.linked("prebiotic_chemistry", "analysis", "solution_chemistry").id)   # tests of the analysis module


def _rows(n=3, set_id="001001"):
    return [ExtractedRow(full_id=f"{set_id}{i:03d}", set_id=set_id, sample_id=f"{i:03d}", entry_number=i,
                         set_type="Independent", paper_title="t", authors=[], year_published=2023,
                         journal_published="j", experiment_type="", solution_type="")
            for i in range(1, n + 1)]


def _setting(par, v=0.0, u="", txt="", hi=0.0, q="", c="high"):
    return {"par": par, "v": v, "u": u, "txt": txt, "hi": hi, "q": q or f"{par} {txt or v}", "src": "Table 2",
            "c": c}


RIGGI = AnalysisResult.model_validate({"methods": [{
    "tech": "MALDI-TOF-MS", "nm": "MALDI-TOF MS", "set": "", "q": "Instrument settings are shown in Table 2",
    "src": "Section 2.4", "c": "high", "settings": [
        _setting("instrument", txt="Bruker Autoflex Speed"),
        _setting("measured", txt="maximum oligomer length"),
        _setting("detection-mode", txt="Reflectron"),
        _setting("ion-polarity", txt="Negative"),
        _setting("ion-source-1-voltage", 19, "kV"),
        _setting("ion-source-2-voltage", 16.7, "kV"),
        _setting("lens-voltage", 8.4, "kV"),
        _setting("pulsed-ion-extraction", 140, "ns"),
        _setting("relative laser intensity", 75, "%", hi=85),     # an alias, and a range
        _setting("laser-shots", 1000),
        _setting("matrix", txt="THAP/AHC"),
        _setting("target-plate", txt="AnchorChip var/387, stainless steel"),
        _setting("calibration", txt="Oligonucleotide Calibration Standard LMW, ~1000-4000 Da"),
        _setting("data-processing", txt="baseline subtraction; Savitzky-Golay smoothing"),
        _setting("crystallization", txt="40 °C incubator, ~10 min"),               # not in the vocabulary
    ]}]})


def test_column_format_round_trips():
    col = av.column("MALDI-TOF-MS", "laser-intensity", "%")
    assert col == "analysis_MALDI-TOF-MS_laser-intensity_%"
    assert av.parse_column(col) == ("MALDI-TOF-MS", "laser-intensity", "%", False)
    assert av.column("RP-HPLC", "flow-rate", "mL/min") == "analysis_RP-HPLC_flow-rate_mL_min"
    assert av.parse_column("analysis_RP-HPLC_flow-rate_mL_min")[2] == "mL/min"
    assert av.column("RP-HPLC", "column") == "analysis_RP-HPLC_column"
    rng = av.column("MALDI-TOF-MS", "laser-intensity", "%", is_range=True)
    assert rng == "analysis_MALDI-TOF-MS_laser-intensity_range_%" and av.parse_column(rng)[3]
    assert av.token("ion source 1 voltage") == "ion-source-1-voltage" and av.token("MALDI-TOF MS") == "MALDI-TOF-MS"
    assert unit_for_column("analysis_RP-HPLC_particle-size_um") == "µm"
    assert unit_for_column("analysis_RP-HPLC_column") == ""
    assert unit_for_column("analysis_MALDI-TOF-MS_pulsed-ion-extraction_ns") == "ns"


def test_vocabulary_matching():
    vocab = av.vocabulary()
    assert vocab.technique("MALDI-TOF MS").name == "MALDI-TOF-MS"
    assert vocab.technique("reversed-phase HPLC").name == "RP-HPLC"
    assert vocab.technique("31P NMR").name == "NMR-31P"
    assert vocab.technique("anion-exchange HPLC").name == "AEX-HPLC"
    assert vocab.technique("DOSY-ish thing") is None
    lc = vocab.technique("RP-HPLC")
    assert vocab.setting(lc, "flow rate").name == "flow-rate"
    assert vocab.setting(lc, "i.d.").name == "column-diameter"
    assert vocab.setting(lc, "LOD").name == "detection-limit"              # general settings belong to every one
    assert vocab.setting(lc, "laser-intensity") is None                    # a MALDI setting, not an LC one
    # every name is a valid column slot: hyphens, no underscores or spaces
    for t in vocab.techniques:
        assert av.token(t.name) == t.name, t.name
    for _, settings in vocab.families.values():
        for s in settings:
            assert av.token(s.name) == s.name and s.unit in av.UNIT_TOKENS or not s.unit, s.name


def test_known_columns():
    reg = VariableRegistry(None)
    assert reg.is_known_column("analysis_RP-HPLC_flow-rate_mL_min")
    assert reg.is_known_column("analysis_MALDI-TOF-MS_laser-intensity_range_%")
    assert not reg.is_known_column("analysis_RP-HPLC_flow-rate_mL")            # wrong unit
    assert not reg.is_known_column("analysis_MALDI-TOF-MS_crystallization")     # not in the vocabulary
    assert not reg.is_known_column("analysis_DOSY-NMR_frequency_MHz")           # unknown technique


def test_unit_conversion():
    assert convert(0.5, "mL min-1", "mL/min") == (0.5, "")
    assert convert(500, "µL/min", "mL/min")[0] == 0.5
    assert convert(30, "m", "m") == (30, "")                      # GC column length: metres, not molar
    assert convert(4.6, "mm", "mm") == (4.6, "")
    assert convert(100, "Å", "nm")[0] == 10
    assert convert(19000, "V", "kV")[0] == 19
    assert convert(298.15, "K", "°C")[0] == 25
    assert convert(1, "kg", "nm")[0] is None
    assert convert(140, "", "ns") == (140, "no unit printed; taken as ns")


def test_riggi_maldi_settings():
    rows = _rows()
    reg = VariableRegistry(None)
    new_vars, flags = apply_analysis(rows, RIGGI, reg, lambda s, smp: [])
    r = rows[0]
    assert r.extra["analysis_MALDI-TOF-MS_instrument"] == "Bruker Autoflex Speed"
    assert r.extra["analysis_MALDI-TOF-MS_detection-mode"] == "Reflectron"
    assert r.extra["analysis_MALDI-TOF-MS_ion-polarity"] == "Negative"
    assert r.extra["analysis_MALDI-TOF-MS_ion-source-1-voltage_kV"] == 19
    assert r.extra["analysis_MALDI-TOF-MS_ion-source-2-voltage_kV"] == 16.7
    assert r.extra["analysis_MALDI-TOF-MS_lens-voltage_kV"] == 8.4
    assert r.extra["analysis_MALDI-TOF-MS_pulsed-ion-extraction_ns"] == 140
    assert r.extra["analysis_MALDI-TOF-MS_laser-intensity_range_%"] == "75:85"
    assert r.extra["analysis_MALDI-TOF-MS_laser-shots"] == 1000
    assert r.extra["analysis_MALDI-TOF-MS_matrix"] == "THAP/AHC"
    assert all(rr.extra == r.extra for rr in rows)                   # used for every experiment: every row
    assert r.provenance["analysis_MALDI-TOF-MS_matrix"].origin == "analysis"
    # the one setting the vocabulary lacks goes to the review, column already in the format
    assert [(v.name, v.proposed_column, v.category) for v in new_vars] == [
        ("MALDI-TOF-MS crystallization", "analysis_MALDI-TOF-MS_crystallization", "analysis")]
    assert len(new_vars[0].row_ids) == 3
    assert flags[0][1].startswith("MALDI-TOF-MS: 15 settings recorded") and "crystallization (review)" in flags[0][1]


def test_sets_unknown_techniques_and_several_values():
    rows = _rows(2, "001001") + _rows(2, "001002")
    by_set = {"A": ["001001001", "001001002"], "B": ["001002001", "001002002"]}
    result = AnalysisResult.model_validate({"methods": [
        {"tech": "reversed-phase HPLC", "nm": "RP-HPLC", "set": "A", "q": "", "src": "Methods", "c": "high",
         "settings": [_setting("column", txt="SunFire C18, Waters"), _setting("column-diameter", 3, "mm"),
                      _setting("column-length", 15, "cm"), _setting("particle-size", 5, "µm"),
                      _setting("flow-rate", 500, "µL/min"), _setting("detection-wavelength", 260, "nm"),
                      _setting("detection-wavelength", 280, "nm")]},
        {"tech": "anion-exchange HPLC", "nm": "anion-exchange HPLC", "set": "B", "q": "", "src": "Methods",
         "c": "high", "settings": [_setting("eluent", txt="0-0.4 M NaClO4, pH 8")]},
        {"tech": "QCM", "nm": "quartz crystal microbalance", "set": "", "q": "", "src": "SI", "c": "medium",
         "settings": [_setting("frequency", 5, "MHz")]},
    ]})
    new_vars, flags = apply_analysis(rows, result, VariableRegistry(None),
                                     lambda s, smp: by_set.get(s, []))
    a, b = rows[0], rows[2]
    assert a.extra["analysis_RP-HPLC_column-length_mm"] == 150                   # 15 cm -> mm
    assert a.extra["analysis_RP-HPLC_flow-rate_mL_min"] == 0.5
    assert a.extra["analysis_RP-HPLC_detection-wavelength_nm"] == "260; 280"    # both kept
    assert "analysis_RP-HPLC_column" not in b.extra                             # set B used another column
    assert b.extra["analysis_AEX-HPLC_mobile-phase"] == "0-0.4 M NaClO4, pH 8"  # 'eluent' -> mobile-phase
    assert any("several values" in m for _, m in flags)
    assert [v.proposed_column for v in new_vars] == ["analysis_QCM_frequency_MHz"]
    assert len(new_vars[0].row_ids) == 4 and new_vars[0].value == 5
    assert any("isn't in the analysis vocabulary" in m for _, m in flags)


def test_conditions_hint_depends_on_the_analysis_step():
    from parameter_extractor.stages.optional import for_run, load_specs
    spec = load_specs()["experimental_conditions"]
    on = for_run(spec, True, {"analysis", "chemistry"}).open_ended_hint
    off = for_run(spec, True, {"chemistry"}).open_ended_hint
    assert "a separate step records them" in on and "analysis details beyond" not in on
    assert "analysis details beyond analysis_method DO belong here" in off


def test_stage_toggle_and_pack_check():
    from parameter_extractor.pack_editing import PackDraft, check
    from parameter_extractor.stages.optional import toggleable_stages
    pack = pf.linked("prebiotic_chemistry", "analysis", "solution_chemistry")
    assert "analysis" in [t.name for t in toggleable_stages(pack)]
    exo = packs.available()["exoplanets"]
    assert ("analysis" in [t.name for t in toggleable_stages(exo)]) == exo.uses("analysis")   # follows the link
    problems = [p for p in check(PackDraft.load(pack.folder)) if "analysis_vocab" in p.where]
    assert not problems, problems


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS:", name)
    print("All analysis-step tests passed.")
