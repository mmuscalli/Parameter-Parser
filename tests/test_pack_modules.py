"""
Shared modules for data packs (pack_modules.py, 2026-11-09): technique detection in paper surveys, the analysis module
(step + vocabulary copy + hints + category) and the solution-chemistry module (step + calculations + the parameters
they need), drafting adding the analysis module when the surveys name techniques, and --add-module refusing the
app's own packs. No API, no network.
"""
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
    from parameter_extractor.pack_editing import PackDraft, check
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        draft = PackDraft.load(pack.folder)
        draft.stages[next(iter(draft.stages))]["open_ended"] = True
        lines = pack_modules.add_analysis(draft)
        draft.save()
        assert any("analysis step switched on" in l for l in lines) and any("vocabulary copied" in l for l in lines)
        d = PackDraft.load(pack.folder)
        assert "analysis" in d.manifest["builtin_stages"] and d.analysis_vocab["techniques"]
        assert all("analysis" in s.get("hint_by_stage", {}) for s in d.stages.values() if s.get("open_ended"))
        assert any(c["id"] == "analysis" for c in d.manifest["variable_categories"])
        assert not [p for p in check(d) if p.level == "error"], check(d)
        assert pack_modules.add_analysis(d) == []                         # already there: nothing to do
        # the step's prompt reads the pack's own vocabulary
        packs.activate("modules_test")
        from parameter_extractor.stages import analysis
        assert "RP-HPLC" in analysis.prompt_text("P", "PLAN")
        packs.activate("prebiotic_chemistry")


def test_solution_chemistry_module():
    from parameter_extractor.pack_editing import PackDraft, check
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp) / "packs"):
        pack = _new_pack(Path(tmp))
        lines = pack_modules.add_module(pack.folder, "solution_chemistry")
        d = PackDraft.load(pack.folder)
        assert "chemistry" in d.manifest["builtin_stages"]
        assert all(c in d.manifest["postprocess"] for c in ("amounts", "mixing", "water_type"))
        cols = [p["column"] for s in d.stages.values() for p in s["parameters"]]
        assert "solvent_volume_mL" in cols and "solvent_name" in cols
        assert (pack.folder / "prompts" / "chemistry.md").is_file() and any("prompt copied" in l for l in lines)
        assert not [p for p in check(d) if p.level == "error"], check(d)
        assert pack_modules.add_module(pack.folder, "solution_chemistry") == ["Solution chemistry: already in the pack"]
        try:
            pack_modules.add_module(packs.BUILTIN_DIR / "exoplanets", "analysis")
            raise AssertionError("an app pack was changed")
        except ValueError:
            pass


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
        assert "analysis" in manifest["builtin_stages"] and (r.pack.folder / "analysis_vocab.json").is_file()
        assert r.module_evidence["analysis"] == {"eder1994": ["RP-HPLC"], "kim2019": ["RP-HPLC"]}
        assert "## Shared modules added" in (r.pack.folder / "drafted_from.md").read_text()
        r2 = pack_drafting.draft_pack([EDER], "without_modules", "Without", "", cfg, modules_on=False)
        assert "analysis" not in json.loads((r2.pack.folder / "pack.json").read_text()).get("builtin_stages", [])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
