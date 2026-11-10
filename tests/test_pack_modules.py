"""
Shared modules for data packs (modules/, pack_modules.py, 2026-11-09): linked by reference, not copied -- technique
detection in paper surveys, the analysis / solution-chemistry / kinetics / wet-dry / totals modules merged at load,
the prebiotic pack built from them, migrating packs made with copies, drafting linking modules, the editor's Modules
tab, and the app's own packs refused. No API, no network.
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("PARAMETER_EXTRACTOR_NO_KEYCHAIN", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pack_facts as pf  # noqa: E402
from parameter_extractor import pack_modules, packs
from parameter_extractor.pack_drafting import PaperSurvey, SurveyVariable


def _survey(method_text: str) -> PaperSurvey:
    return PaperSurvey(field="x", row_unit="r", set_unit="s", notes="", compounds=[], variables=[
        SurveyVariable(name="analysis method", column="analysis_method", unit="", kind="text", role="method",
                       description="how products were measured", level="paper", uncertainty=False, where="text",
                       example=method_text),
        SurveyVariable(name="temperature", column="temperature", unit="°C", kind="number", role="condition",
                       description="heating temperature, measured by thermocouple", level="set", uncertainty=False,
                       where="table", example="80 °C")])


def test_techniques_named():
    named = pack_modules.techniques_named(["GC-MS and direct MS", "UHPLC/MSMS (Shimadzu LCMS-8040)",
                                           "Raman spectroscopy; SEM/EDX", "1H NMR", "reversed-phase HPLC"])
    for t in ("GC-MS", "UHPLC", "Raman", "NMR-1H", "RP-HPLC"):
        assert t in named, (t, named)
    assert "HPLC" not in named and "NMR" not in named         # the specific ones only
    assert pack_modules.techniques_named(["N-body simulation of impact rates", "a model of carbon delivery"]) == []
    papers = [SimpleNamespace(name="a", survey=_survey("HPLC with UV detection")),
              SimpleNamespace(name="b", survey=_survey("not stated")), SimpleNamespace(name="c", survey=None)]
    assert pack_modules.analysis_evidence(papers) == {"a": ["HPLC"]}


def _new_pack(tmp: Path):
    return packs.create_pack("modules_test", "Modules test", "", base=tmp / "packs")


def test_analysis_module():
    """Linked, not copied: the pack lists the module; the step, its vocabulary, hints and category come from it."""
    from parameter_extractor.pack_editing import PackDraft, check
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        draft = PackDraft.load(pack.folder)
        draft.stages[next(iter(draft.stages))]["open_ended"] = True
        draft.save()
        lines = pack_modules.add_modules(pack.folder, ["analysis"])["analysis"]
        assert lines and all(l.startswith("linked") for l in lines), lines
        own = json.loads((pack.folder / "pack.json").read_text())
        assert own["modules"] == ["analysis"] and "analysis" not in own.get("builtin_stages", [])
        assert not (pack.folder / "analysis_vocab.json").exists()                  # nothing copied
        merged = packs.Pack(pack.folder)
        assert "analysis" in merged.manifest.builtin_stages
        assert any(c["id"] == "analysis" for c in merged.manifest.variable_categories)
        assert merged.file("analysis_vocab.json") == pack_modules._source_vocab_path()
        from parameter_extractor.stages.optional import load_specs
        assert all("analysis" in s.hint_by_stage for s in load_specs(merged).values() if s.open_ended)
        d = PackDraft.load(pack.folder)
        assert "analysis" in d.effective_steps()
        assert not [p for p in check(d) if p.level == "error"], check(d)
        assert pack_modules.add_modules(pack.folder, ["analysis"]) == {"analysis": []}    # already linked
        packs.activate("modules_test")
        from parameter_extractor.stages import analysis
        assert "RP-HPLC" in analysis.prompt_text("P", "PLAN")
        packs.activate("prebiotic_chemistry")
        assert pack_modules.remove_module(pack.folder, "analysis")
        assert "analysis" not in packs.Pack(pack.folder).manifest.builtin_stages


def test_solution_chemistry_module():
    from parameter_extractor.pack_editing import PackDraft, check
    from parameter_extractor.stages.optional import load_specs
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        pack_modules.add_module(pack.folder, "solution_chemistry")
        merged = packs.Pack(pack.folder)
        assert "chemistry" in merged.manifest.builtin_stages
        assert all(c in merged.manifest.postprocess for c in ("amounts", "mixing", "water_type"))
        cols = [p.column for s in load_specs(merged).values() for p in s.parameters]
        assert "solvent_volume_mL" in cols and "solvent_name" in cols         # the module's parameters, merged in
        assert not (pack.folder / "prompts" / "chemistry.md").exists()
        assert merged.prompt_path("chemistry").parent.parent.name == "solution_chemistry"
        d = PackDraft.load(pack.folder)
        assert not [p for p in check(d) if p.level == "error"], check(d)
        assert pack_modules.add_module(pack.folder, "solution_chemistry") == ["Solution chemistry: already in the pack"]
        try:
            pack_modules.add_module(packs.BUILTIN_DIR / "exoplanets", "analysis")
            raise AssertionError("an app pack was changed")
        except ValueError:
            pass


def test_prebiotic_uses_the_modules():
    pack = packs.get("prebiotic_chemistry") if hasattr(packs, "get") else packs.Pack(packs.BUILTIN_DIR / "prebiotic_chemistry")
    # its steps and calculations come from the modules it links (whichever those are): none written in the pack
    assert pack.own_manifest.builtin_stages == []
    mods = pack.module_ids()
    assert mods and set(mods) == set(pf.module_ids("prebiotic_chemistry"))
    assert ("chemistry" in pack.manifest.builtin_stages) == ("solution_chemistry" in mods)
    from parameter_extractor.stages.optional import load_specs
    specs = set(load_specs(pack))
    assert "experimental_conditions" in specs                            # the pack's own step
    from parameter_extractor import module_settings as ms
    for mod in pack.modules:                     # every linked module's steps, unless the pack switches one off
        st = ms.settings_for(pack.own_manifest.module_settings, mod.id).steps
        assert {f.stem for f in mod.stage_files() if not (f.stem in st and st[f.stem].off)} <= specs, mod.id


def test_migrate_copies():
    """A pack made when modules were copied: identical copies become links, the pack's own changes stay."""
    from parameter_extractor.pack_editing import PackDraft
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        m = json.loads((pack.folder / "pack.json").read_text())
        m["builtin_stages"] = ["analysis", "chemistry"]
        m["postprocess"] = ["normalize_species", "mixing", "molar_ratios", "amounts", "water_type", "my_own"]
        (pack.folder / "pack.json").write_text(json.dumps(m))
        (pack.folder / "analysis_vocab.json").write_bytes(pack_modules._source_vocab_path().read_bytes())
        (pack.folder / "prompts").mkdir(exist_ok=True)
        (pack.folder / "prompts" / "chemistry.md").write_text("my own changed prompt")
        lines = pack_modules.migrate_copies(pack.folder)
        own = json.loads((pack.folder / "pack.json").read_text())
        assert set(own["modules"]) >= {"analysis", "solution_chemistry"}, lines
        assert own["builtin_stages"] == [] and own["postprocess"] == ["my_own"]
        assert not (pack.folder / "analysis_vocab.json").exists()
        assert (pack.folder / "prompts" / "chemistry.md").read_text() == "my own changed prompt"   # differs: kept
        assert packs.Pack(pack.folder).prompt_path("chemistry") == pack.folder / "prompts" / "chemistry.md"
        assert pack_modules.migrate_copies(pack.folder) == []                 # nothing left to migrate
        assert PackDraft.load(pack.folder).effective_steps()


