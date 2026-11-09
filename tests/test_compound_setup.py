"""
Compounds for a drafted research area (compound_setup.py) and suggested additions to an existing one
(pack_drafting.suggest_additions / apply_additions), 2026-11-08. A fake PubChem, canned model answers; the review
windows and the editor's buttons. No API, no network.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PARAMETER_EXTRACTOR_NO_KEYCHAIN", "1")      # never the real keychain (macOS asks)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client, compound_setup, pack_drafting, packs
from parameter_extractor.compound_setup import formula_case, names_in_column, names_in_text
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pack_editing import PackDraft, check

KNOWN = {"mgcl2": (5360315, "Magnesium Chloride"), "nacl": (5234, "Sodium Chloride"), "ump": (6030, "UMP"),
         "2',3'-cgmp": (135398728, "cGMP"), "diamidophosphate": (23280244, "Diamidophosphate"),
         "tris": (6503, "Tris"), "formamide": (713, "Formamide")}


class FakePubChem:
    unavailable_reason = ""

    def __init__(self):
        self.asked = []

    def lookup(self, name):
        self.asked.append(name)
        hit = KNOWN.get(name.lower())
        return SimpleNamespace(cid=hit[0], title=hit[1]) if hit else None

    def synonyms(self, cid):
        return [f"syn-{cid}"] + (["UMP"] if cid == 6030 else [])        # a code PubChem does list

    def save(self):
        pass


def _drafted_pack(base: Path):
    """A pack shaped like Mickey's 'Prebiotic (Sam Papers)' draft."""
    pack = packs.create_pack("sam_like", "Sam-like", base=base)
    d = PackDraft.load(pack.folder)
    for f in list(d.stages):
        d.remove_stage(f)
    d.manifest["formulas"] = []
    d.manifest["variable_categories"] = [
        {"id": "composition", "table_order": 30, "label": "Composition", "value_type": "number", "model_assigns": True,
         "description": "x"},
        {"id": "results", "table_order": 40, "label": "Results", "value_type": "number", "model_assigns": True,
         "description": "y"}]
    f1 = d.new_stage("conditions", "Conditions")
    d.stages[f1]["parameters"] = [
        {"column": "reactant_species", "kind": "text", "description": "Main reactant (e.g. 2',3'-cGMP, UMP, or ribose)."},
        {"column": "reactant_concentration_mM", "unit": "mM", "description": "Its starting concentration."},
        {"column": "mgcl2_concentration_mM", "unit": "mM", "description": "MgCl2 in the solution."},
        {"column": "nacl_concentration_mM", "unit": "mM", "description": "NaCl in the solution."},
        {"column": "buffer_concentration_mM", "unit": "mM", "description": "The buffer, such as Tris."},
        {"column": "reaction_temperature_C", "unit": "°C", "description": "Temperature."},
        {"column": "solvent", "kind": "text", "description": "Solvent, e.g. water or formamide."}]
    f2 = d.new_stage("results", "Results")
    d.stages[f2]["parameters"] = [
        {"column": "product_name", "kind": "text", "description": "The product."},
        {"column": "product_yield_pct", "unit": "%", "description": "Its yield."},
        {"column": "oligomer_length_nt", "unit": "nt", "description": "Longest oligomer."}]
    cols = [p["column"] for s in d.stages.values() for p in s["parameters"]]
    d.columns = ["set_type", "duration_hr"] + cols
    d.manifest["category_columns"] = {"composition": {"columns": cols[:7]}, "results": {"columns": cols[7:]}}
    d.save()
    (pack.folder / compound_setup.SURVEYS_FILE).write_text(json.dumps([{"paper": "p1", "survey": {"variables": [
        {"column": "product_name", "kind": "text", "example": "UMP"}]}}]))
    return pack


def test_name_helpers():
    assert formula_case("mgcl2") == "MgCl2" and formula_case("nacl") == "NaCl" and formula_case("cacl2") == "CaCl2"
    assert formula_case("buffer") is None and formula_case("pyrite") is None and formula_case("ribose") is None
    assert names_in_column("mgcl2_concentration_mM") == ["mgcl2"]
    assert names_in_column("activating_agent_concentration_mM") == []
    assert names_in_text("Main reactant (e.g. 2',3'-cGMP, UMP, or ribose).") == ["2',3'-cGMP", "UMP", "ribose"]


