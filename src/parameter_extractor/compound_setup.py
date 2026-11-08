"""
Compounds for a research area that was drafted without the chemistry step (Mickey, 2026-11-08): a drafted pack has
columns like 'mgcl2_concentration_mM' or pairs like 'reactant_species' (text) + 'reactant_concentration_mM' --
substances the chemistry step would handle properly (one column per compound in the '<role>_<name>_<phase>_<measure>'
format, names matched to PubChem identities, mixing / ratio calculations). `find_compounds(draft)` works this out
LOCALLY -- no model, only PubChem's free name lookups -- and `apply(draft, plan)` rewrites the pack:

- compounds come from (a) column names that contain one ('mgcl2_concentration_mM' -> MgCl2; element letters' case is
  restored and the formula confirmed on PubChem), (b) the example values of the draft's paper surveys
  (drafted_surveys.json) for substance-type text parameters, (c) a text parameter's allowed words and the 'e.g. ...'
  lists in descriptions. Each candidate is kept when the app's name rules (names.match_species) or PubChem identify
  it; the vocabulary gets its name, CID, PubChem title and synonyms (species_cids.json), like the app's own packs.
- a substance PAIR (a text parameter naming the substance -- species / reactant / product / additive ... -- and the
  numeric parameters sharing its prefix) and every compound-named column are replaced by the chemistry step: the
  parameters are removed from their stage (the step records those values per compound), and the compound columns are
  added to the column list: initial_<name>_aq_mM for starting substances, sampled_<name>_aq_mM / _aq_%yield for
  products, in the category the replaced parameter was in.
- the chemistry step and its calculations (normalize_species, mixing, molar_ratios) are switched on, and the chemistry
  prompt is copied from the prebiotic pack when the pack has none (the app has no generic one).

Everything is a proposal first (`CompoundPlan`, shown for review in the GUI); `apply` writes only the parts left ticked.
"""
from __future__ import annotations
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from parameter_extractor import packs

ELEMENTS = ("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr "
            "Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W "
            "Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U").split()
# words of a column name that aren't a substance
GENERIC = set("""concentration conc amount mass molarity molality ratio fraction percent pct yield yields total initial
final starting start mean average avg max min measured relative rate constant value level content loading dose
added addition volume buffer salt salts agent agents activating activator condensing catalyst catalysts mineral
minerals solvent solution solutions reactant reactants reagent reagents product products substrate substrates
species compound compounds monomer monomers nucleotide nucleotides precursor precursors additive additives analyte
molecule molecules other main primary secondary per in of the and or with free bound stock mixture time temperature
ph pressure""".split())
# a text parameter naming a substance
SUBSTANCE_WORDS = {"species", "reactant", "reagent", "compound", "substrate", "monomer", "nucleotide", "precursor",
                   "additive", "salt", "product", "analyte", "molecule", "amino", "peptide", "starting", "activator",
                   "agent", "buffer"}
PRODUCT_WORDS = {"product", "products", "result", "formed", "yield"}
CHEMISTRY_POSTPROCESS = ["normalize_species", "mixing", "molar_ratios"]
SURVEYS_FILE = "drafted_surveys.json"


@dataclass
class FoundCompound:
    name: str                                     # the vocabulary name ('MgCl2', 'UMP', 'Gly-Gly')
    cid: int = 0
    title: str = ""
    synonyms: List[str] = field(default_factory=list)
    roles: Set[str] = field(default_factory=set)              # initial / sampled
    measures: Set[str] = field(default_factory=set)           # mM / %yield
    categories: Dict[str, str] = field(default_factory=dict)  # role -> category id of the replaced parameter
    sources: List[str] = field(default_factory=list)          # where it was found
    include: bool = True

    def columns(self) -> List[str]:
        from parameter_extractor.ingestion.flatten_to_template import species_column
        out = []
        for role in sorted(self.roles):
            for measure in (sorted(self.measures) if role == "sampled" else ["mM"]):
                out.append(species_column(role, self.name, "aq", measure))
        return out


@dataclass
class Replacement:
    stage_file: str
    column: str
    reason: str
    include: bool = True


@dataclass
class CompoundPlan:
    compounds: List[FoundCompound] = field(default_factory=list)
    replacements: List[Replacement] = field(default_factory=list)
    not_identified: List[str] = field(default_factory=list)
    note: str = ""                                            # e.g. PubChem couldn't be reached

    @property
    def empty(self) -> bool:
        return not self.compounds and not self.replacements


