"""
Drafting a research area from sample papers (pack_drafting.py, 2026-11-08) with canned answers: column names get the
app's unit suffixes, the template's examples are replaced, categories / stages / row rules land in the pack format,
the pack loads and passes its check, the report is written, a paper that fails doesn't stop the rest, the id is
checked before anything is paid for; the New research area dialog runs it end to end. No API, no network.
"""
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
        r = pack_drafting.draft_pack([EDER, KIM], "peptide_draft", "Peptide synthesis", "Abiotic peptides.", cfg,
                                     on_progress=lambda d, n, m: progress.append(m))
        assert [c[1] for c in calls] == ["claude-haiku-5-5", "claude-haiku-5-5", "claude-sonnet-5-5"]
        assert [p.name for p in r.papers] == ["eder1994", "kim2019"] and "could not read" in r.papers[1].error
        folder = r.pack.folder
        manifest = json.loads((folder / "pack.json").read_text())
        assert manifest["units"] == {"set": "reaction condition", "sample": "time point"}
        assert manifest["formulas"] == [] and not manifest.get("is_template")
        assert [c["id"] for c in manifest["variable_categories"]] == ["conditions", "metadata_area", "results"]
        cc = manifest["category_columns"]
        assert cc["methodology"]["columns"] == ["set_type"] and "duration_hr" in cc["conditions"]["columns"]
        assert "reactor" in cc["metadata_area"]["columns"] and "rate_per_hr" in cc["conditions"]["columns"]
        stages = sorted(p.name for p in (folder / "stages").glob("*.json"))
        assert stages == ["conditions.json", "results.json"]                     # the template's example is gone
        cond = json.loads((folder / "stages" / "conditions.json").read_text())
        assert cond["trigger"] == {"always": True} and cond["rules"] == ["Read tables."]
        assert cond["parameters"][0] == {"column": "reaction_temperature_C", "description": "temperature",
                                         "unit": "°C", "uncertainties": True}
        assert cond["parameters"][2]["choices"] == ["sealed", "open"] and cond["parameters"][2]["kind"] == "text"
        res = json.loads((folder / "stages" / "results.json").read_text())
        assert res["trigger"] == {"keywords": ["yield"]} and res["open_ended_hint"] == "other results"
        assert [p["column"] for p in res["parameters"]] == ["product_yield_pct", "rate_per_hr"]   # repeat dropped
        assert r.dropped == ["reaction_temperature_C (stage results)"]
        columns = json.loads((folder / "columns.json").read_text())["all_columns"]
        assert columns == ["set_type", "duration_hr", "reaction_temperature_C", "pH", "reactor", "product_yield_pct",
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