def test_drafting_adds_the_analysis_module():
    from test_pack_drafting import EDER, KIM, PROPOSAL
    if not (EDER.is_file() and KIM.is_file()):
        print(f"SKIP: needs {EDER} and {KIM}")
        return
    from parameter_extractor import api_client, pack_drafting
    from parameter_extractor.config.run_config import RunConfig

    def call(ctx, *, stage, response_model, **kw):
        return _survey("RP-HPLC (C18, UV 210 nm)") if stage == "pack_survey" else PROPOSAL
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"), \
            patch.object(api_client, "call_structured", call):
        cfg = RunConfig(api_key="test", output_dir=Path(tmp) / "out", rasterize_table_pages=False)
        r = pack_drafting.draft_pack([EDER, KIM], "with_modules", "With modules", "", cfg)
        manifest = json.loads((r.pack.folder / "pack.json").read_text())
        assert "analysis" in manifest["modules"] and not (r.pack.folder / "analysis_vocab.json").exists()
        assert r.module_evidence["analysis"] == {"eder1994": ["RP-HPLC"], "kim2019": ["RP-HPLC"]}
        assert "## Shared modules linked" in (r.pack.folder / "drafted_from.md").read_text()
        r2 = pack_drafting.draft_pack([EDER], "without_modules", "Without", "", cfg, modules_on=False)
        assert "analysis" not in json.loads((r2.pack.folder / "pack.json").read_text()).get("modules", [])