# ---- finding names ------------------------------------------------------------------------------------------------

def formula_case(token: str) -> Optional[str]:
    """'mgcl2' -> 'MgCl2', 'nacl' -> 'NaCl'; None when the letters aren't element symbols (two-letter ones first)."""
    t = token.strip()
    if not re.fullmatch(r"[A-Za-z0-9()]+", t) or not re.search(r"[A-Za-z]", t):
        return None
    lower = {e.lower(): e for e in ELEMENTS}
    out, i, n_elements = "", 0, 0
    while i < len(t):
        if t[i].isdigit() or t[i] in "()":
            out += t[i]
            i += 1
            continue
        two, one = t[i:i + 2].lower(), t[i].lower()
        if len(two) == 2 and two in lower and two.isalpha():
            out, i = out + lower[two], i + 2
        elif one in lower:
            out, i = out + lower[one], i + 1
        else:
            return None
        n_elements += 1
    # a formula has a digit, or at least two elements and no long runs of one-letter elements read from a word
    if not re.search(r"\d", out) and (n_elements < 2 or n_elements > 4):
        return None
    return out


def _tokens(column: str) -> List[str]:
    from parameter_extractor.ingestion.observations import unit_for_column
    base = column
    unit = unit_for_column(column)
    if unit:
        base = re.sub(r"_(?:[A-Za-z%]+(?:_[A-Za-z]+)?)$", "", column)      # the unit suffix
    return [t for t in base.split("_") if t]


def names_in_column(column: str) -> List[str]:
    """Candidate substance names inside a column name: runs of non-generic words ('mgcl2_concentration_mM' ->
    ['mgcl2'], 'free_mg_ion_concentration_mM' -> ['mg ion'])."""
    runs, current = [], []
    for t in _tokens(column):
        if t.lower() in GENERIC or t.isdigit():
            if current:
                runs.append(" ".join(current))
            current = []
        else:
            current.append(t)
    if current:
        runs.append(" ".join(current))
    return runs


def names_in_text(text: str) -> List[str]:
    """Items of 'e.g. A, B or C' / 'such as A and B' lists in a description."""
    out = []
    for m in re.finditer(r"(?:e\.g\.,?|such as|for example|like)\s+([^.;)]+)", text or "", re.IGNORECASE):
        for item in re.split(r",\s+|\s+or\s+|\s+and\s+", m.group(1)):     # "2',3'-cGMP" keeps its comma
            item = re.sub(r"^(?:or|and|etc)\b\s*", "", item.strip()).strip(" .\"")
            if 1 <= len(item) <= 40 and len(item.split()) <= 4:
                out.append(item)
    return out


def _reference_vocab() -> tuple:
    try:
        return tuple(packs.available()["prebiotic_chemistry"].vocab.get("species_names", ())) or ("",)
    except Exception:
        return ("",)


class _Resolver:
    """A name -> (vocabulary name, CID, title, synonyms) via the app's name rules and PubChem (cached, fails soft)."""

    def __init__(self, pubchem=None):
        self.pubchem = pubchem

    def resolve(self, raw: str):
        from parameter_extractor.names import match_species
        raw = " ".join((raw or "").split())
        if not raw or raw.lower() in GENERIC:
            return None
        candidates = [raw]
        if " " not in raw:
            fc = formula_case(raw)
            if fc and fc != raw:
                candidates.insert(0, fc)
        for name in candidates:
            try:                    # the app's own naming (the prebiotic vocabulary: 'sodium_triMP', 'Gly-Gly')
                matched = match_species(name, vocab=_reference_vocab())
            except Exception:
                matched = None
            hit = self.pubchem.lookup(name) if self.pubchem is not None else None
            if hit is None and not matched:
                continue
            vocab_name = matched[0] if matched else name
            synonyms = self.pubchem.synonyms(hit.cid) if hit is not None else []
            return vocab_name, (hit.cid if hit else 0), (hit.title if hit else ""), synonyms
        return None


# ---- the plan --------------------------------------------------------------------------------------------------------

def _category_of(manifest: dict, column: str) -> str:
    for cid, entry in (manifest.get("category_columns") or {}).items():
        if column in (entry or {}).get("columns", []):
            return cid
    return ""


def _measure(unit: str, column: str) -> Optional[str]:
    from parameter_extractor.units import canonical_unit, _UNITS
    if (unit or "").strip() == "%" or column.endswith("_pct"):
        return "%yield"
    canon = canonical_unit(unit or "")
    if canon and _UNITS.get(canon, ("",))[0] == "concentration":
        return "mM"
    return None


