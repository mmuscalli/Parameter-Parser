"""
Modules drafted from sample papers (module_drafting.py, 2026-11-09): the checks on a proposal (conventions, existing
modules' columns left out, core conditions -> pack_parameters, unit talk out of descriptions, evidence words that fit the
papers, overlap between proposals, too-small modules dropped, additions to existing modules), writing a module and
drafting linking it, step triggers needing several keyword mentions, the app's new modules. No API calls.
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

from parameter_extractor import module_drafting as md, modules, pack_modules  # noqa: E402
from parameter_extractor.pack_drafting import (PaperSurvey, ProposedCategory, ProposedParameter,  # noqa: E402
                                               ProposedStage, SurveyedPaper, SurveyVariable)


def _paper(name, notes, columns=()):
    vars_ = [SurveyVariable(name=c, column=c, unit="", kind="number", role="condition", description=c, level="set",
                            uncertainty=False, where="table", example="1") for c in columns]
    return SurveyedPaper(item=name, name=name, survey=PaperSurvey(field="x", row_unit="r", set_unit="s", notes=notes,
                                                                  variables=vars_, compounds=[]))


def _param(column, unit="", kind="number", desc=""):
    return ProposedParameter(column=column, unit=unit, kind=kind, description=desc or column, category="c",
                             choices=[], uncertainties=False, papers=2)


def _module(mid, label, params, words, papers, extends=""):
    return md.ProposedModule(
        id=mid, label=label, description=f"{label}.", covers=f"{label} values.", evidence_words=words, papers=papers,
        step=ProposedStage(name=mid, label=label, description=f"{label} values.", per="sample", keywords=[],
                           parameters=params, rules=[], other_hint=""),
        category=ProposedCategory(id=mid, label=label, description="d", value_type="number"), row_rules=[],
        extends=extends)


PAPERS = [_paper("clayA", "montmorillonite catalysis with homoionic clays; flow rate 1 mL/min"),
          _paper("clayB", "Na-montmorillonite, exchangeable cation Cu; flow rate"),
          _paper("shock", "light-gas gun shots at 5 km/s; flow rate of gas"),
          _paper("other1", "solution chemistry at 80 C; flow rate"),
          _paper("other2", "dry-down of nucleotides"),
          _paper("other3", "gas flow rate over a heated plate")]


def test_checks():
    proposal = md.ModuleProposal(notes="", modules=[
        _module("clay_surfaces", "Clay surfaces", [
            _param("exchangeable_cation", kind="text"), _param("particle_size", "µm", desc="Particle size, in µm."),
            _param("pretreatment", kind="text", desc="Treatment of the clay, converted to mg."),
            _param("solid_material_name", kind="text"), _param("half_life", "h")],
            ["montmorillonite", "homoionic", "flow rate"], ["clayA", "clayB"]),
        _module("tiny", "Tiny", [_param("pretreatment", kind="text"), _param("thing_a", "%")], ["light-gas gun"],
                ["shock"]),
        _module("linkage", "Linkage", [_param("linkage_2_5", "%"), _param("linkage_3_5", "%"),
                                       _param("linkage_method", kind="text")], ["2'-5' linkage"], ["clayA"],
                extends="product_totals")])
    checked, left = md.check_proposals(proposal, PAPERS)
    by = {c.id: c for c in checked}
    clay = by["clay_surfaces"]
    cols = [p["column"] for p in clay.parameters]
    assert "half_life_hr" not in cols                                    # the Kinetics module records it
    assert [p["column"] for p in clay.pack_parameters] == ["solid_material_name"]       # core condition
    assert "particle_size_um" in cols and all("in µm" not in p["description"] for p in clay.parameters)
    assert all("converted" not in p["description"] for p in clay.parameters)
    assert "flow rate" not in clay.evidence and set(clay.papers_with_evidence) == {"clayA", "clayB"}
    assert any("mostly hit other papers" in n for n in clay.notes)
    assert "tiny" not in by and any("Tiny" in x and "fewer than" in x for x in left)    # pretreatment taken + 1 left
    assert by["linkage"].extends == "peptides_oligomers"                 # renamed id resolved
    with tempfile.TemporaryDirectory() as tmp:
        assert md.write_module(by["linkage"], Path(tmp)) is None         # an addition to an app module: not written
        folder = md.write_module(clay, Path(tmp))
        man = json.loads((folder / "module.json").read_text())
        spec = json.loads((folder / "stages" / "clay_surfaces.json").read_text())
        assert man["evidence"]["words"] == clay.evidence and man["pack_parameters"][0]["column"] == "solid_material_name"
        assert spec["trigger"] == {"keywords": clay.evidence, "min_hits": md.MIN_TRIGGER_HITS}
        # drafting links it from papers using its words
        with patch.object(modules, "_extra_dirs", [Path(tmp)]):
            modules.clear_cache()
            assert "clay_surfaces" in modules.available()
            assert set(pack_modules.evidence_for(PAPERS).get("clay_surfaces", {})) == {"clayA", "clayB"}
        modules.clear_cache()


def test_min_hits_trigger():
    from parameter_extractor.stages.optional import StageSpec
    from parameter_extractor.schemas.structure_plan import StructurePlan
    spec = StageSpec(name="x", label="X", intro="i", parameters=[],
                     trigger={"keywords": ["montmorillonite"], "min_hits": 3})
    plan = StructurePlan(paper_id="p", experiment_sets=[], n_rows=0, excluded_data=[])
    once = "Unlike montmorillonite catalysis, we used a flow reactor."
    many = "Montmorillonite K10 ... the montmorillonite was washed ... homoionic montmorillonites"
    refs = "We heated it.\nReferences\nFerris, montmorillonite; montmorillonite; montmorillonite"
    assert not spec.triggered(plan, once) and spec.triggered(plan, many) and not spec.triggered(plan, refs)
    assert not spec.could_trigger(once) and spec.could_trigger(many)
    one = StageSpec(name="y", label="Y", intro="i", parameters=[], trigger={"keywords": ["half-life"]})
    assert one.triggered(plan, "a half-life of 3 h")                     # default: one mention, as before


def test_new_app_modules():
    modules.clear_cache()
    found = modules.available()
    for mid in ("mineral_surfaces", "impact_shock", "heat_flow_chamber", "flow_reactor", "fluid_inclusions"):
        mod = found[mid]
        assert mod.manifest.covers and mod.manifest.evidence["words"] and len(mod.stage_files()) == 1
        spec = json.loads(mod.stage_files()[0].read_text())
        assert spec["trigger"]["min_hits"] == 3 and len(spec["parameters"]) >= 3
    assert any(p.name == "oligomer_linkage.json" for p in found["peptides_oligomers"].stage_files())
    # no two modules fill the same column
    from parameter_extractor.pack_drafting import _module_own_columns
    seen = {}
    for mid, mod in found.items():
        for c in _module_own_columns(mod):
            assert c not in seen or seen[c] == mid, (c, seen.get(c), mid)
            seen[c] = mid
    # the evidence for new modules comes from their words
    papers = [SimpleNamespace(name="a", survey=_paper("a", "a hydrothermal flow reactor with a back-pressure "
                                                          "regulator").survey)]
    assert "flow_reactor" in pack_modules.evidence_for(papers)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
