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


# ---- stages shared as files: kinetics, wet-dry cycling --------------------------------------------------------------

def _source_spec(name: str) -> dict:
    return json.loads((packs.BUILTIN_DIR / SOURCE_PACK / "stages" / f"{name}.json").read_text())


def _has_stage(draft, name: str) -> bool:
    return any(spec.get("name") == name for spec in draft.stages.values())


def _add_category(draft, cid: str, label: str, description: str, patterns: List[str], order: int,
                  value_type: str = "number", model_assigns: bool = True) -> Optional[str]:
    cats = draft.manifest.setdefault("variable_categories", [])
    if any(c.get("id") == cid for c in cats):
        return None
    cats.append({"id": cid, "table_order": order, "label": label, "value_type": value_type,
                 "model_assigns": model_assigns, "description": description})
    entry = draft.manifest.setdefault("category_columns", {}).setdefault(cid, {"columns": []})
    entry.setdefault("patterns", []).extend(p for p in patterns if p not in entry.get("patterns", []))
    return f"category {label} added"


def _add_stage(draft, name: str) -> List[str]:
    """A copy of the source pack's stage file; its columns added to the pack's list."""
    if _has_stage(draft, name):
        return []
    spec = _source_spec(name)
    file = f"{name}.json"
    while file in draft.stages:
        file = "module_" + file
    draft.stages[file] = spec
    new_cols = [q["column"] for q in spec.get("parameters", []) if q["column"] not in draft.columns]
    draft.columns = list(draft.columns) + new_cols
    trigger = spec.get("trigger") or {}
    when = ("always" if trigger.get("always") else
            "for papers mentioning: " + ", ".join(trigger.get("keywords", [])[:5]) + " ..." if trigger.get("keywords")
            else "for wet-dry cycling experiments" if trigger.get("set_types") or trigger.get("set_patterns") else "")
    return [f"stage '{spec.get('label', name)}' added ({len(spec.get('parameters', []))} parameters; runs {when})"]


def _rules(draft, lines: List[str]) -> List[str]:
    from parameter_extractor.pack_editing import items_to_rules, rules_to_items
    items = rules_to_items(draft.rules.get("structure_planner", "") or "")
    added = [l for l in lines if l not in items]
    if added:
        draft.rules["structure_planner"] = items_to_rules(items + added)
    return [f"row rule added: {l[:70]}..." for l in added]


KINETICS_WORDS = ["rate constant", "half-life", "half life", "activation energy", "arrhenius", "first-order",
                  "second-order", "kinetic", "k_obs", "kobs", "rate coefficient", "decay rate", "degradation rate"]


def _texts(survey) -> List[str]:
    """Every variable's words in a survey (names, columns, descriptions, examples) and its notes."""
    out = [getattr(survey, "notes", "") or "", getattr(survey, "field", "") or ""]
    for v in getattr(survey, "variables", []) or []:
        out += [v.name, v.column, v.description, v.example]
    return out


def _papers_saying(papers, pattern: str) -> Dict[str, List[str]]:
    rx = re.compile(pattern, re.IGNORECASE)
    out = {}
    for p in papers:
        if getattr(p, "survey", None) is None:
            continue
        hits = sorted({m.group(0).lower() for t in _texts(p.survey) for m in rx.finditer(t or "")})
        if hits:
            out[p.name] = hits
    return out


def kinetics_evidence(papers) -> Dict[str, List[str]]:
    return _papers_saying(papers, r"\b(?:" + "|".join(re.escape(w) for w in KINETICS_WORDS) + r")s?\b")


def has_kinetics(draft) -> bool:
    return _has_stage(draft, "kinetics")


def add_kinetics(draft) -> List[str]:
    """The kinetics stage (rate constants, half-lives, activation energies; keyword-triggered) + its category."""
    done = _add_stage(draft, "kinetics")
    if done:
        cat = next(c for c in json.loads((packs.BUILTIN_DIR / SOURCE_PACK / "pack.json").read_text())
                   ["variable_categories"] if c["id"] == "kinetics")
        line = _add_category(draft, "kinetics", cat["label"], cat["description"], cat.get("patterns", []), 74)
        done += [line] if line else []
    return done


