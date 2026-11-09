"""
Shared modules for data packs (Mickey, 2026-11-09 -- step 2 after the organics held-out test): parts that were built
and refined for one pack, which any pack can take whole instead of re-inventing them. A drafted pack captured every
value of its field but recorded analysis methods as one text column, where the prebiotic pack's analysis step records
each instrument setting, and it had no amount / mixing / water handling until compound setup added it.

Two modules, each with what it switches on, how to tell that sample papers need it, and one function to add it:

- **analysis** -- the built-in analysis step (stages/analysis.py) with the pack's own copy of the analysis vocabulary
  (techniques and instrument settings, analysis_vocab.json; copied from the prebiotic pack, editable in the pack
  editor). Needed when the sample papers name analytical techniques (`techniques_named`). The pack's open-ended stages
  are told not to repeat instrument settings while the step runs (`hint_by_stage`, as in the prebiotic pack).
- **solution_chemistry** -- the chemistry step (compounds and their concentrations / yields) with its calculations:
  normalize_species, mixing (stock -> mixture), molar_ratios, amounts (mmol -> mM with the reaction volume) and
  water_type, plus the parameters those need (solvent_volume_mL, solvent_name) and the chemistry prompt. Added by
  compound setup (compound_setup.apply) when it finds compounds; also usable on its own.

`draft_pack` adds the analysis module when the surveys call for it; the report lists what each module added.
"""
from __future__ import annotations
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from parameter_extractor import packs

SOURCE_PACK = "prebiotic_chemistry"          # where the modules' curated parts come from

# ---- analysis -----------------------------------------------------------------------------------------------------------

ANALYSIS_HINT = {"runs": "not analytical techniques or instrument settings (column, mobile phase, wavelength, matrix, "
                         "laser, voltages, standards, detection limits): a separate step records them",
                 "off": "analysis details beyond the analysis method DO belong here (instrument, column, mobile phase, "
                        "detection wavelength, standards, detection limit): one entry each"}


def _source_vocab_path() -> Path:
    return packs.BUILTIN_DIR / SOURCE_PACK / "analysis_vocab.json"


