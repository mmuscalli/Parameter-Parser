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
ph pressure measured target sampled formed composition name names identity type""".split())
# a text parameter naming a substance
SUBSTANCE_WORDS = {"species", "reactant", "reagent", "compound", "substrate", "monomer", "nucleotide", "precursor",
                   "additive", "salt", "product", "analyte", "molecule", "amino", "peptide", "starting", "activator",
                   "agent", "buffer"}
PRODUCT_WORDS = {"product", "products", "result", "formed", "yield", "target"}
NAMING_WORDS = {"name", "names", "identity", "id", "type", "species", "composition", "used", "main", "list", "target",
                "or", "and", "solvent", "added", "studied", "starting", "initial", "primary"}
RESULT_WORDS = {"product", "measured", "yield", "target", "species", "final", "sampled", "formed"}
CHEMISTRY_POSTPROCESS = ["normalize_species", "mixing", "molar_ratios"]
# (id, label, description, pattern, place after the area's own categories)
COMPOUND_CATEGORIES = [
    ("starting_compounds", "Starting Compounds", "concentrations of the compounds in the starting solution",
     r"^(?:initial|stock)_.+_(?:aq|gas|s)(?:_avg)?_mM", 5),
    ("products", "Products", "amounts and yields of the compounds formed or measured at the end",
     r"^(?:total_)?sampled_.+_(?:aq|gas|s)(?:_avg)?_(?:mM|%yield|%recovered|ratio|rate_mM_hr)", 6)]
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
class Rename:
    """A column changed to the app's naming conventions (conventions.py); new '' = dropped (a row column)."""
    stage_file: str
    column: str
    new: str
    unit: str
    kind: str
    integer: bool
    reason: str
    include: bool = True


@dataclass
class CompoundPlan:
    compounds: List[FoundCompound] = field(default_factory=list)
    replacements: List[Replacement] = field(default_factory=list)
    renames: List[Rename] = field(default_factory=list)
    not_identified: List[str] = field(default_factory=list)
    note: str = ""                                            # e.g. PubChem couldn't be reached

    @property
    def empty(self) -> bool:
        return not self.compounds and not self.replacements and not self.renames


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
    # a formula has a digit, or is short: 2 elements in <= 4 letters (NaCl, KCl), 3 in <= 5 (NaOH) -- not a word
    # spelled with element letters ('borate' = B O Ra Te, 'mg' = one element: an abbreviation, not a formula)
    if not re.search(r"\d", out) and not (n_elements == 2 and len(t) <= 4 or n_elements == 3 and len(t) <= 5):
        return None
    return out


def is_abbreviation(name: str) -> bool:
    """'ImpA', 'RCP', 'p2A', 'TMP': a short code with capitals or digits, not a formula -- PubChem's first hit for these
    is often another compound (ImpA -> isopropyl methylphosphonate, p2A -> a pyridine oxime), so a hit counts only when
    PubChem lists the code itself among the compound's names (or a full name identifies it)."""
    n = name.strip()
    return bool(re.fullmatch(r"[A-Za-z0-9'\-,()+]{2,8}", n)) and bool(re.search(r"[A-Z0-9]", n)) \
        and formula_case(n) != n


# not compounds: enzymes, dyes, kits, buffers named by type, classes of molecules (the surveys list them anyway)
NOT_A_COMPOUND = re.compile(r"\b(?:buffers?|polymerase|enzymes?|ligase|kit|dyes?|stain|SYBR|ladder|marker|primers?|"
                            r"templates?|strands?|oligomers?|oligonucleotides?|polymers?|products?|mixtures?|"
                            r"solutions?|media|medium|water|DNA|RNA|protein|peptides|lipids|vesicles|membranes?|"
                            r"aerosols?|droplets?|clays?|minerals?|glass|salts|ions|nucleotides|amino acids|ribozymes?|DNase\w*|"
                            r"RNase\w*|dNTPs|dimers?|beads|\w*[DR]NA|oligo\w*|Cy\d|FAM|Alexa\w*)\b|\s(?:and|or)\s",
                            re.IGNORECASE)