WET_DRY_PATTERN = r"\b(?:wet|dry)\s*[-–−/]\s*(?:dry|wet)\b|dehydration[-–− ]rehydration|evaporation cycl|drying cycl|hydration cycl"
WET_DRY_RULES = [
    "Wet-dry cycling experiments: one row per cycle sampled, in a set of type \"Evaporation Cycle\"; name each row by "
    "its cycle ('Cycle 3').",
    "For wet-dry cycles the duration (`hr`) is the TOTAL time up to the end of that cycle: 24 h cycles -> Cycle 1 = "
    "24, Cycle 2 = 48, Cycle 3 = 72 (cycles of different lengths add up)."]


def wet_dry_evidence(papers) -> Dict[str, List[str]]:
    return _papers_saying(papers, WET_DRY_PATTERN)


def has_wet_dry(draft) -> bool:
    return _has_stage(draft, "wet_dry")


def add_wet_dry(draft) -> List[str]:
    """The wet-dry cycling stage (cycle number, durations, phase temperatures, humidity), its category and the row
    rules for cycles."""
    done = _add_stage(draft, "wet_dry")
    if done:
        line = _add_category(draft, "wet_dry", "Wet-Dry Cycling",
                             "the cycles of wet-dry experiments: cycle number and length, wet and dry phase "
                             "temperatures, durations and humidity", [r"^cycle_", r"^wet_phase", r"^dry_phase"], 35)
        done += ([line] if line else []) + _rules(draft, WET_DRY_RULES)
    return done


# ---- product totals: peptides and oligomers -------------------------------------------------------------------------

TOTALS_POSTPROCESS = ["peptide_totals", "oligomer_totals"]
TOTALS_COLUMNS = [
    {"column": "total_sampled_peptides_yield", "description": "Total yield (%) of peptides (dimers and longer, linear "
     "and cyclic): stated by the paper, else the sum of the row's peptide % yields (calculated)."},
    {"column": "total_sampled_oligomers_yield", "description": "Total yield (%) of nucleic-acid oligomers (2-mers and "
     "longer): stated by the paper, else the sum of the row's oligomer % yields (calculated)."},
    {"column": "max_oligomer_length_nt", "description": "Longest nucleic-acid oligomer with a value in the row (nt): "
     "stated by the paper, else from the row's oligomer columns (calculated)."}]
TOTALS_PATTERN = (r"\bpeptides?\b|\boligo(?:mer|nucleotide|peptide)s?\b|\b(?:di|tri|tetra|penta)(?:glycine|peptides?|mers?)\b|"
                  r"\bdiketopiperazines?\b|\b\d+-?mers?\b|\bpoly\([A-Za-z]+\)")


def totals_evidence(papers) -> Dict[str, List[str]]:
    out = _papers_saying(papers, TOTALS_PATTERN)
    rx = re.compile(TOTALS_PATTERN, re.IGNORECASE)
    from parameter_extractor.names import oligonucleotide_match, peptide_codes
    for p in papers:
        for c in (getattr(p.survey, "compounds", []) if getattr(p, "survey", None) else []):
            if c.role == "product" and (rx.search(f"{c.name} {c.full_name}") or peptide_codes(c.name)
                                        or oligonucleotide_match(c.name)):
                out.setdefault(p.name, []).append(c.name)
    return out


def has_totals(draft) -> bool:
    return all(c in draft.manifest.get("postprocess", []) for c in TOTALS_POSTPROCESS)


