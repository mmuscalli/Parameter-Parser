"""
Drafting a research area from sample papers (pack_drafting.py, 2026-11-08) with canned answers: column names get the
app's unit suffixes, the template's examples are replaced, categories / stages / row rules land in the pack format,
the pack loads and passes its check, the report is written, a paper that fails doesn't stop the rest, the id is
checked before anything is paid for; the New research area dialog runs it end to end. No API, no network.
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client, errors, pack_drafting, packs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pack_drafting import (PackProposal, PaperSurvey, ProposedCategory, ProposedParameter,
                                               ProposedStage, SurveyVariable, column_for)

PAPERS = ROOT.parent / "Paper Files" / "Paper Lists"
EDER = PAPERS / "Initial Easy Papers" / "Eder1994" / "eder1994.pdf"
KIM = PAPERS / "Kim2019" / "kim2019.pdf"


def _survey(n):
    return PaperSurvey(field="peptide formation", row_unit="one time point", set_unit="one condition", notes="",
                       compounds=[],
                       variables=[SurveyVariable(name="temperature", column="reaction_temperature", unit="°C",
                                                 kind="number", role="condition", description="heating temperature",
                                                 level="set", uncertainty=False, where="table", example=f"{80 + n} °C"),
                                  SurveyVariable(name="yield", column="product_yield", unit="%", kind="number",
                                                 role="result", description="peptide yield", level="row",
                                                 uncertainty=True, where="table", example="2.77 %")])


PROPOSAL = PackProposal(
    description="Peptides formed from amino acids. One row is one time point.", set_word="reaction condition",
    sample_word="time point", notes="",
    categories=[ProposedCategory(id="conditions", label="Conditions", description="how it ran", value_type="number"),
                ProposedCategory(id="metadata", label="Paper details", description="clash", value_type="text"),
                ProposedCategory(id="results", label="Results", description="what was measured", value_type="number")],
    stages=[ProposedStage(name="conditions", label="Reaction conditions", description="conditions", per="sample",
                          keywords=[], rules=["Read tables."], other_hint="",
                          parameters=[
                              ProposedParameter(column="reaction_temperature", unit="K", kind="number",
                                                description="temperature", category="conditions", choices=[],
                                                uncertainties=True, papers=2),
                              ProposedParameter(column="ph", unit="", kind="number", description="pH",
                                                category="conditions", choices=[], uncertainties=False, papers=1),
                              ProposedParameter(column="reactor", unit="", kind="text", description="setup",
                                                category="metadata", choices=["sealed", "open"], uncertainties=False,
                                                papers=2)]),
            ProposedStage(name="results", label="Results", description="results", per="sample",
                          keywords=["yield"], rules=[], other_hint="other results",
                          parameters=[
                              ProposedParameter(column="product_yield", unit="%", kind="number", description="yield",
                                                category="results", choices=[], uncertainties=True, papers=2),
                              ProposedParameter(column="reaction_temperature", unit="°C", kind="number",
                                                description="repeat", category="results", choices=[],
                                                uncertainties=False, papers=1),
                              ProposedParameter(column="rate", unit="s-1", kind="number", description="rate",
                                                category="nowhere", choices=[], uncertainties=False, papers=1)])],
    row_rules=["One row is one time point.", "Controls are not rows."])


def _fake_call(fail=()):
    calls = []

    def call(ctx, *, stage, system_prompt, user_content, response_model, image_paths=None, max_tokens=None, **kw):
        calls.append((stage, ctx.config.model_for(stage)))
        if stage == "pack_survey":
            if any(name in str(ctx.run_dir) for name in fail):
                raise errors.PipelineError("could not read it")
            return _survey(len(calls))
        assert "SURVEYS:" in user_content and "reaction_temperature" in user_content
        return PROPOSAL
    return call, calls


def test_column_names():
    assert column_for("reaction_temperature", "K") == ("reaction_temperature_C", "°C")
    assert column_for("ph", "") == ("pH", "")
    assert column_for("product_yield", "%") == ("product_yield_pct", "%")
    assert column_for("band_gap", "eV") == ("band_gap_eV", "eV")
    assert column_for("grain_size", "µm") == ("grain_size_um", "µm")
    assert column_for("reactor", "", "text") == ("reactor", "")
    assert column_for("rate", "% h-1") == ("rate", "% h-1")              # a suffix the app would misread: none
    assert column_for("reaction_temperature_C", "°C") == ("reaction_temperature_C", "°C")


def test_draft_writes_a_working_pack():
    if not (EDER.is_file() and KIM.is_file()):
        print(f"SKIP: needs {EDER} and {KIM}")
        return
    call, calls = _fake_call(fail=("kim2019",))
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"), \
            patch.object(api_client, "call_structured", call):
        cfg = RunConfig(api_key="test", output_dir=Path(tmp) / "out", rasterize_table_pages=False)
        progress = []
        r = pack_drafting.draft_pack([EDER, KIM], "peptide_draft", "Peptide synthesis", "Abiotic peptides.", cfg, modules_on=False,
                                     on_progress=lambda d, n, m: progress.append(m))
        assert [c[1] for c in calls] == ["claude-haiku-5-5", "claude-haiku-5-5", "claude-sonnet-5-5"]
        assert [p.name for p in r.papers] == ["eder1994", "kim2019"] and "could not read" in r.papers[1].error
        folder = r.pack.folder
        manifest = json.loads((folder / "pack.json").read_text())
        assert manifest["units"] == {"set": "reaction condition", "sample": "time point"}
        assert manifest["formulas"] == [] and not manifest.get("is_template")
        # fill-in settings for the standard columns it has (2026-11-14: drafted packs had none -- the pack study)
        assert manifest["label_columns"] == {"temperature": "initial_temperature_C", "time": "duration_hr",
                                             "pH": "initial_pH"}                  # no pressure column here
        assert "column_pairs" not in manifest or manifest["column_pairs"] == []   # no related pair present
        assert manifest["postprocess"] == ["ambient_conditions"]                  # modules off: no chemistry step
        assert [c["id"] for c in manifest["variable_categories"]] == ["conditions", "metadata_area", "results"]
        cc = manifest["category_columns"]
        assert cc["methodology"]["columns"] == ["set_type"] and "duration_hr" in cc["conditions"]["columns"]
        assert "reactor" in cc["metadata_area"]["columns"] and "rate_per_hr" in cc["conditions"]["columns"]
        stages = sorted(p.name for p in (folder / "stages").glob("*.json"))
        assert stages == ["conditions.json", "results.json"]                     # the template's example is gone
        cond = json.loads((folder / "stages" / "conditions.json").read_text())
        assert cond["trigger"] == {"always": True} and cond["rules"] == ["Read tables."]
        assert cond["parameters"][0] == {"column": "initial_temperature_C", "description": "temperature",
                                         "unit": "°C", "uncertainties": True}
        assert cond["parameters"][2]["choices"] == ["sealed", "open"] and cond["parameters"][2]["kind"] == "text"
        res = json.loads((folder / "stages" / "results.json").read_text())
        assert res["trigger"] == {"keywords": ["yield"]} and res["open_ended_hint"] == "other results"
        assert [p["column"] for p in res["parameters"]] == ["product_yield_pct", "rate_per_hr"]   # repeat dropped
        assert r.dropped == ["initial_temperature_C (stage results)"]
        assert any(t.startswith("reaction_temperature_C -> initial_temperature_C") for t in r.tidied)
        assert any(t.startswith("pH -> initial_pH") for t in r.tidied)
        columns = json.loads((folder / "columns.json").read_text())["all_columns"]
        assert columns == ["set_type", "duration_hr", "initial_temperature_C", "initial_pH", "reactor", "product_yield_pct",
                           "rate_per_hr"]
        assert (folder / "prompts" / "structure_planner.rules.md").read_text() == \
            "- One row is one time point.\n- Controls are not rows.\n"
        report = (folder / "drafted_from.md").read_text()
        assert "`product_yield_pct` [%]" in report and "kim2019: not surveyed" in report and "2.77 %" in report
        assert not [p for p in r.problems if p.level == "error"], r.problems
        from parameter_extractor.stages.optional import load_specs
        specs = load_specs(r.pack)
        assert set(specs) == {"conditions", "results"}
        assert (r.work_dir / "surveys.json").is_file() and progress[-1].startswith("Drafted")
        # the id is checked before anything is paid for
        calls.clear()
        for bad in ("peptide_draft", "Bad Id"):
            try:
                pack_drafting.draft_pack([EDER], bad, "x", "", cfg)
                raise AssertionError("expected ValueError")
            except ValueError:
                pass
        assert not calls
        # every paper failing: an error, no pack
        call2, _ = _fake_call(fail=("eder1994",))
        with patch.object(api_client, "call_structured", call2):
            try:
                pack_drafting.draft_pack([EDER], "other_draft", "Other", "", cfg)
                raise AssertionError("expected PipelineError")
            except errors.PipelineError as e:
                assert "None of the papers" in str(e)
        assert not (Path(tmp) / "packs" / "other_draft").exists()


def test_new_pack_dialog_drafts():
    if not EDER.is_file():
        print(f"SKIP: needs {EDER}")
        return
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import DRAFT, NewPackDialog
    call, _ = _fake_call()
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"), \
            patch.object(api_client, "call_structured", call):
        cfg = RunConfig(api_key="", output_dir=Path(tmp) / "out", rasterize_table_pages=False)
        holder = {"cfg": cfg}
        d = NewPackDialog(config=lambda: holder["cfg"])
        d.source_combo.setCurrentIndex(d.source_combo.findData(DRAFT))
        assert d.draft_box.isVisibleTo(d) and d.create_btn.text() == "Draft from these papers"
        d.label_edit.setText("Peptide synthesis")
        d.create()
        assert "sample papers" in d.error.text()
        d.papers.add_items([EDER])
        d.create()
        assert "API key" in d.error.text()                    # nothing started without a key
        holder["cfg"] = RunConfig(api_key="test", output_dir=Path(tmp) / "out", rasterize_table_pages=False)
        d.create()
        deadline = time.time() + 60
        while d.result() == 0 and time.time() < deadline:
            app.processEvents()
            time.sleep(0.05)
        assert d.created is not None and d.created.id == "peptide_synthesis", d.error.text()
        assert d.draft_result.cost_usd == 0 and (d.created.folder / "drafted_from.md").is_file()


def test_stage_discipline():
    """A stage costs a request per paper: < 3 parameters -> merged into the closest stage; at most two stages run on
    every paper, the others get trigger words (2026-11-08)."""
    from parameter_extractor.pack_drafting import _disciplined_stages
    par = lambda c, d: ProposedParameter(column=c, unit="", kind="number", description=d, category="x", choices=[],
                                         uncertainties=False, papers=1)
    st = lambda name, params, kw=(): ProposedStage(name=name, label=name, description=name, per="sample",
                                                   keywords=list(kw), parameters=params, rules=[], other_hint="")
    stages = [st("conditions", [par("temperature", "reaction temperature"), par("ph", "solution ph"),
                                par("pressure", "reaction pressure")]),
              st("results", [par("yield", "product yield"), par("length", "oligomer length"), par("rate", "rate")]),
              st("transport", [par("gradient", "thermal gradient across chamber"), par("thickness", "chamber gap"),
                               par("velocity", "flow velocity in the chamber")]),
              st("extra_temperature", [par("cold_side_temperature", "cold side temperature of the reaction")])]
    notes = []
    out = _disciplined_stages(stages, notes)
    assert [s.name for s in out] == ["conditions", "results", "transport"]
    assert any(p.column == "cold_side_temperature" for p in out[0].parameters)       # merged into conditions
    assert not out[0].keywords and not out[1].keywords and out[2].keywords             # only two always run
    assert any("merged into stage conditions" in n for n in notes)



ASTRO_PROPOSAL = PackProposal(
    description="Exoplanet discoveries. One row is one planet.", set_word="host star system", sample_word="planet",
    notes="",
    categories=[ProposedCategory(id="planet", label="Planet", description="the planet", value_type="number"),
                ProposedCategory(id="star", label="Host star", description="the star", value_type="number")],
    stages=[ProposedStage(name="planet_parameters", label="Planet parameters", description="each planet",
                          per="sample", keywords=[], rules=[], other_hint="", parameters=[
                              ProposedParameter(column=c, unit=u, kind="number", description=c, category="planet",
                                                choices=[], uncertainties=True, papers=3)
                              for c, u in [("orbital_period", "d"), ("semi_major_axis", "au"),
                                           ("time_of_conjunction", "BJD-2457000"), ("transit_duration", "h"),
                                           ("planet_mass", "M_earth"), ("planet_radius", "R_earth"),
                                           ("equilibrium_temperature", "K"), ("planet_density", "g/cm3")]]),
            ProposedStage(name="host_star", label="Host star", description="the star", per="set", keywords=[],
                          rules=[], other_hint="", parameters=[
                              ProposedParameter(column=c, unit=u, kind="number", description=c, category="star",
                                                choices=[], uncertainties=True, papers=3)
                              for c, u in [("stellar_effective_temperature", "K"), ("stellar_mass", "M_sun"),
                                           ("stellar_age", "Myr"), ("stellar_luminosity", "log(L_sun)"),
                                           ("stellar_metallicity", "dex")]])],
    row_rules=["One row is one planet."])


def test_units_follow_the_research_area():
    """Mickey, 2026-11-20 (accuracy evaluation, Phase 1): a drafted exoplanet pack had stellar temperatures in °C and
    orbital periods in hours although the design asked for K and days -- the lab datasets' conventions applied to an
    astronomy field. A pack whose units are astronomy's keeps the field's own; a lab pack is drafted as before."""
    from parameter_extractor import conventions
    from parameter_extractor.pack_drafting import write_pack
    assert conventions.unit_system(["d", "au", "M_earth", "R_earth", "K", "M_sun"]) == conventions.ASTRONOMY
    assert conventions.unit_system(["°C", "h", "mM", "bar", "%", "K", "d", "km/s", "GPa"]) == conventions.LAB
    assert conventions.unit_system(["°C", "mM", "au"]) == conventions.LAB          # one astronomy unit doesn't decide
    assert column_for("orbital_period", "d", system="astronomy") == ("orbital_period_d", "d")
    assert column_for("equilibrium_temperature", "K", system="astronomy") == ("equilibrium_temperature_K", "K")
    assert column_for("planet_mass", "M_earth", system="astronomy") == ("planet_mass_M_E", "M_E")
    assert column_for("t0", "BJD-2457000", system="astronomy") == ("t0_BJD", "BJD")     # stored as the full date
    assert column_for("planet_density", "g/cm3", system="astronomy") == column_for("planet_density", "g/cm3")
    assert column_for("equilibrium_temperature", "K") == ("equilibrium_temperature_C", "°C")   # lab: unchanged
    assert column_for("stellar_log_g", "dex", system="astronomy") == ("stellar_log_g_dex", "dex")   # log g keeps its g
    assert column_for("primer_concentration_um", "mM") == ("primer_concentration_mM", "mM")      # a unit word goes
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack, _, _ = write_pack(ASTRO_PROPOSAL, "astro_drafted", "Astro drafted", base=Path(tmp))
        m = json.loads((pack.folder / "pack.json").read_text())
        assert m["unit_system"] == "astronomy"
        params = {p["column"]: p.get("unit") for f in (pack.folder / "stages").glob("*.json")
                  for p in json.loads(f.read_text())["parameters"]}
        assert params["orbital_period_d"] == "d" and params["transit_duration_h"] == "h"
        assert params["stellar_effective_temperature_K"] == "K" and params["equilibrium_temperature_K"] == "K"
        assert params["time_of_conjunction_BJD"] == "BJD" and params["planet_mass_M_E"] == "M_E"
        assert params["stellar_age_Myr"] == "Myr" and params["stellar_luminosity_log_L_sun"] == "log(L_sun)"
        assert not any(c.endswith(("_C", "_hr")) for c in params), params
        columns = json.loads((pack.folder / "columns.json").read_text())
        assert "duration_hr" not in json.dumps(columns)        # a sample's time in hours is the lab datasets' row column
        from parameter_extractor.pack_editing import PackDraft, check
        unit_problems = [p for p in check(PackDraft.load(pack.folder)) if "named in" in p.message]
        assert not unit_problems, unit_problems
        # the step converts a value printed in another astronomy unit into the column's
        from parameter_extractor.units import convert_printed
        assert convert_printed(2.0, "days", "d")[0] == 2.0 and abs(convert_printed(48.0, "h", "d")[0] - 2.0) < 1e-9
        assert convert_printed(5.0, "BJD - 2457000", "BJD")[0] == 2457005.0
        lab, _, _ = write_pack(PROPOSAL, "lab_drafted", "Lab drafted", base=Path(tmp))
        assert "unit_system" not in json.loads((lab.folder / "pack.json").read_text())
        assert packs.Pack(lab.folder).manifest.unit_system == "lab"
        assert packs.Pack(pack.folder).manifest.unit_system == "astronomy"


def test_a_drafted_pack_gets_levels_and_fill_settings_from_the_surveys():
    """Branch levels-and-facets: a drafted pack's categories get the level their values sit at and whether they're
    filled in, from what the surveys say of each variable (where it differs, its role) -- conditions that differ
    between sets: the set, filled within it; results: the rows, never filled. The template's settings stay."""
    from types import SimpleNamespace
    from parameter_extractor.calculators.shared_values import selectors
    from parameter_extractor.pack_drafting import structure_from_surveys, write_pack
    surveys = [SimpleNamespace(survey=_survey(n)) for n in range(3)]
    levels, fills, never = structure_from_surveys(
        [("temp_C", "conditions", "reaction_temperature"), ("yield_pct", "results", "product_yield")], surveys)
    assert levels == {"conditions": "set"} and fills == {"conditions": "set"} and never == []
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack, _, _ = write_pack(PROPOSAL, "levels_drafted", "Levels drafted", base=Path(tmp), surveys=surveys)
        m = json.loads((pack.folder / "pack.json").read_text())
        cats = {c["id"]: c for c in m["variable_categories"]}
        assert cats["conditions"]["level"] == "set" and cats["conditions"]["fill"] == "set"
        assert "level" not in cats["results"] and "fill" not in cats["results"]
        assert m["category_fill"] == {"methodology": "paper"} and m["fill_columns"]["duration_hr"] == "none"
        assert "shared_columns" not in m and "group_columns" not in m
        shared, group = selectors(packs.Pack(pack.folder))
        assert "conditions" in group["categories"] and "methodology" in shared["categories"]
        # without surveys (an older caller): the template's settings only
        plain, _, _ = write_pack(PROPOSAL, "levels_plain", "Levels plain", base=Path(tmp))
        m2 = json.loads((plain.folder / "pack.json").read_text())
        assert not any(c.get("fill") or c.get("level") for c in m2["variable_categories"])