def is_compound_name(name: str) -> bool:
    """A specific compound's name, not a class or material ('phosphate buffer', 'RNA oligomers', 'Taq polymerase')."""
    n = (name or "").strip()
    if re.fullmatch(r"[a-z]{1,2}|[A-Z]|[a-z][->][A-Z]", n) and formula_case(n) != n:
        return False                       # figure-panel letters and the like ('b', 'ab', 'a-P')
    return bool(n) and len(n) <= 60 and not NOT_A_COMPOUND.search(n) and len(n.split()) <= 5


FORMULA_WORD = re.compile(r"(?<![A-Za-z])(?:[A-Z][a-z]?\d*){2,}(?:\.\w+)?(?![a-z])|(?<![A-Za-z])[A-Z][a-z]?\d*[+-]+")


def formula_words(text: str) -> List[str]:
    """Formula-like words in a text ('MgCl2', 'NaCl', 'Mg2+') -- the original spelling behind a column's 'mgcl2'."""
    return [w for w in FORMULA_WORD.findall(text or "") if formula_case(w.rstrip("+-")) or w.endswith(("+", "-"))]


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


def _reference_cids() -> Dict[str, dict]:
    """The prebiotic pack's hand-checked identities (species_cids.json): trusted over a PubChem name search."""
    try:
        path = packs.available()["prebiotic_chemistry"].species_cids_path
        return json.loads(path.read_text()).get("species", {}) if path else {}
    except Exception:
        return {}


def _reference_vocab() -> tuple:
    try:
        return tuple(packs.available()["prebiotic_chemistry"].vocab.get("species_names", ())) or ("",)
    except Exception:
        return ("",)


class _Resolver:
    """A name -> (vocabulary name, CID, title, synonyms) via the app's name rules and PubChem (cached, fails soft)."""

    def __init__(self, pubchem=None):
        self.pubchem = pubchem
        self.reference = _reference_cids()

    def _pubchem(self, name: str, code: bool = False):
        if self.pubchem is None or not name:
            return None
        checked = getattr(self.pubchem, "lookup_checked", None)
        hit = self.pubchem.lookup(name) if checked is None else checked(name)
        if hit is None:
            return None
        synonyms = self.pubchem.synonyms(hit.cid)
        if checked is None and code and name not in synonyms and name != hit.title:   # (test doubles without it)
            return None
        return hit.cid, hit.title, synonyms

    def resolve(self, raw: str, full_name: str = "", trusted: bool = False, from_column: bool = False):
        """(vocabulary name, CID, PubChem title, synonyms) or None. `trusted`: the name is known to be a compound
        (the paper survey listed it) -- kept without a CID when nothing identifies it."""
        from parameter_extractor.names import match_species
        raw = " ".join((raw or "").split())
        if not raw or raw.lower() in GENERIC:
            return None
        names = [raw]
        formula = None
        if " " not in raw and raw == raw.lower():       # a lower-cased column word: its formula spelling first
            formula = formula_case(raw)                 # (a name written with capitals is kept as written: CHES)
            if formula and formula != raw:
                names.insert(0, formula)
        for name in names:
            try:                    # the app's own naming (the prebiotic vocabulary: 'sodium_triMP', 'Gly-Gly')
                matched = match_species(name, vocab=_reference_vocab())
            except Exception:
                matched = None
            vocab_name = matched[0] if matched else name
            ref = self.reference.get(vocab_name)
            if ref and ref.get("cid"):             # hand-checked identity
                return vocab_name, int(ref["cid"]), ref.get("title", ""), list(ref.get("synonyms", []))
            hit = self._pubchem(full_name) if full_name else None
            # a word from a column name goes to PubChem only as a formula ('primer' found a drug there); a code only
            # when PubChem lists it as one of the compound's names
            if hit is None and (not from_column or name == formula):
                hit = self._pubchem(name, code=is_abbreviation(name))
            if hit is not None:
                return (vocab_name,) + hit
            if matched:
                return vocab_name, 0, "", []
        if trusted:
            return raw, 0, "", []
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