def _surveys(folder: Path) -> list:
    path = Path(folder) / SURVEYS_FILE
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return []


def find_compounds(draft, pubchem=None) -> CompoundPlan:
    """What the pack's columns and surveys say about compounds (see the module docstring)."""
    plan = CompoundPlan()
    resolver = _Resolver(pubchem)
    found: Dict[str, FoundCompound] = {}          # by CID (or name when PubChem doesn't know it)
    tried: Dict[str, object] = {}
    known = set(draft.species)

    def add(raw: str, role: str, measure: Optional[str], category: str, source: str) -> bool:
        key = raw.strip().lower()
        if key not in tried:
            tried[key] = resolver.resolve(raw)
        hit = tried[key]
        if hit is None:
            if raw.strip() and raw not in plan.not_identified:
                plan.not_identified.append(raw.strip())
            return False
        name, cid, title, synonyms = hit
        k = f"cid:{cid}" if cid else f"name:{name.lower()}"
        fc = found.get(k)
        if fc is None:
            fc = found[k] = FoundCompound(name=name, cid=cid, title=title, synonyms=list(synonyms),
                                          include=name not in known)
        fc.roles.add(role)
        if measure:
            fc.measures.add(measure)
        fc.categories.setdefault(role, category)
        if source not in fc.sources:
            fc.sources.append(source)
        return True

    params = [(file, spec, p) for file, spec in draft.stages.items() for p in spec.get("parameters", [])]
    surveys = _surveys(draft.folder)
    examples: Dict[str, List[str]] = {}
    for s in surveys:
        for v in ((s.get("survey") or {}).get("variables") or []):
            if v.get("kind") == "text" and v.get("example"):
                examples.setdefault(_slug(v.get("column", "")), []).append(v["example"])

    # 1. substance pairs: a text parameter naming the substance + numeric parameters with its prefix
    for file, spec, p in params:
        if p.get("kind") != "text":
            continue
        words = p["column"].lower().split("_")
        if not SUBSTANCE_WORDS & set(words) and not SUBSTANCE_WORDS & set(re.findall(r"[a-z]+", p.get(
                "description", "").lower())[:6]):
            continue
        prefix = words[0]
        role = "sampled" if (PRODUCT_WORDS & set(words) or _category_of(draft.manifest, p["column"]) in
                             ("results", "products")) else "initial"
        partners = [(f2, q) for f2, s2, q in params if q is not p and q.get("kind") != "text"
                    and q["column"].lower().split("_")[0] == prefix and _measure(q.get("unit", ""), q["column"])]
        if not partners:
            continue
        measures = {_measure(q.get("unit", ""), q["column"]) for _, q in partners}
        category = _category_of(draft.manifest, partners[0][1]["column"]) or _category_of(draft.manifest, p["column"])
        names = names_in_text(p.get("description", "")) + list(p.get("choices", []) or []) \
            + examples.get(_slug(p["column"]), [])
        hits = [n for n in dict.fromkeys(names) if add(n, role, None, category, f"examples of '{p['column']}'")]
        for fc in found.values():
            if any(f"examples of '{p['column']}'" == s for s in fc.sources):
                fc.measures |= {m for m in measures if m}
        what = "product" if role == "sampled" else "starting substance"
        plan.replacements.append(Replacement(file, p["column"], f"names the {what}: the chemistry step records each "
                                                                f"one as a compound"))
        for f2, q in partners:
            plan.replacements.append(Replacement(f2, q["column"], f"'{q['column']}' of the substance in "
                                                                  f"'{p['column']}': one column per compound instead"))
        if not hits:
            plan.not_identified.append(f"(no example compounds found for '{p['column']}')")

    # 2. columns named after a compound
    replaced = {r.column for r in plan.replacements}
    for file, spec, p in params:
        if p["column"] in replaced or p.get("kind") == "text":
            continue
        measure = _measure(p.get("unit", ""), p["column"])
        if not measure:
            continue
        category = _category_of(draft.manifest, p["column"])
        role = "sampled" if (PRODUCT_WORDS & set(p["column"].lower().split("_")) or category in ("results", "products")) \
            else "initial"
        if any(add(n, role, measure, category, f"column '{p['column']}'") for n in names_in_column(p["column"])):
            plan.replacements.append(Replacement(file, p["column"], f"the value of {'a product' if role == 'sampled' else 'a starting compound'}: "
                                                                    f"its compound column instead"))
            continue
        # a class of substances with examples ('activating_agent_concentration_mM', e.g. diamidophosphate, ...)
        if not names_in_column(p["column"]):
            hits = [n for n in dict.fromkeys(names_in_text(p.get("description", "")))
                    if add(n, role, measure, category, f"examples of '{p['column']}'")]
            if hits:
                plan.replacements.append(Replacement(file, p["column"], f"a value of {', '.join(hits[:3])}"
                                                                        f"{' ...' if len(hits) > 3 else ''}: one "
                                                                        f"column per compound instead"))
    plan.compounds = sorted(found.values(), key=lambda c: c.name.lower())
    if pubchem is not None and getattr(pubchem, "unavailable_reason", ""):
        plan.note = pubchem.unavailable_reason + " -- names only matched by the app's own rules."
    return plan


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