def test_modules_are_chosen_before_the_design():
    """2026-11-09: the modules the surveys call for are chosen BEFORE the design request, which is told what they
    record; what a proposal still asks of them is left to them; a step named like a module's is renamed; compounds
    are set up when the chemistry step is linked (numbers stripped, product measures from the examples)."""
    from parameter_extractor.pack_drafting import (SurveyCompound, SurveyVariable, covered_by_module,
                                                   modules_brief, write_pack)
    from parameter_extractor.pack_editing import PackDraft
    from parameter_extractor import pack_modules, compound_setup
    brief = modules_brief(["kinetics", "peptides_oligomers"])
    assert "SHARED MODULES" in brief and "Kinetics:" in brief and "Solution chemistry:" in brief    # needs
    assert covered_by_module("rate_constant_per_M_hr", "number", ["kinetics"], []) == "Kinetics"
    assert covered_by_module("product_yield_pct", "number", ["solution_chemistry"], []) == "Solution chemistry"
    assert covered_by_module("salt_or_additive", "text", ["solution_chemistry"], []) == "Solution chemistry"
    assert covered_by_module("detection_wavelength_nm", "number", ["analysis"], []) == "Analysis methods"
    assert covered_by_module("analysis_method", "text", ["analysis"], []) == ""
    assert covered_by_module("initial_temperature_C", "number", ["solution_chemistry", "analysis"], []) == ""
    # survey evidence for the solution-chemistry module: compounds + concentrations in solution
    var = SurveyVariable(name="glycine concentration", column="glycine_concentration", unit="mM", kind="number",
                         role="composition", description="glycine in the aqueous solution", level="set",
                         uncertainty=False, where="table", example="100 mM")
    survey = PaperSurvey(field="x", row_unit="r", set_unit="s", notes="", variables=[var], compounds=[
        SurveyCompound(name="Gly", full_name="glycine", role="starting", example="100 mM")])
    from types import SimpleNamespace
    assert "a" in pack_modules.solution_evidence([SimpleNamespace(name="a", survey=survey)])
    # the design request carries the brief
    seen = {}

    def call(ctx, *, stage, response_model, user_content="", **kw):
        seen[stage] = user_content
        return PROPOSAL
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "call_structured", call):
        cfg = RunConfig(api_key="test", output_dir=Path(tmp) / "out", rasterize_table_pages=False)
        pack_drafting.synthesize([], cfg, Path(tmp), "Area", "", modules=["kinetics"])
        assert "SHARED MODULES" in seen["pack_synthesis"] and "rate constants" in seen["pack_synthesis"]
    # writing: covered parameters left out, a module-named step renamed, modules linked
    proposal = PROPOSAL.model_copy(deep=True)
    proposal.stages[1].name = "kinetics"
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack, _, by_column = write_pack(proposal, "mods_first", "Mods first", base=Path(tmp),
                                        modules=["kinetics", "solution_chemistry"])
        left = by_column["__left_to_modules__"]
        d = PackDraft.load(pack.folder)
        own = {s["name"]: [p["column"] for p in s["parameters"]] for s in d.stages.values()}
        assert d.manifest["modules"] == ["kinetics", "solution_chemistry"]
        assert any("product_yield" in l and "Solution chemistry" in l for l in left), left
        assert "kinetics" not in own                                        # the module's step keeps its name
        assert not any("product_yield" in c for cols in own.values() for c in cols)
    # compound numbers and product measures (compound_setup)
    assert compound_setup._without_compound_number({"name": "nicotinamide 6", "full_name": ""})["name"] == "nicotinamide"
    assert compound_setup._without_compound_number({"name": "4", "full_name": "ribose-1,2-cyclic phosphate 4"})[
        "name"] == "ribose-1,2-cyclic phosphate"
    assert compound_setup._without_compound_number({"name": "7", "full_name": ""}) is None
    assert compound_setup._example_measure("13.96 %") == "%yield"
    assert compound_setup._example_measure("12 % recovered") == "%recovered"
    assert compound_setup._example_measure("2.5 mM") == "mM" and compound_setup._example_measure("") is None
    # a list sent as a JSON string with stray words after it (api_client._decoded)
    assert api_client._decoded({"rows": '[{"a": 1}]\nthe rows'}) == {"rows": [{"a": 1}]}

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
