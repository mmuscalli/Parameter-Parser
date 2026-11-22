"""Accuracy evaluation, Phase 1 follow-up (Mickey, 2026-11-20): a drafted pack written again from the surveys and the
design its draft saved, with the current app -- after the fix that keeps an astronomy pack's units its own
(conventions.unit_system). Nothing is asked: the same design, so the difference is the fix alone. The pack as it was
is moved to `<work folder>/pack_before_<date>` first.

Usage: PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 python redraft_from_saved.py WORK_FOLDER PACK_ID "LABEL" "DESCRIPTION"
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from parameter_extractor import pack_modules, packs  # noqa: E402
from parameter_extractor.pack_drafting import (DraftResult, PackProposal, PaperSurvey, SurveyedPaper,  # noqa: E402
                                               _write_surveys, write_pack, write_report)
from parameter_extractor.pack_editing import PackDraft, check  # noqa: E402


def _keep_compounds(before, folder: Path) -> None:
    """The compound vocabulary the draft's compound setup made (a model request write_pack doesn't repeat): its species
    names, their dataset columns and species_cids.json carried into the pack written again (2026-11-22: without them
    every compound value of the rewritten P1 pack was held for review)."""
    import re
    if before is None or not (before / "columns.json").is_file():
        return
    o, n = (json.loads((p / "columns.json").read_text()) for p in (before, folder))
    compound = re.compile(r"^(initial|sampled|stock|calculated)_.+_(aq|gas|solid)_")
    n["all_columns"] += [c for c in o.get("all_columns", []) if compound.search(c) and c not in n["all_columns"]]
    n["species_names"] = o.get("species_names", [])
    (folder / "columns.json").write_text(json.dumps(n, indent=2))
    if (before / "species_cids.json").is_file():
        shutil.copy(before / "species_cids.json", folder / "species_cids.json")


def main(work: Path, pack_id: str, label: str, description: str) -> None:
    saved = json.loads((work / "pack_synthesis.output.json").read_text())
    proposal = PackProposal.model_validate(saved.get("answer", saved))
    papers = [SurveyedPaper(item=s["item"], name=s["paper"], error=s.get("error", ""),
                            survey=PaperSurvey.model_validate(s["survey"]) if s.get("survey") else None)
              for s in json.loads((work / "surveys.json").read_text())]
    good = [p for p in papers if p.survey and p.survey.variables]
    evidence = pack_modules.evidence_for(good)
    old = packs.user_packs_dir() / pack_id
    if old.is_dir():
        shutil.move(str(old), str(work / f"pack_before_{datetime.now():%Y%m%d-%H%M%S}"))
    pack, dropped, by_column = write_pack(proposal, pack_id, label, description, tidy=True, modules=list(evidence),
                                          surveys=good)
    before = sorted(work.glob("pack_before_*"))
    _keep_compounds(before[-1] if before else None, pack.folder)
    tidied = by_column.pop("__tidied__", [])
    left = by_column.pop("__left_to_modules__", [])
    result = DraftResult(pack=packs.Pack(pack.folder), proposal=proposal, papers=papers,
                         problems=check(PackDraft.load(pack.folder)), work_dir=work, cost_usd=0.0, dropped=dropped,
                         tidied=tidied, module_evidence=evidence, left_to_modules=left)
    text = write_report(result, by_column, label) + (
        "\n\nWritten again on " + f"{datetime.now():%Y-%m-%d %H:%M} from the saved surveys and design (nothing asked), "
        "after the fix that keeps an astronomy pack's units its own.\n")
    (pack.folder / "drafted_from.md").write_text(text)
    _write_surveys(pack.folder, papers)
    m = json.loads((pack.folder / "pack.json").read_text())
    print(f"{pack_id}: unit_system {m.get('unit_system', 'lab')}, modules {m.get('modules')}")
    for f in sorted((pack.folder / "stages").glob("*.json")):
        spec = json.loads(f.read_text())
        print(" ", spec["name"], [(p["column"], p.get("unit", "")) for p in spec["parameters"]])
    for p in result.problems:
        print("  check:", p.level, p.where, p.message)


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4])