# ---- applying it -------------------------------------------------------------------------------------------------------

CHEMISTRY_RULE = ("Dissolved compounds and their concentrations or yields are recorded by the chemistry step -- don't "
                  "list them here.")


def apply(draft, plan: CompoundPlan) -> List[str]:
    """Write the ticked parts of the plan into the draft (then draft.save()); returns what was done, line by line."""
    done = []
    chosen = [c for c in plan.compounds if c.include]
    # the vocabulary with PubChem identities
    species = list(draft.species)
    entries = draft.cids_file.setdefault("species", {})
    for c in chosen:
        if c.name not in species:
            species.append(c.name)
        if c.cid:
            entries[c.name] = {"cid": c.cid, "title": c.title, "synonyms": list(c.synonyms)}
    draft.species = species
    # the replaced parameters
    gone = {(r.stage_file, r.column) for r in plan.replacements if r.include}
    for file, spec in draft.stages.items():
        before = len(spec.get("parameters", []))
        spec["parameters"] = [p for p in spec.get("parameters", []) if (file, p["column"]) not in gone]
        if len(spec["parameters"]) != before:
            done.append(f"stage '{spec.get('name')}': {before - len(spec['parameters'])} parameter(s) replaced by the "
                        f"chemistry step")
        if CHEMISTRY_RULE not in spec.get("rules", []):
            spec.setdefault("rules", []).append(CHEMISTRY_RULE)
    removed = {c for _, c in gone}
    columns = [c for c in draft.columns if c not in removed]
    cc = draft.manifest.setdefault("category_columns", {})
    for entry in cc.values():
        entry["columns"] = [c for c in entry.get("columns", []) if c not in removed]
    first = next(iter(cc), "")
    for c in chosen:
        for col in c.columns():
            if col not in columns:
                columns.append(col)
            role = col.split("_", 1)[0]
            category = c.categories.get(role) or first
            if category:
                entry = cc.setdefault(category, {"columns": []})
                if col not in entry["columns"]:
                    entry["columns"].append(col)
    draft.columns = columns
    # the chemistry step, its calculations and its prompt
    m = draft.manifest
    m["builtin_stages"] = list(dict.fromkeys(list(m.get("builtin_stages", [])) + ["chemistry"]))
    m["postprocess"] = list(dict.fromkeys(list(m.get("postprocess", [])) + CHEMISTRY_POSTPROCESS))
    done.insert(0, f"{len(chosen)} compound(s) added to the vocabulary ({sum(1 for c in chosen if c.cid)} with a "
                   f"PubChem CID); chemistry step and its calculations switched on")
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
    shutil.copyfile(packs.BUILTIN_DIR / "prebiotic_chemistry" / "prompts" / "chemistry.md", own)
    return True


def set_up_compounds(folder: Path, pubchem=None, plan: Optional[CompoundPlan] = None) -> tuple:
    """find + apply + save in one go (the New research area dialog's option, the CLI): (plan, lines done, problems)."""
    from parameter_extractor.pack_editing import PackDraft, check
    draft = PackDraft.load(folder)
    plan = plan or find_compounds(draft, pubchem)
    done = apply(draft, plan) if not plan.empty else ["no compounds found"]
    if not plan.empty:
        draft.save()
        if ensure_chemistry_prompt(folder):
            done.append("chemistry prompt copied from the prebiotic chemistry pack (prompts/chemistry.md)")
    if pubchem is not None:
        pubchem.save()
    return plan, done, check(PackDraft.load(folder))
