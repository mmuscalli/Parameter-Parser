"""
Shared modules for data packs (Mickey, 2026-11-09): which modules a pack uses, how to tell that sample papers need one,
and adding / removing them. Since the reference-based design (same day) a module is NOT copied into a pack: the pack
lists it in pack.json ("modules") and packs.Pack links it in when the pack loads (parameter_extractor/modules/: the
module folders and their loader). An improvement to a module reaches every pack that uses it.

Modules (each a folder in parameter_extractor/modules/ with a module.json):
- analysis            the analysis step and its technique vocabulary
- solution_chemistry  the chemistry step, its calculations and the solvent parameters they need
- kinetics            rate constants, half-lives, activation energies (keyword-triggered stage)
- wet_dry             wet-dry cycling stage, its category and row rules
- peptides_oligomers      peptide / oligomer totals and the longest oligomer (needs solution_chemistry)

Evidence (for drafting): the surveys' words -- analytical techniques, kinetics words, wet-dry cycles, peptide and
oligomer products. `migrate_copies` turns a pack drafted before the reference design (copies of the vocabulary, the
chemistry prompt, stage files, rules, hints, categories) into one that links the modules.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from parameter_extractor import modules as module_store
from parameter_extractor import packs


def _source_vocab_path() -> Path:
    return module_store.BUILTIN_DIR / "analysis" / "analysis_vocab.json"


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


_SOLUTION_WORDS = re.compile(r"\b(?:solutions?|aqueous|dissolved|buffer(?:ed)?|stock|in water|molar|mM|µM|mol/L|mol L-1)\b",
                             re.IGNORECASE)


def solution_evidence(papers) -> Dict[str, List[str]]:
    """Papers whose surveys name compounds AND report concentrations or amounts of them in solution (a variable with
    a concentration or amount unit, and solution words in the survey) -> the Solution chemistry module."""
    from parameter_extractor.units import _UNITS, canonical_unit
    out = {}
    for p in papers:
        s = getattr(p, "survey", None)
        if s is None or not getattr(s, "compounds", None):
            continue
        amounts = [v for v in s.variables
                   if _UNITS.get(canonical_unit(v.unit or "") or "", ("",))[0] in ("concentration", "amount")]
        text = " ".join([s.notes or ""] + [f"{v.name} {v.description} {v.unit} {v.example}" for v in s.variables])
        if amounts and _SOLUTION_WORDS.search(text):
            out[p.name] = [f"{v.name} ({v.unit})" for v in amounts[:4]]
    return out


def kinetics_evidence(papers) -> Dict[str, List[str]]:
    return _papers_saying(papers, r"\b(?:" + "|".join(re.escape(w) for w in KINETICS_WORDS) + r")s?\b")



WET_DRY_PATTERN = r"\b(?:wet|dry)\s*[-–−/]\s*(?:dry|wet)\b|dehydration[-–− ]rehydration|evaporation cycl|drying cycl|hydration cycl"

def wet_dry_evidence(papers) -> Dict[str, List[str]]:
    return _papers_saying(papers, WET_DRY_PATTERN)



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




# ---- the modules a pack uses ------------------------------------------------------------------------------------------

@dataclass
class ModuleInfo:
    id: str
    label: str
    description: str
    evidence: object = None               # papers -> {paper: why}; None = drafting doesn't add it on its own


EVIDENCE = {"analysis": analysis_evidence, "solution_chemistry": solution_evidence, "kinetics": kinetics_evidence,
            "wet_dry": wet_dry_evidence,
            "peptides_oligomers": totals_evidence}


def modules_info() -> Dict[str, ModuleInfo]:
    return {mid: ModuleInfo(mid, m.label, m.manifest.description, EVIDENCE.get(mid))
            for mid, m in module_store.available().items()}


# (kept for callers of the copy-based version: the module ids and labels)
class _Lazy(dict):
    def __missing__(self, key):
        info = modules_info()
        if key not in info:
            raise KeyError(key)
        return info[key]

    def __iter__(self):
        return iter(modules_info())

    def items(self):
        return modules_info().items()

    def __contains__(self, key):
        return key in modules_info()

    def __len__(self):
        return len(modules_info())


MODULES = _Lazy()


def used(draft_or_manifest) -> List[str]:
    """The modules a pack uses, with the ones they bring along (resolved), from a PackDraft or a manifest dict."""
    manifest = getattr(draft_or_manifest, "manifest", draft_or_manifest)
    return [m.id for m in module_store.resolve(list(manifest.get("modules", [])))]


def evidence_for(papers) -> Dict[str, Dict[str, List[str]]]:
    """{module: {paper: why}} for the modules whose evidence the sample papers show: the app's own by their rules
    (EVIDENCE), any other module by the evidence words in its module.json (module_drafting)."""
    out = {}
    for mid, fn in EVIDENCE.items():
        found = fn(papers)
        if found and mid in module_store.available():
            out[mid] = found
    for mid, mod in module_store.available().items():
        words = (mod.manifest.evidence or {}).get("words") or []
        if mid in EVIDENCE or not words:
            continue
        pattern = r"(?<![a-z0-9])(?:" + "|".join(re.escape(w.lower()).replace(r"\ ", r"[\s_-]+") for w in words) \
            + r")s?(?![a-z0-9])"
        found = _papers_saying(papers, pattern)
        if found:
            out[mid] = found
    return out


# "What it brings" (Mickey, 2026-11-11: one format for every module): the same rows in the same order for every
# module, grouped; an empty list reads "none", a zero count "0". (group, label, kind: "list" | "count")
BRINGS_FIELDS = [
    ("Steps and calculations", "Uses other modules", "list"),
    ("Steps and calculations", "Built-in steps", "list"),
    ("Steps and calculations", "Configurable steps", "list"),
    ("Steps and calculations", "Calculations", "list"),
    ("Columns", "Columns added", "list"),
    ("Columns", "Added to the conditions step", "list"),
    ("Columns", "Column groups", "list"),
    ("Rules", "Row-planning rules", "count"),
    ("Rules", "Rules for the pack's own steps", "count"),
    ("Rules", "Rules for built-in steps", "count"),
    ("Rules", "Hints to other steps", "list"),
    ("Reference data", "Vocabulary", "list"),
    ("Reference data", "Instructions file", "list"),
    ("Reference data", "Compound list fill-in", "list"),
]
BRINGS_HELP = {
    "Uses other modules": "Modules linked along with this one.",
    "Built-in steps": "Steps that are part of the app: one model request per paper. View them on the Steps tab.",
    "Configurable steps": "The module's own steps: one model request each, for the papers they run for.",
    "Calculations": "Run on your computer after the model's answers: no model requests.",
    "Columns added": "Columns the module defines.",
    "Added to the conditions step": "Columns added to the data pack's conditions step (its first step that runs for "
                                    "every paper) when it doesn't have them.",
    "Column groups": "Categories the dataset's columns are grouped under.",
    "Row-planning rules": "Rules added to the instructions for planning a paper's rows.",
    "Rules for the pack's own steps": "Rules added to the instructions of the data pack's configurable steps.",
    "Rules for built-in steps": "Rules added to a built-in step's instructions.",
    "Hints to other steps": "What the data pack's other steps are told while one of this module's steps runs.",
    "Vocabulary": "Reference data the module's step works from.",
    "Instructions file": "A step's full instructions, kept with the module.",
    "Compound list fill-in": "What the module adds to a drafted data pack's compound list.",
}


def _runs_for(trig: dict) -> str:
    if trig.get("always"):
        return "every paper"
    words = trig.get("keywords") or []
    if words:
        shown = ", ".join(f"“{w}”" for w in words[:3]) + (", …" if len(words) > 3 else "")
        hits = trig.get("min_hits") or 1
        return f"papers mentioning {shown}" + (f" (at least {hits} times)" if hits > 1 else "")
    kinds = list(trig.get("set_types") or []) + list(trig.get("set_patterns") or [])
    return "experiments of these kinds: " + ", ".join(kinds[:3]) if kinds else "papers that call for it"


def brings(module_id: str) -> List[tuple]:
    """What a module brings: (group, label, value) for every field of BRINGS_FIELDS, in order; value is a list of
    strings or a count (int)."""
    from parameter_extractor.pack_editing import CALCULATIONS
    m = module_store.available()[module_id]
    mm = m.manifest
    found = module_store.available()
    steps = []
    for path in m.stage_files():
        spec = json.loads(path.read_text())
        cols = [prm["column"] for prm in spec.get("parameters", [])]
        # one item on three lines (brings_html indents the second and third)
        steps.append(f"{spec.get('label', spec['name'])}\nruns for {_runs_for(spec.get('trigger') or {})}\n"
                     f"fills {len(cols)} column{'s' if len(cols) != 1 else ''}: {', '.join(cols)}")
    vocab = []
    vocab_file = m.file("analysis_vocab.json")
    if vocab_file:
        data = json.loads(vocab_file.read_text())
        vocab.append(f"{len(data.get('techniques', []))} analytical techniques in {len(data.get('families', {}))} "
                     f"instrument families (analysis_vocab.json)")
    prompts_dir = m.folder / "prompts"
    instructions = [f"the {f.stem} step's instructions (prompts/{f.name})"
                    for f in sorted(prompts_dir.glob("*.md"))] if prompts_dir.is_dir() else []
    hints = [f"while the {step} step runs, the data pack's other steps leave its details out (and include them "
             f"when it is switched off)" for step in mm.stage_hints]
    built_in_rules = sum(len(r) for r in mm.prompt_rules.values())
    values = {
        "Uses other modules": [found[n].label for n in mm.needs if n in found],
        "Built-in steps": [f"{s} (part of the app)" for s in mm.builtin_stages],
        "Configurable steps": steps,
        "Calculations": [f"{c}: {CALCULATIONS[c][0]}" if c in CALCULATIONS else c for c in mm.postprocess],
        "Columns added": [e["column"] for e in mm.standard_columns],
        "Added to the conditions step": [prm["column"] for prm in mm.pack_parameters],
        "Column groups": [c["label"] for c in mm.variable_categories],
        "Row-planning rules": len(mm.row_rules),
        "Rules for the pack's own steps": len(mm.stage_rules),
        "Rules for built-in steps": built_in_rules,
        "Hints to other steps": hints,
        "Vocabulary": vocab,
        "Instructions file": instructions,
        "Compound list fill-in": (["every length of an oligomer series found in the sample papers"]
                                  if mm.compound_series else []),
    }
    out = []
    for group, label, _kind in BRINGS_FIELDS:
        value = values[label]
        if label == "Rules for built-in steps" and value:
            per_step = [(s, len(r)) for s, r in mm.prompt_rules.items() if r]
            value = (f"{value} (the {per_step[0][0]} step)" if len(per_step) == 1
                     else f"{value} (" + ", ".join(f"{n} for the {s} step" for s, n in per_step) + ")")
        out.append((group, label, value))
    return out


def brings_html(module_id: str) -> str:
    """The "What it brings" table: groups as headings, labels in one column, values in the next (each item on its
    own line); "none" / "0" for what the module doesn't bring."""
    from html import escape
    rows, last = [], None
    for group, label, value in brings(module_id):
        if group != last:
            top = "14" if last is not None else "2"
            rows.append(f"<tr><td colspan='2' style='padding-top:{top}px; font-weight:600'>{escape(group)}</td></tr>")
            last = group
        if isinstance(value, int) or (isinstance(value, str) and value[:1].isdigit()):
            shown = escape(str(value)) if value else "<span style='color:gray'>0</span>"
        elif not value:
            shown = "<span style='color:gray'>none</span>"
        else:
            def item(v: str) -> str:            # a step's details on indented lines under its name
                first, *more = v.split("\n")
                return escape(first) + "".join(f"<br><span style='color:gray'>&nbsp;&nbsp;&nbsp;&nbsp;{escape(x)}"
                                               f"</span>" for x in more)
            gap = "<div style='margin-top:6px'></div>" if any("\n" in v for v in value) else "<br>"
            shown = gap.join(item(v) for v in value)
        rows.append(f"<tr><td width='230' valign='top' style='padding:2px 14px 2px 14px'"
                    f" title='{escape(BRINGS_HELP.get(label, ''))}'>{escape(label)}</td>"
                    f"<td valign='top' style='padding:2px 0'>{shown}</td></tr>")
    return "<table cellspacing='0' cellpadding='0' width='100%'>" + "".join(rows) + "</table>"