def test_find_and_apply_compounds():
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = _drafted_pack(Path(tmp))
        plan = compound_setup.find_compounds(PackDraft.load(pack.folder), FakePubChem())
        names = {c.name: c for c in plan.compounds}
        assert {"MgCl2", "NaCl", "UMP", "2',3'-cGMP"} <= set(names), names
        assert names["MgCl2"].columns() == ["initial_MgCl2_aq_mM"] and names["MgCl2"].cid == 5360315
        assert "sampled" in names["UMP"].roles and "initial" in names["UMP"].roles      # reactant AND product example
        assert "sampled_UMP_aq_%yield" in names["UMP"].columns()
        replaced = {r.column for r in plan.replacements}
        assert {"reactant_species", "reactant_concentration_mM", "mgcl2_concentration_mM", "nacl_concentration_mM",
                "product_name", "product_yield_pct", "buffer_concentration_mM"} == replaced
        assert "reaction_temperature_C" not in replaced and "solvent" not in replaced     # not a substance pair
        next(r for r in plan.replacements if r.column == "nacl_concentration_mM").include = False   # the user keeps it
        _, done, problems = compound_setup.set_up_compounds(pack.folder, FakePubChem(), plan=plan)
        d = PackDraft.load(pack.folder)
        assert "chemistry" in d.manifest["builtin_stages"]
        assert d.manifest["postprocess"][:3] == ["normalize_species", "mixing", "molar_ratios"]
        assert {"MgCl2", "UMP", "Tris"} <= set(d.species)
        ref = compound_setup._reference_cids()["MgCl2"]            # the prebiotic pack's checked identity wins
        assert d.cids_file["species"]["MgCl2"]["cid"] == ref["cid"]
        params = [p["column"] for s in d.stages.values() for p in s["parameters"]]
        assert "mgcl2_concentration_mM" not in params and "nacl_concentration_mM" in params
        assert "initial_MgCl2_aq_mM" in d.columns and "mgcl2_concentration_mM" not in d.columns
        from parameter_extractor.column_order import ColumnOrder        # compounds in their own blocks
        order = ColumnOrder(pack=packs.Pack(pack.folder))
        assert order.category_of("initial_MgCl2_aq_mM") == "starting_compounds"
        assert order.category_of("sampled_UMP_aq_%yield") == "products"
        assert order.category_of("initial_temperature_C") != "starting_compounds"
        assert all(compound_setup.CHEMISTRY_RULE in s["rules"] for s in d.stages.values())
        assert (pack.folder / "prompts" / "chemistry.md").is_file()
        assert not [p for p in problems if p.level == "error"], problems
        assert any("chemistry prompt copied" in line for line in done)


def test_suggest_and_apply_additions():
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = packs.create_pack("prebiotic_copy", "Prebiotic copy", source=packs.available()["prebiotic_chemistry"])
        pdf = ROOT.parent / "Paper Files" / "Paper Lists" / "Initial Easy Papers" / "Eder1994" / "eder1994.pdf"
        if not pdf.is_file():
            print(f"SKIP: needs {pdf}")
            return
        from parameter_extractor.pack_drafting import (PackAdditions, PaperSurvey, ProposedCategory, SuggestedCompound,
                                                       SuggestedParameter, SuggestedRule, SuggestedStage)
        from parameter_extractor.pack_drafting import SurveyCompound
        survey = PaperSurvey(field="x", row_unit="r", set_unit="s", notes="", variables=[], compounds=[
            SurveyCompound(name="A", full_name="", role="starting", example=""),           # a base letter
            SurveyCompound(name="SYBR Green I", full_name="", role="reagent", example=""),
            SurveyCompound(name="KCl/MgCl2", full_name="", role="reagent", example=""),    # two salts
            SurveyCompound(name="Gly-Gly", full_name="", role="product", example="")])     # known already
        survey.variables = [pack_drafting.SurveyVariable(name="t", column="t", unit="°C", kind="number",
                                                         role="condition", description="d", level="set",
                                                         uncertainty=False, where="table", example="80 °C")]
        common = dict(kind="number", category="conditions", choices=[], uncertainties=False, papers=2, reason="r")
        answer = PackAdditions(
            parameters=[SuggestedParameter(stage="experimental_conditions", column="irradiation_wavelength", unit="nm",
                                           description="UV wavelength.", **common),
                        SuggestedParameter(stage="experimental_conditions", column="initial_temperature", unit="°C",
                                           description="already there", **common),
                        SuggestedParameter(stage="photochemistry", column="photon_flux", unit="",
                                           description="flux", **common)],
            new_stages=[SuggestedStage(name="photochemistry", label="Photochemistry", description="light",
                                       per="sample", keywords=["irradiat"])],
            categories=[ProposedCategory(id="light", label="Light", description="irradiation", value_type="number")],
            rules=[SuggestedRule(target="rows", rule="Dark controls are not rows.", reason="r"),
                   SuggestedRule(target="experimental_conditions", rule="Lamp power goes in other.", reason="r")],
            compounds=[SuggestedCompound(name="Tris", role="initial", papers=1, reason="buffer"),
                       SuggestedCompound(name="NaCl", role="initial", papers=3, reason="already there"),
                       SuggestedCompound(name="DNase I", role="initial", papers=1, reason="enzyme"),
                       SuggestedCompound(name="ab", role="initial", papers=1, reason="panel letters")],
            notes="")

        def call(ctx, *, stage, response_model, **kw):
            return survey if stage == "pack_survey" else answer
        with patch.object(api_client, "call_structured", call):
            cfg = RunConfig(api_key="test", output_dir=Path(tmp) / "out", rasterize_table_pages=False)
            r = pack_drafting.suggest_additions(pack.folder, [pdf], cfg)
        kinds = [(s.kind, s.title) for s in r.suggestions]
        assert ("parameter", "irradiation_wavelength_nm") in kinds and ("compound", "Tris") in kinds
        assert ("stage", "Photochemistry") in kinds and ("category", "Light") in kinds
        compounds = sorted(t for k, t in kinds if k == "compound")
        assert compounds == ["Tris"], compounds      # KCl, MgCl2, Gly-Gly are in the vocabulary already; A, SYBR, DNase, ab dropped
        assert not any(t == "initial_temperature_C" for _, t in kinds)                 # already a column
        assert "initial_temperature_C (already a column)" in r.left_out and "NaCl (already a compound)" in r.left_out
        done, problems = pack_drafting.apply_additions(pack.folder, r.suggestions, FakePubChem())
        d = PackDraft.load(pack.folder)
        cond = next(s for s in d.stages.values() if s["name"] == "experimental_conditions")
        assert any(p["column"] == "irradiation_wavelength_nm" for p in cond["parameters"])
        assert "Lamp power goes in other." in cond["rules"]
        photo = next(s for s in d.stages.values() if s["name"] == "photochemistry")
        assert photo["trigger"] == {"keywords": ["irradiat"]} and photo["parameters"][0]["column"] == "photon_flux"
        assert any(c["id"] == "light" for c in d.manifest["variable_categories"])
        assert "Tris" in d.species and d.cids_file["species"]["Tris"]["cid"] == 6503
        assert "initial_Tris_aq_mM" in d.columns
        own = (pack.folder / "prompts" / "structure_planner.md").read_text()      # the pack's own whole prompt
        assert own.rstrip().endswith("- Dark controls are not rows.")
        assert not [p for p in problems if p.level == "error"], problems