def _technique_patterns() -> List[tuple]:
    """(technique, compiled pattern) for every name and alias of the source vocabulary. Short all-capital names
    ('LC', 'MS', 'NMR') match case-sensitively as whole words, longer names case-insensitively."""
    raw = json.loads(_source_vocab_path().read_text())
    out = []
    for t in raw.get("techniques", []):
        for name in [t["name"]] + list(t.get("aliases", [])):
            name = name.strip()
            if len(name) < 2:
                continue
            body = re.escape(name).replace(r"\-", r"[-\s/]?").replace(r"\ ", r"[-\s]+")
            acronym = name.replace("-", "").replace("/", "").isupper() and len(name) <= 8
            flags = 0 if acronym else re.IGNORECASE
            out.append((t["name"], re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", flags)))
    return out


def techniques_named(texts: Iterable[str]) -> List[str]:
    """The vocabulary techniques the texts name, most specific first-found ('GC-MS', 'UHPLC/MSMS' -> UHPLC, LC-MS;
    'Raman spectroscopy' -> Raman). A technique whose every match lies inside a longer one's ('HPLC' in 'RP-HPLC',
    'MS' in 'GC-MS') isn't listed; 'GC-MS and direct MS' gives both."""
    patterns = _technique_patterns()
    found: Dict[str, None] = {}
    for text in texts:
        if not text:
            continue
        spans = [(m.start(), m.end(), name) for name, pattern in patterns for m in pattern.finditer(text)]
        for a0, a1, name in spans:
            inside = any(b0 <= a0 and a1 <= b1 and (b1 - b0) > (a1 - a0) and other != name for b0, b1, other in spans)
            if not inside:
                found.setdefault(name, None)
    return list(found)


def _survey_texts(survey) -> List[str]:
    """The parts of a paper survey that describe how things were measured."""
    texts = []
    for v in getattr(survey, "variables", []) or []:
        method_like = v.role == "method" or re.search(r"analy|detect|measur|instrument|spectr|chromatog|technique",
                                                       f"{v.name} {v.column}", re.IGNORECASE)
        if method_like:
            texts += [v.name, v.description, v.example]
    texts.append(getattr(survey, "notes", "") or "")
    return texts


def analysis_evidence(papers) -> Dict[str, List[str]]:
    """{paper: techniques named in its survey} for the papers that name any (SurveyedPaper list)."""
    out = {}
    for p in papers:
        if getattr(p, "survey", None) is None:
            continue
        named = techniques_named(_survey_texts(p.survey))
        if named:
            out[p.name] = named
    return out


def has_analysis(draft) -> bool:
    return "analysis" in draft.manifest.get("builtin_stages", [])


def add_analysis(draft) -> List[str]:
    """Switch the analysis step on with a copy of the analysis vocabulary (kept when the pack has its own); tell the
    open-ended stages to leave instrument settings to it. Lines saying what was done (empty when it was on)."""
    if has_analysis(draft) and draft.analysis_vocab is not None:
        return []
    m = draft.manifest
    m["builtin_stages"] = list(dict.fromkeys(list(m.get("builtin_stages", [])) + ["analysis"]))
    done = ["analysis step switched on (each technique's instrument settings in analysis_<technique>_<setting> "
            "columns)"]
    if draft.analysis_vocab is None:
        draft.analysis_vocab = json.loads(_source_vocab_path().read_text())
        done.append(f"analysis vocabulary copied from the prebiotic chemistry pack "
                    f"({len(draft.analysis_vocab.get('techniques', []))} techniques; edit it under Analysis methods)")
    told = 0
    for spec in draft.stages.values():
        if spec.get("open_ended") and "analysis" not in (spec.get("hint_by_stage") or {}):
            spec.setdefault("hint_by_stage", {})["analysis"] = dict(ANALYSIS_HINT)
            told += 1
    if told:
        done.append(f"{told} stage(s) told to leave instrument settings to the analysis step")
    cats = m.setdefault("variable_categories", [])
    if not any(c.get("id") == "analysis" for c in cats):
        top = max([c.get("table_order", 0) for c in cats] + [30])
        cats.append({"id": "analysis", "table_order": top + 5, "label": "Analysis", "value_type": "any",
                     "max_words": 10, "model_assigns": True,
                     "description": "how the products were analysed: technique, instrument and its settings"})
        m.setdefault("category_columns", {}).setdefault("analysis", {"columns": []}).setdefault(
            "patterns", []).append(r"^analysis_")
        done.append("category Analysis added (analysis_* columns)")
    return done


# ---- solution chemistry --------------------------------------------------------------------------------------------------

CHEMISTRY_POSTPROCESS = ["normalize_species", "mixing", "molar_ratios", "amounts", "water_type"]
CHEMISTRY_RULE = ("Dissolved compounds and their concentrations or yields are recorded by the chemistry step -- don't "
                  "list them here.")
# amounts ('0.20 mmol') become concentrations only with the reaction volume (calculators/amounts.py); water_type needs
# the solvent (calculators/water.py)
CHEMISTRY_PARAMETERS = [
    {"column": "solvent_volume_mL", "unit": "mL", "description": (
        "total volume of the reaction solution (liquid) the compounds were in: as stated, or -- when the paper gives "
        "only the volumes of the solutions combined -- their sum, with b 'derived' and the parts in `n`.")},
    {"column": "solvent_name", "kind": "text", "description": (
        "the solvent. For water, the type exactly as stated: distilled, deionized (DI), Milli-Q, ultrapure, nanopure, "
        "tap -- just 'water' if the paper doesn't say.")}]


def has_solution_chemistry(draft) -> bool:
    return "chemistry" in draft.manifest.get("builtin_stages", [])


def add_solution_chemistry(draft) -> List[str]:
    """Switch the chemistry step and its calculations on, add the parameters they need to the first always-on stage
    and the chemistry rule to every stage. Lines saying what was done. (The prompt file: ensure_chemistry_prompt, after
    the draft is saved.)"""
    m = draft.manifest
    done = []
    if not has_solution_chemistry(draft):
        m["builtin_stages"] = list(dict.fromkeys(list(m.get("builtin_stages", [])) + ["chemistry"]))
        done.append("chemistry step switched on")
    missing = [c for c in CHEMISTRY_POSTPROCESS if c not in m.get("postprocess", [])]
    if missing:
        m["postprocess"] = list(dict.fromkeys(list(m.get("postprocess", [])) + CHEMISTRY_POSTPROCESS))
        done.append("calculations switched on: " + ", ".join(missing))
    present = {q.get("column") for sp in draft.stages.values() for q in sp.get("parameters", [])}
    always = [sp for sp in draft.stages.values() if (sp.get("trigger") or {}).get("always")]
    for param in CHEMISTRY_PARAMETERS:
        if param["column"] in present or not always:
            continue
        always[0].setdefault("parameters", []).append(dict(param))
        if param["column"] not in draft.columns:
            draft.columns = draft.columns + [param["column"]]
        done.append(f"stage '{always[0].get('name')}': {param['column']} added"
                    + (" -- amounts in mmol become concentrations with it" if param["column"] == "solvent_volume_mL"
                       else " -- the water type is normalised"))
    for spec in draft.stages.values():
        if CHEMISTRY_RULE not in spec.get("rules", []):
            spec.setdefault("rules", []).append(CHEMISTRY_RULE)
    return done


def ensure_chemistry_prompt(folder: Path) -> bool:
    """The chemistry step's prompt in the pack (copied from the prebiotic pack: the app has no generic one)."""
    own = Path(folder) / "prompts" / "chemistry.md"
    if own.is_file():
        return False
    from parameter_extractor.config import settings
    if (settings.PROMPTS_DIR / "chemistry.md").is_file():
        return False
    own.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(packs.BUILTIN_DIR / SOURCE_PACK / "prompts" / "chemistry.md", own)
    return True


# ---- the list ---------------------------------------------------------------------------------------------------------

@dataclass
class Module:
    id: str
    label: str
    description: str
    present: object                       # draft -> bool
    add: object                           # draft -> lines


MODULES = {
    "analysis": Module("analysis", "Analysis methods",
                       "the analysis step: every analytical technique and its instrument settings, named from a "
                       "vocabulary of techniques", has_analysis, add_analysis),
    "solution_chemistry": Module("solution_chemistry", "Solution chemistry",
                                 "the chemistry step: compounds with their concentrations and yields, stock solutions, "
                                 "ratios, amounts per volume and the water type", has_solution_chemistry,
                                 add_solution_chemistry),
}


def add_module(folder: Path, module_id: str) -> List[str]:
    """Add one module to a user's pack on disk (the CLI's --add-module); lines done. Refuses the app's own packs."""
    from parameter_extractor.pack_editing import PackDraft
    draft = PackDraft.load(Path(folder))
    if draft.builtin:
        raise ValueError("The app's own data packs can't be changed -- copy it first.")
    if module_id not in MODULES:
        raise ValueError(f"Unknown module '{module_id}'. Modules: {', '.join(MODULES)}")
    done = MODULES[module_id].add(draft)
    draft.save()
    if module_id == "solution_chemistry" and ensure_chemistry_prompt(Path(folder)):
        done.append("chemistry prompt copied from the prebiotic chemistry pack (prompts/chemistry.md)")
    return done or [f"{MODULES[module_id].label}: already in the pack"]