def describe(module_id: str) -> List[str]:
    """What a module brings, one line per field it has something for ('label: value'), for text reports (the draft
    report, add_modules)."""
    out = []
    for _group, label, value in brings(module_id):
        if value:
            out.append(f"{label}: " + (str(value) if not isinstance(value, list)
                                       else "; ".join(v.replace("\n", ", ") for v in value)))
    return out


def add_to_manifest(manifest: dict, module_ids: Iterable[str]) -> List[str]:
    """Add module references to a pack.json dict; the ids newly added (unknown ids raise ValueError)."""
    found = module_store.available()
    have = list(manifest.get("modules", []))
    added = []
    for mid in module_ids:
        if mid not in found:
            raise ValueError(f"Unknown module '{mid}'. Modules: {', '.join(found)}")
        if mid not in have and mid not in used(manifest):
            have.append(mid)
            added.append(mid)
    manifest["modules"] = have
    return added


def add_modules(folder: Path, module_ids: Iterable[str]) -> Dict[str, List[str]]:
    """Link modules into a user's pack (pack.json "modules"; nothing copied); {module: lines}. Refuses the app's own."""
    from parameter_extractor.pack_editing import PackDraft
    draft = PackDraft.load(Path(folder))
    if draft.builtin:
        raise ValueError("The app's own data packs can't be changed -- copy it first.")
    module_ids = list(module_ids)
    added = add_to_manifest(draft.manifest, module_ids)
    draft.save()
    found = module_store.available()
    out = {mid: [] for mid in module_ids}
    for mid in added:
        out[mid] = [f"linked ({found[mid].label}): " + "; ".join(describe(mid))]
    return out