def test_review_windows_and_editor_buttons():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_assist import AdditionsDialog, CompoundSetupDialog
    from parameter_extractor.gui.pack_windows import PackEditor
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = _drafted_pack(Path(tmp))
        with patch("parameter_extractor.pubchem.PubChem", lambda *a, **k: FakePubChem()):
            dlg = CompoundSetupDialog(pack.folder)
        assert dlg.compound_table.rowCount() >= 4 and dlg.apply_btn.isEnabled()
        row = next(r for r in range(dlg.compound_table.rowCount()) if dlg.compound_table.item(r, 0).text() == "NaCl")
        dlg.compound_table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        dlg.apply()
        d = PackDraft.load(pack.folder)
        assert "NaCl" not in d.species and "MgCl2" in d.species and dlg.applied
        # suggestions shown, one unticked, the rest applied
        sug = [pack_drafting.Suggestion("rule", "Controls aren't rows.", "planning the rows", payload=("rows", "Controls aren't rows.")),
               pack_drafting.Suggestion("rule", "Skip me.", "planning the rows", payload=("rows", "Skip me."))]
        add = AdditionsDialog(pack.folder, config=lambda: RunConfig(api_key="", output_dir=Path(tmp)))
        add.run()
        assert "Add a few" in add.status.text()
        add.show_suggestions(pack_drafting.AdditionsResult(suggestions=sug, papers=[], work_dir=Path(tmp)))
        add.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        with patch("parameter_extractor.pubchem.PubChem", lambda *a, **k: FakePubChem()):
            add.apply()
        rules = (pack.folder / "prompts" / "structure_planner.rules.md").read_text()
        assert "Controls aren't rows." in rules and "Skip me." not in rules
        # the editor's buttons: on for the user's own area, off for the app's
        ed = PackEditor(pack.folder, config=lambda: None)
        assert ed.compounds_btn.isEnabled() and ed.suggest_btn.isEnabled()
        builtin = PackEditor(packs.available()["prebiotic_chemistry"].folder)
        assert not builtin.compounds_btn.isEnabled() and not builtin.suggest_btn.isEnabled()