def test_kinetics_wet_dry_and_totals_modules():
    from parameter_extractor.pack_editing import PackDraft, check
    from parameter_extractor.stages.optional import load_specs
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        done = pack_modules.add_modules(pack.folder, ["kinetics", "wet_dry", "peptides_oligomers"])
        assert set(done) >= {"kinetics", "wet_dry", "peptides_oligomers"}
        merged = packs.Pack(pack.folder)
        assert "solution_chemistry" in merged.module_ids()                       # totals bring it along
        assert {"kinetics", "wet_dry"} <= {c["id"] for c in merged.manifest.variable_categories}
        assert "Cycle 1 = 24" in merged.prompt_rules("structure_planner")
        assert {"peptide_totals", "oligomer_totals", "amounts"} <= set(merged.manifest.postprocess)
        assert "chemistry" in merged.manifest.builtin_stages
        assert {"total_sampled_peptides_yield", "max_oligomer_length_nt"} <= {e["column"] for e in merged.standard_column_entries}
        assert {"kinetics", "wet_dry"} <= set(load_specs(merged))
        d = PackDraft.load(pack.folder)
        assert {"rate_constant_first_order_per_hr", "cycle_number"} <= set(d.all_columns())
        assert not [p for p in check(d) if p.level == "error"], [str(p) for p in check(d)]
        assert not list((pack.folder / "stages").glob("kinetics*.json"))           # not copied
        assert pack_modules.add_modules(pack.folder, ["kinetics", "wet_dry", "peptides_oligomers"]) == \
            {"kinetics": [], "wet_dry": [], "peptides_oligomers": []}                # nothing twice


def test_evidence_for_modules():
    def survey(words, compounds=()):
        from parameter_extractor.pack_drafting import SurveyCompound
        return PaperSurvey(field="x", row_unit="r", set_unit="s", notes=words, variables=[], compounds=[
            SurveyCompound(name=c, full_name="", role="product", example="") for c in compounds])
    papers = [SimpleNamespace(name="a", survey=survey("first-order rate constants and half-lives were fitted")),
              SimpleNamespace(name="b", survey=survey("ten wet-dry cycles at 80 °C")),
              SimpleNamespace(name="c", survey=survey("", compounds=["Gly-Gly", "(pA)4"])),
              SimpleNamespace(name="d", survey=survey("N-body simulation of impacts"))]
    ev = pack_modules.evidence_for(papers)
    assert set(ev["kinetics"]) == {"a"} and set(ev["wet_dry"]) == {"b"} and "c" in ev["peptides_oligomers"]
    assert all("d" not in found for found in ev.values())