def find_compounds(draft, pubchem=None, tidy: bool = True) -> CompoundPlan:
    """What the pack's columns and surveys say about compounds (see the module docstring)."""
    plan = CompoundPlan()
    resolver = _Resolver(pubchem)
    found: Dict[str, FoundCompound] = {}          # by CID (or name when PubChem doesn't know it)
    tried: Dict[str, object] = {}
    known = set(draft.species)

    def add(raw: str, role: str, measure: Optional[str], category: str, source: str, full_name: str = "",
            trusted: bool = False, from_column: bool = False) -> bool:
        key = raw.strip().lower()
        if key not in tried or (tried[key] is None and (trusted or full_name)):
            tried[key] = resolver.resolve(raw, full_name, trusted, from_column)
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

    # 0. the compounds the paper surveys list (with full names for abbreviations)
    survey_compounds = []
    for s in surveys:
        for c in ((s.get("survey") or {}).get("compounds") or []):
            # 'Mn2+/Fe3+': two compounds
            for part in (re.split(r"\s*/\s*", c.get("name", "")) if "/" in c.get("name", "") else [c.get("name", "")]):
                if part and c.get("role") != "other" and is_compound_name(part):
                    survey_compounds.append(dict(c, name=part, full_name=c.get("full_name", "") if part == c["name"]
                                                 else ""))
                elif part and part not in plan.not_identified:
                    plan.not_identified.append(part)
    surveyed_names = [c["name"] for c in survey_compounds]

    # 1. substance pairs: a text parameter naming the substance + numeric parameters of it
    for file, spec, p in params:
        if p.get("kind") != "text":
            continue
        words = p["column"].lower().split("_")
        # a column that NAMES substances ('reactant_species', 'buffer_or_solvent'), not one describing them
        # ('product_phase_state')
        if not SUBSTANCE_WORDS & set(words) or set(words) - SUBSTANCE_WORDS - NAMING_WORDS:
            continue
        prefix = words[0]
        role = "sampled" if (PRODUCT_WORDS & set(words) or _category_of(draft.manifest, p["column"]) in
                             ("results", "products") or "result" in spec.get("name", "")) else "initial"

        def partner(f2, q) -> bool:
            if q is p or q.get("kind") == "text" or not _measure(q.get("unit", ""), q["column"]):
                return False
            qwords = set(q["column"].lower().split("_"))
            if names_in_column(q["column"]):      # a column of one named compound: handled below
                return False
            return (q["column"].lower().split("_")[0] == prefix or bool(set(words) & qwords & SUBSTANCE_WORDS)
                    or role == "sampled" and f2 == file and bool(qwords & RESULT_WORDS))
        partners = [(f2, q) for f2, s2, q in params if partner(f2, q)]
        if not partners:
            continue
        measures = {_measure(q.get("unit", ""), q["column"]) for _, q in partners}
        category = _category_of(draft.manifest, partners[0][1]["column"]) or _category_of(draft.manifest, p["column"])
        names = [n for n in names_in_text(p.get("description", "")) + list(p.get("choices", []) or [])
                 + examples.get(_slug(p["column"]), []) if is_compound_name(n)]
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
        spelled = formula_words(p.get("description", "")) + surveyed_names

        def original(token: str) -> str:
            """'mg' -> 'MgCl2' when the description or the surveys spell it out (a salt before its ion)."""
            t = token.replace(" ", "").lower()
            hits = [w for w in spelled if w.lower().startswith(t)]
            hits.sort(key=lambda w: (w.rstrip("+-") != w, w.lower() != t, -len(w)))
            return hits[0] if hits else token
        if any(add(original(n), role, measure, category, f"column '{p['column']}'", from_column=original(n) == n)
               for n in names_in_column(p["column"])):
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
    product_measures = {m for r in plan.replacements for f, s2, q in params if q["column"] == r.column
                        for m in [_measure(q.get("unit", ""), q["column"])] if m and m != "mM"} or set()
    for c in survey_compounds:
        role = "sampled" if c.get("role") == "product" else "initial"
        measure = "mM" if role == "initial" else None
        if add(c["name"], role, measure, "", "the paper surveys", full_name=c.get("full_name", ""), trusted=True):
            for fc in found.values():
                if "the paper surveys" in fc.sources and role == "sampled" and not fc.measures:
                    fc.measures |= product_measures or {"mM"}
    for fc in found.values():
        if "sampled" in fc.roles and not fc.measures:
            fc.measures.add("mM")
    plan.compounds = sorted(found.values(), key=lambda c: c.name.lower())
    unique, seen_rep = [], set()
    for r in plan.replacements:
        if (r.stage_file, r.column) not in seen_rep:
            seen_rep.add((r.stage_file, r.column))
            unique.append(r)
    plan.replacements = unique
    if tidy:                          # the other columns: the app's naming conventions
        from parameter_extractor.conventions import canonical
        replaced = {r.column for r in plan.replacements}
        taken = set(draft.all_columns())
        for file, spec, p in params:
            if p["column"] in replaced:
                continue
            conv = canonical(p["column"], p.get("unit", ""), p.get("kind", "number"), p.get("description", ""))
            if conv is None:
                continue
            if conv.column and conv.column in taken and conv.column not in draft.columns:
                continue                  # e.g. a built-in column filled elsewhere
            plan.renames.append(Rename(file, p["column"], conv.column, conv.unit, conv.kind or p.get("kind", ""),
                                       conv.integer, conv.reason))
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
    chemistry = bool(chosen) or any(r.include for r in plan.replacements)
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
        if chemistry and CHEMISTRY_RULE not in spec.get("rules", []):
            spec.setdefault("rules", []).append(CHEMISTRY_RULE)
    removed = {c for _, c in gone}
    renamed: Dict[str, str] = {}
    for r in (x for x in plan.renames if x.include):
        spec = draft.stages.get(r.stage_file, {})
        for i, p in enumerate(list(spec.get("parameters", []))):
            if p["column"] != r.column:
                continue
            if not r.new:                       # a row column filled elsewhere (duration_hr)
                spec["parameters"].remove(p)
                removed.add(r.column)
            elif any(q["column"] == r.new for s2 in draft.stages.values() for q in s2.get("parameters", [])):
                spec["parameters"].remove(p)    # the conventional column is already filled by a parameter
                removed.add(r.column)
            else:
                p["column"] = r.new
                if r.unit:
                    p["unit"] = r.unit
                else:
                    p.pop("unit", None)
                if r.kind == "text":
                    p["kind"] = "text"
                if r.integer:
                    p["integer"] = True
                renamed[r.column] = r.new
        done.append(f"{r.column} -> {r.new or '(row column duration_hr)'}")
    columns = [renamed.get(c, c) for c in draft.columns if c not in removed]
    columns = list(dict.fromkeys(columns))
    cc = draft.manifest.setdefault("category_columns", {})
    for entry in cc.values():
        entry["columns"] = list(dict.fromkeys(renamed.get(c, c) for c in entry.get("columns", []) if c not in removed))
    # compound columns get their own blocks, as in the prebiotic pack: Starting compounds, then Products (by pattern,
    # so compounds accepted in reviews later land there too)
    if chosen:
        cats = draft.manifest.setdefault("variable_categories", [])
        ids = {c.get("id") for c in cats}
        top = max([c.get("table_order", 0) for c in cats] + [50])
        for cid, label, desc, pattern, step in COMPOUND_CATEGORIES:
            if cid not in ids:
                cats.append({"id": cid, "table_order": top + step, "label": label, "value_type": "number",
                             "model_assigns": False, "description": desc})
            entry = cc.setdefault(cid, {"columns": []})
            if pattern not in entry.setdefault("patterns", []):
                entry["patterns"].append(pattern)
    for c in chosen:
        for col in c.columns():
            if col not in columns:
                columns.append(col)
    draft.columns = columns
    # the chemistry step, its calculations and its prompt
    m = draft.manifest
    if chemistry:
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


def set_up_compounds(folder: Path, pubchem=None, plan: Optional[CompoundPlan] = None, tidy: bool = True) -> tuple:
    """find + apply + save in one go (the New research area dialog's option, the CLI): (plan, lines done, problems)."""
    from parameter_extractor.pack_editing import PackDraft, check
    draft = PackDraft.load(folder)
    plan = plan or find_compounds(draft, pubchem, tidy=tidy)
    done = apply(draft, plan) if not plan.empty else ["no compounds found"]
    if not plan.empty:
        draft.save()
        if "chemistry" in draft.manifest.get("builtin_stages", []) and ensure_chemistry_prompt(folder):
            done.append("chemistry prompt copied from the prebiotic chemistry pack (prompts/chemistry.md)")
    if pubchem is not None:
        pubchem.save()
    return plan, done, check(PackDraft.load(folder))