def add_module(folder: Path, module_id: str) -> List[str]:
    """One module (the CLI's --add-module); lines done."""
    done = add_modules(folder, [module_id]).get(module_id, [])
    return done or [f"{module_store.available()[module_id].label}: already in the pack"]


def remove_module(folder: Path, module_id: str) -> List[str]:
    """Unlink a module from a user's pack (modules that only it brought along go too)."""
    from parameter_extractor.pack_editing import PackDraft
    draft = PackDraft.load(Path(folder))
    if draft.builtin:
        raise ValueError("The app's own data packs can't be changed -- copy it first.")
    have = list(draft.manifest.get("modules", []))
    if module_id not in have:
        needed_by = [m for m in have if module_id in module_store.available().get(m).manifest.needs] \
            if all(m in module_store.available() for m in have) else []
        return [f"'{module_id}' is brought along by {', '.join(needed_by)} -- remove that first."] if needed_by else []
    draft.manifest["modules"] = [m for m in have if m != module_id]
    draft.save()
    return [f"{module_id} unlinked"]


# compatibility: compound setup and drafting call these by name
def has_solution_chemistry(draft) -> bool:
    return "solution_chemistry" in used(draft) or "chemistry" in draft.manifest.get("builtin_stages", [])


def add_solution_chemistry(draft) -> List[str]:
    """Link the Solution chemistry module into a draft (saved by the caller)."""
    added = add_to_manifest(draft.manifest, ["solution_chemistry"])
    return ["Solution chemistry module linked: " + "; ".join(describe("solution_chemistry"))] if added else []


