"""
Constructed-parameter groups (scopes.py, 2026-11-08): compounds and instrument families in the Parameters panel narrow
the chemistry / analysis steps; all unticked switches the step off. No API calls.
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import csv
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pack_facts as pf  # noqa: E402
from parameter_extractor import api_client, packs, scopes
from parameter_extractor.schemas.analysis import AnalysisMethod, AnalysisResult


def _pack():
    return pf.linked("prebiotic_chemistry", "solution_chemistry", "analysis")      # tests of those two modules


def test_groups_list_compounds_and_families():
    pack = _pack()
    gs = {g.step: g for g in scopes.groups(pack)}
    assert set(gs) == {"chemistry", "analysis"}
    keys = [i.key for i in gs["chemistry"].items]
    assert "Gly" in keys and "NaCl" in keys and len(keys) == len(set(keys))
    families = [i.key for i in gs["analysis"].items]
    assert "nmr" in families and "general" not in families
    exo = packs.available()["exoplanets"]                            # only the steps it links
    assert {g.step for g in scopes.groups(exo)} == {s for s in ("chemistry", "analysis") if exo.uses(s)}


def test_prompt_rules_and_filters():
    from parameter_extractor.analysis_vocab import vocabulary, prompt_listing
    assert scopes.compound_rule(None) == "" and "ONLY these compounds" in scopes.compound_rule(["Gly", "NaCl"])
    vocab = vocabulary(_pack())
    full, nmr = prompt_listing(vocab), prompt_listing(vocab, ["nmr"])
    assert len(nmr) < len(full) and "NMR" in nmr
    assert "NMR" in scopes.analysis_rule(["nmr"], vocab)
    chem = SimpleNamespace(solutes=[SimpleNamespace(name="Gly"), SimpleNamespace(name="NaCl"),
                                    SimpleNamespace(name="Gly-Gly")])
    assert scopes.filter_compounds(chem, ["gly"]) == ["Gly-Gly", "NaCl"] and [s.name for s in chem.solutes] == ["Gly"]
    nmr_tech = next(t for t in vocab.techniques if "nmr" in t.families)
    other = next(t for t in vocab.techniques if "nmr" not in t.families)
    result = AnalysisResult(methods=[AnalysisMethod(technique=nmr_tech.name, name="x", set_label="", settings=[]),
                                     AnalysisMethod(technique=other.name, name="y", set_label="", settings=[]),
                                     AnalysisMethod(technique="Made-up", name="z", set_label="", settings=[])])
    dropped = scopes.filter_analysis(result, ["nmr"], vocab)
    assert [m.technique for m in result.methods] == [nmr_tech.name] and dropped == [other.name, "Made-up"]


def test_chemistry_prompt_narrowed():
    from parameter_extractor.stages import chemistry_extractor
    packs.activate(_pack().id)
    vocab = {"species_names": ["Gly", "NaCl", "KCl"]}
    narrowed = chemistry_extractor.prompt_text("PAPER", "{}", vocab, scope=["Gly"])
    assert "SCOPE OF THIS RUN" in narrowed and '"KCl"' not in narrowed
    assert "SCOPE OF THIS RUN" not in chemistry_extractor.prompt_text("PAPER", "{}", vocab)


def test_replayed_run_keeps_only_chosen_compounds():
    from test_pipeline_offline import PDF, _config, _replay_send
    from parameter_extractor.pipeline import run_pipeline
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}")
        return
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", _replay_send):
        full = run_pipeline(PDF, _config(Path(tmp)))
        narrowed = run_pipeline(PDF, _config(Path(tmp), scopes={"chemistry": ["Gly"]}))

        def species_columns(result):
            rows = list(csv.DictReader(result.csv_path.open()))
            return {c for r in rows for c, v in r.items() if v and c.startswith(("initial_", "sampled_", "stock_"))
                    and c.endswith(("_mM", "_%yield")) and "temperature" not in c and "pressure" not in c}
        before, after = species_columns(full), species_columns(narrowed)
        assert "initial_Gly_aq_mM" in after and len(after) < len(before)
        assert all("_Gly_" in c for c in after), after
        assert any(f.kind == "scope" for f in narrowed.paper_flags)
        assert not any(f.kind == "scope" for f in full.paper_flags)

        calls = []

        def counting(ctx, **kw):
            calls.append(kw["response_model"].__name__)
            return _replay_send(ctx, **kw)
        with patch.object(api_client, "_send", counting):              # every compound unticked: no chemistry call
            run_pipeline(PDF, _config(Path(tmp), optional_stages={"chemistry": "off"}))
        assert "ChemistryExtraction" not in calls and "StructurePlan" in calls


def test_panel_scope_groups():
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    QApplication.setOrganizationName("ParameterExtractorTests")
    QSettings().clear()
    from parameter_extractor.gui.parameter_panel import ParameterPanel, STAGE_ROLE
    panel = ParameterPanel()
    panel.load(_pack().id)
    assert list(panel.groups)[0] == "chemistry" and "analysis" in panel.scope_groups
    assert panel.scopes() == {} and panel.scope_summary() == ""
    fam = panel.groups["analysis"]
    for j in range(fam.childCount()):
        if fam.child(j).data(0, STAGE_ROLE) != "nmr":
            fam.child(j).setCheckState(0, Qt.CheckState.Unchecked)
    assert panel.scopes() == {"analysis": ["nmr"]} and not panel.focused       # narrowed, still a full extraction
    assert "NMR" in panel.scope_summary()
    assert all("nmr" not in c for c in panel.checked_columns())
    panel.set_stage("chemistry", False)
    assert panel.optional_stage_choices()["chemistry"] == "off" and "chemistry" not in panel.scopes()
    panel.tick_all()
    assert panel.scopes() == {} and panel.optional_stage_choices()["analysis"] == "auto"
    QSettings().clear()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