def test_reported_misses_and_conventions():
    """Mickey's Sam Papers draft (2026-11-08): 'mg' from a column became elemental magnesium (the paper used MgCl2),
    ImpA / RCP matched unrelated compounds on PubChem, 'borate' became 'BORaTe'; names like 'pH' and
    'reaction_temperature_C' instead of the app's conventions."""
    from parameter_extractor.conventions import canonical
    assert formula_case("borate") is None and formula_case("mg") is None
    assert compound_setup.is_abbreviation("ImpA") and compound_setup.is_abbreviation("RCP")
    assert not compound_setup.is_abbreviation("MgCl2") and not compound_setup.is_abbreviation("NaCl")
    assert canonical("pH", "", "number").column == "initial_pH"
    assert canonical("measured_pH", "", "number").column == "sampled_pH"
    assert canonical("reaction_temperature_C", "°C").column == "initial_temperature_C"
    assert canonical("reaction_time_hr", "h").column == ""                         # duration_hr: the row column
    assert canonical("wet_dry_cycles", "", "number").column == "cycle_number"
    assert canonical("warm_side_temperature_C", "°C") is None and canonical("initial_pH", "") is None
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = packs.create_pack("sam_check", "Sam check", base=Path(tmp))
        d = PackDraft.load(pack.folder)
        for f in list(d.stages):
            d.remove_stage(f)
        f1 = d.new_stage("conditions", "Conditions")
        d.stages[f1]["parameters"] = [
            {"column": "mg_concentration_mM", "unit": "mM", "description": "Concentration of Mg2+ (as MgCl2)."},
            {"column": "pH", "description": "Initial pH."},
            {"column": "reaction_temperature_C", "unit": "°C", "description": "Temperature."}]
        d.columns = ["set_type", "duration_hr", "mg_concentration_mM", "pH", "reaction_temperature_C"]
        d.save()
        (pack.folder / compound_setup.SURVEYS_FILE).write_text(json.dumps([{"paper": "p", "survey": {
            "variables": [], "compounds": [
                {"name": "ImpA", "full_name": "adenosine 5'-phosphorimidazolide", "role": "starting", "example": ""},
                {"name": "RCP", "full_name": "", "role": "product", "example": ""},
                {"name": "KCl", "full_name": "", "role": "reagent", "example": "100 mM"}]}}]))
        fake = FakePubChem()
        KNOWN["adenosine 5'-phosphorimidazolide"] = (3035161, "Adenosine 5'-phosphorimidazolide")
        KNOWN["impa"] = (15778, "Isopropyl methylphosphonate")      # PubChem's (wrong) answer for the abbreviation
        KNOWN["rcp"] = (449097, "CP-640186")
        KNOWN["kcl"] = (4873, "Potassium Chloride")
        plan = compound_setup.find_compounds(PackDraft.load(pack.folder), fake)
        by = {c.name: c for c in plan.compounds}
        assert "MgCl2" in by and "mg" not in by and "Mg" not in by, by          # spelled out by the description
        assert by["ImpA"].cid == 3035161                                         # via its full name, not 'ImpA'
        assert by["RCP"].cid == 0             # PubChem's hit doesn't list 'RCP' among its names: not taken
        assert not compound_setup.is_compound_name("Taq polymerase") and not compound_setup.is_compound_name(
            "RNA oligomers") and compound_setup.is_compound_name("MgCl2")
        assert "sampled_RCP_aq_mM" in by["RCP"].columns() and by["KCl"].columns() == ["initial_KCl_aq_mM"]
        assert {(r.column, r.new) for r in plan.renames} == {("pH", "initial_pH"),
                                                             ("reaction_temperature_C", "initial_temperature_C")}
        _, done, problems = compound_setup.set_up_compounds(pack.folder, fake, plan=plan)
        d = PackDraft.load(pack.folder)
        cols = [p["column"] for s in d.stages.values() for p in s["parameters"]]
        assert cols == ["initial_pH", "initial_temperature_C"] and "initial_MgCl2_aq_mM" in d.columns
        assert "pH" not in d.columns and "initial_pH" in d.columns
        assert not [p for p in problems if p.level == "error"], problems


def test_survey_passes_are_merged():
    from parameter_extractor.pack_drafting import PaperSurvey, SurveyCompound, SurveyVariable, merge_surveys
    v = lambda c: SurveyVariable(name=c, column=c, unit="", kind="number", role="result", description="",
                                 level="row", uncertainty=False, where="table", example="1")
    c = lambda n: SurveyCompound(name=n, full_name="", role="starting", example="")
    a = PaperSurvey(field="f", row_unit="r", set_unit="s", notes="", variables=[v("yield"), v("ph")],
                    compounds=[c("MgCl2")])
    b = PaperSurvey(field="g", row_unit="r2", set_unit="s2", notes="", variables=[v("Yield"), v("rate")],
                    compounds=[c("mgcl2"), c("NaCl")])
    m = merge_surveys([a, b])
    assert [x.column for x in m.variables] == ["yield", "ph", "rate"] and [x.name for x in m.compounds] == ["MgCl2", "NaCl"]
    assert m.field == "f"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