def add_totals(draft) -> List[str]:
    """Peptide and oligomer totals and the longest oligomer, calculated locally from the compound columns (needs the
    chemistry step -- switched on too)."""
    if has_totals(draft):
        return []
    done = add_solution_chemistry(draft)
    m = draft.manifest
    m["postprocess"] = list(dict.fromkeys(list(m.get("postprocess", [])) + TOTALS_POSTPROCESS))
    done.append("calculations switched on: " + ", ".join(TOTALS_POSTPROCESS))
    std = draft.standard_file.setdefault("columns", [])
    have = {e["column"] for e in std} | set(draft.columns)
    for entry in TOTALS_COLUMNS:
        if entry["column"] not in have:
            std.append(dict(entry))
            done.append(f"column {entry['column']} added")
    if not m.get("standard_columns"):
        m["standard_columns"] = "standard_columns.json"
    cc = m.setdefault("category_columns", {})
    if "products" in cc and "max_oligomer_length_nt" not in cc["products"].get("columns", []):
        cc["products"].setdefault("columns", []).append("max_oligomer_length_nt")
    return done


# ---- the list ---------------------------------------------------------------------------------------------------------

@dataclass
class Module:
    id: str
    label: str
    description: str
    present: object                       # draft -> bool
    add: object                           # draft -> lines
    evidence: object = None               # papers -> {paper: why}; None = not added by drafting on its own
    needs: tuple = ()                     # modules it switches on too


MODULES = {
    "analysis": Module("analysis", "Analysis methods",
                       "the analysis step: every analytical technique and its instrument settings, named from a "
                       "vocabulary of techniques", has_analysis, add_analysis, analysis_evidence),
    "solution_chemistry": Module("solution_chemistry", "Solution chemistry",
                                 "the chemistry step: compounds with their concentrations and yields, stock solutions, "
                                 "ratios, amounts per volume and the water type", has_solution_chemistry,
                                 add_solution_chemistry),
    "kinetics": Module("kinetics", "Kinetics",
                       "rate constants, half-lives and activation energies (runs only for papers that mention them)",
                       has_kinetics, add_kinetics, kinetics_evidence),
    "wet_dry": Module("wet_dry", "Wet-dry cycling",
                      "cycle number and length, wet and dry phase temperatures, durations and humidity; rows per cycle "
                      "with cumulative times (runs only for wet-dry experiments)", has_wet_dry, add_wet_dry,
                      wet_dry_evidence),
    "product_totals": Module("product_totals", "Peptide and oligomer totals",
                             "total peptide and oligomer yields and the longest oligomer, calculated from the compound "
                             "columns (switches the chemistry step on)", has_totals, add_totals, totals_evidence,
                             needs=("solution_chemistry",)),
}


def evidence_for(papers) -> Dict[str, Dict[str, List[str]]]:
    """{module: {paper: why}} for the modules whose evidence the sample papers show."""
    out = {}
    for mid, module in MODULES.items():
        if module.evidence is not None:
            found = module.evidence(papers)
            if found:
                out[mid] = found
    return out


def add_modules(folder: Path, module_ids: Iterable[str]) -> Dict[str, List[str]]:
    """Add modules to a user's pack on disk in one save; {module: lines done}. Refuses the app's own packs."""
    from parameter_extractor.pack_editing import PackDraft
    draft = PackDraft.load(Path(folder))
    if draft.builtin:
        raise ValueError("The app's own data packs can't be changed -- copy it first.")
    out = {}
    for mid in module_ids:
        if mid not in MODULES:
            raise ValueError(f"Unknown module '{mid}'. Modules: {', '.join(MODULES)}")
        out[mid] = MODULES[mid].add(draft)
    draft.save()
    if has_solution_chemistry(draft) and ensure_chemistry_prompt(Path(folder)):
        out.setdefault("solution_chemistry", []).append(
            "chemistry prompt copied from the prebiotic chemistry pack (prompts/chemistry.md)")
    return out


def add_module(folder: Path, module_id: str) -> List[str]:
    """One module (the CLI's --add-module); lines done."""
    done = add_modules(folder, [module_id]).get(module_id, [])
    return done or [f"{MODULES[module_id].label}: already in the pack"]