def test_modules_tab():
    """The editor's Modules tab: tick to link, what a module brings along, steps shown as the module's, saved as a
    reference; the app's own packs read-only."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import PackEditor
    e = PackEditor(packs.BUILTIN_DIR / "prebiotic_chemistry")
    assert "Analysis methods" not in [e.tabs.tabText(i) for i in range(e.tabs.count())]
    assert not e.builtin_boxes["chemistry"].isEnabled() and "Solution chemistry module" in e.builtin_boxes["chemistry"].text()
    assert not e.module_table.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        e = PackEditor(pack.folder)
        t = e.module_table
        rows = {t.item(r, 0).data(Qt.ItemDataRole.UserRole): r for r in range(t.rowCount())}
        compounds = e.tab_index("Compounds")
        assert not e.tabs.isTabEnabled(compounds)
        t.item(rows["peptides_oligomers"], 0).setCheckState(Qt.CheckState.Checked)
        assert t.item(rows["solution_chemistry"], 1).text().startswith("brought along by")
        assert e.tabs.isTabEnabled(compounds) and e.builtin_boxes["chemistry"].isChecked()
        assert "Peptides and oligomers module" in e.module_stages_note.text()   # its linkage step (2026-11-09)
        t.item(rows["kinetics"], 0).setCheckState(Qt.CheckState.Checked)
        assert "Kinetics module" in e.module_stages_note.text()
        t.item(rows["kinetics"], 0).setCheckState(Qt.CheckState.Unchecked)
        t.setCurrentCell(rows["analysis"], 0)
        assert e.analysis_stack.currentIndex() == 0                          # not linked: no vocabulary
        assert e.vocab_box.parent() is not None                              # shown on the module's page
        t.item(rows["analysis"], 0).setCheckState(Qt.CheckState.Checked)
        assert e.analysis_stack.currentIndex() == 1 and e.tech_table.rowCount() > 20
        assert not e._vocab_editable()                                        # the module's: read-only here
        assert e.save()
        own = json.loads((pack.folder / "pack.json").read_text())
        assert own["modules"] == ["analysis", "peptides_oligomers"]
        assert own.get("builtin_stages", []) == [] and own.get("postprocess", []) == []



def test_peptides_and_oligomers_module():
    """2026-11-09: 'Peptide and oligomer totals' became 'Peptides and oligomers' (the old id still works): the chemistry
    step's naming rules for peptides / oligomers come from it, and compound setup fills in every length of a series."""
    import json as _json
    from parameter_extractor import compound_setup, modules, names
    from parameter_extractor.stages.prompt_loader import load_prompt
    assert [m.id for m in modules.resolve(["product_totals"])] == ["solution_chemistry", "peptides_oligomers"]
    assert modules.unknown(["product_totals"]) == []
    mod = modules.available()["peptides_oligomers"]
    assert mod.manifest.compound_series and mod.manifest.prompt_rules["chemistry"]
    assert names.homopolymer("Gly13") == ("peptide", "Gly", 13) and names.homopolymer("Gly-Ala") is None
    assert names.homopolymer("10mer_A") == ("nucleotide", "A", 10) and names.homopolymer_name("peptide", "Gly", 5) == "(Gly)5"
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        pack_modules.add_modules(pack.folder, ["solution_chemistry"])
        try:
            packs.activate("modules_test")
            assert "Peptides: name a peptide" not in load_prompt("chemistry", PAPER_TEXT="", STRUCTURE_PLAN_JSON="")
            pack_modules.add_modules(pack.folder, ["peptides_oligomers"])
            packs.activate("modules_test")
            text = load_prompt("chemistry", PAPER_TEXT="", STRUCTURE_PLAN_JSON="")
            assert "Peptides: name a peptide" in text and "{{MODULE_RULES}}" not in text
            rule = mod.manifest.prompt_rules["chemistry"][1]                    # switched off for this pack
            m = _json.loads((pack.folder / "pack.json").read_text())
            m["module_settings"] = {"peptides_oligomers": {"prompt_rules_off": [rule]}}
            (pack.folder / "pack.json").write_text(_json.dumps(m))
            packs.activate("prebiotic_chemistry")                               # (written behind the pack's back)
            packs.activate("modules_test")
            assert rule not in load_prompt("chemistry", PAPER_TEXT="", STRUCTURE_PLAN_JSON="")
        finally:
            packs.activate("prebiotic_chemistry")
        # the series: Gly2, Gly3 and Gly13 surveyed -> (Gly)4 ... (Gly)12 too, as products in % yield
        surveys = [{"paper": "p", "item": "p", "error": "", "survey": {"field": "x", "row_unit": "r", "set_unit": "s",
                    "notes": "", "variables": [], "compounds": [
                        {"name": "Gly2", "full_name": "glycylglycine", "role": "product", "example": "13.96 %"},
                        {"name": "Gly3", "full_name": "triglycine", "role": "product", "example": "10.4 %"},
                        {"name": "Gly13", "full_name": "", "role": "product", "example": "0.11 %"},
                        {"name": "GG", "full_name": "diglycine", "role": "starting", "example": "3.7 mM"}]}}]
        (pack.folder / "drafted_surveys.json").write_text(_json.dumps(surveys))
        from parameter_extractor.pack_editing import PackDraft
        plan = compound_setup.find_compounds(PackDraft.load(pack.folder), None)
        by = {c.name: c for c in plan.compounds}
        assert all(f"(Gly){n}" in by for n in range(4, 13)), sorted(by)
        assert by["(Gly)7"].roles == {"sampled"} and by["(Gly)7"].measures == {"%yield"}    # what all members share
        assert "Filled in 9 length(s)" in plan.note

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