def ensure_chemistry_prompt(folder: Path) -> bool:
    """(No longer copies anything: the chemistry prompt comes from the Solution chemistry module.)"""
    return False


CHEMISTRY_POSTPROCESS = list(module_store.available()["solution_chemistry"].manifest.postprocess) \
    if "solution_chemistry" in module_store.available() else []
CHEMISTRY_RULE = (module_store.available()["solution_chemistry"].manifest.stage_rules or [""])[0] \
    if "solution_chemistry" in module_store.available() else ""


# ---- packs drafted with copies (before the reference design) -----------------------------------------------------------

def migrate_copies(folder: Path) -> List[str]:
    """Turn copies of module content in a user's pack into links: copied vocabulary / chemistry prompt / stage files
    identical to the module's are removed, the module's rules and hints are taken out of the pack's stages, its
    categories (same id and fields) out of the manifest, its steps and calculations out of the pack's own lists -- and
    the module is listed in "modules". Parameters stay where they are (they're the pack's now). Lines done."""
    from parameter_extractor.pack_editing import PackDraft
    folder = Path(folder)
    draft = PackDraft.load(folder)
    if draft.builtin:
        raise ValueError("The app's own data packs can't be changed.")
    m, done, found = draft.manifest, [], module_store.available()
    want = []
    if "analysis" in m.get("builtin_stages", []) or (folder / "analysis_vocab.json").is_file():
        want.append("analysis")
    if "chemistry" in m.get("builtin_stages", []):
        want.append("solution_chemistry")
    names = {s.get("name") for s in draft.stages.values()}
    for mid in ("kinetics", "wet_dry"):
        if mid in found and any(json.loads(p.read_text()).get("name") in names for p in found[mid].stage_files()):
            want.append(mid)
    if all(x in m.get("postprocess", []) for x in ("peptide_totals", "oligomer_totals")):
        want.append("peptides_oligomers")
    want = [w for w in want if w in found]
    if not want:
        return []
    add_to_manifest(m, want)
    mods = module_store.resolve(m["modules"])
    provided_steps = {s for x in mods for s in x.manifest.builtin_stages}
    provided_calcs = {c for x in mods for c in x.manifest.postprocess}
    before = (list(m.get("builtin_stages", [])), list(m.get("postprocess", [])))
    m["builtin_stages"] = [s for s in m.get("builtin_stages", []) if s not in provided_steps]
    m["postprocess"] = [c for c in m.get("postprocess", []) if c not in provided_calcs]
    if before != (m["builtin_stages"], m["postprocess"]):
        done.append("steps and calculations now come from the modules")
    for x in mods:
        for cat in x.manifest.variable_categories:
            own = next((c for c in m.get("variable_categories", []) if c.get("id") == cat["id"]), None)
            if own is not None and all(own.get(k) == v for k, v in cat.items() if k not in ("table_order",)):
                m["variable_categories"].remove(own)
                cc = m.get("category_columns", {}).get(cat["id"], {})
                mod_cc = x.manifest.category_columns.get(cat["id"], {})
                if not [c for c in cc.get("columns", []) if c not in mod_cc.get("columns", [])]:
                    m.get("category_columns", {}).pop(cat["id"], None)
                done.append(f"category {cat['label']} now comes from the {x.label} module")
    rules = {r for x in mods for r in x.manifest.stage_rules}
    hints = {step: h for x in mods for step, h in x.manifest.stage_hints.items()}
    for file, spec in list(draft.stages.items()):
        same_stage = next((x for x in mods for p in x.stage_files() if json.loads(p.read_text()).get("name") == spec.get("name")), None)
        if same_stage is not None:
            draft.remove_stage(file)
            done.append(f"stage '{spec.get('name')}' now comes from the {same_stage.label} module")
            continue
        if any(r in rules for r in spec.get("rules", [])):
            spec["rules"] = [r for r in spec.get("rules", []) if r not in rules]
        for step, h in hints.items():
            if (spec.get("hint_by_stage") or {}).get(step) == h:
                spec["hint_by_stage"].pop(step)
                if not spec["hint_by_stage"]:
                    spec.pop("hint_by_stage")
    for name, module_file in (("analysis_vocab.json", "analysis_vocab.json"), ("prompts/chemistry.md", "prompts/chemistry.md")):
        own = folder / name
        src = next((x.file(module_file) for x in mods if x.file(module_file)), None)
        same = own.is_file() and src is not None and (
            json.loads(own.read_text()) == json.loads(src.read_text()) if name.endswith(".json")   # formatting aside
            else own.read_text().strip() == src.read_text().strip())
        if same:
            own.unlink()
            if name == "analysis_vocab.json":
                draft.analysis_vocab = None
            done.append(f"{name}: the module's (identical copy removed)")
        elif own.is_file() and src is not None:
            done.append(f"{name}: the pack's own (it differs from the module's) -- kept, and it wins over the module's")
    draft.save()
    return [f"linked: {', '.join(want)}"] + done
