"""
Editing data packs (packs) and checking them (Mickey, 2026-11-05: pack creation inside the app, menu Data Packs).

`PackDraft` holds one pack's files as plain data -- the manifest, the column list, the extra columns, every stage
spec, the rules files -- so a window can change them freely and write them all at once with `save()`. Keys the
editor doesn't know (the template's `_about_*` explanations, modes, alternatives, ...) are kept as they are.

`check(draft)` finds what would break or quietly misbehave: invalid files, columns used but not defined, units that
don't match a column's name, stages that never run, unknown calculations, leftover template examples. Each finding
is a `Problem` with a level -- "error" (the pack won't work as meant), "warning" (probably not what you want) or
"note" (worth knowing).

The app's own packs live inside the app and aren't edited; a copy of one is (packs.create_pack(source=...)).
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from parameter_extractor import packs

# code-based extraction steps a pack can switch on (packs.PackManifest.builtin_stages)
BUILTIN_STAGES = {
    "chemistry": "Dissolved species and their concentrations / yields, with a compound vocabulary (solution "
                 "chemistry). Needs species names in the columns file.",
    "fit_models": "How astronomical fits were made: data, software, priors, joint fits (exoplanets).",
    "analysis": "Analytical techniques and their instrument settings -> analysis_<technique>_<setting>_<unit> "
                "columns. Needs analysis_vocab.json (techniques and settings) in the pack's folder.",
}
# calculations a pack can run on its rows (packs.PackManifest.postprocess): description, step it needs ('' = none)
CALCULATIONS = {
    "normalize_species": ("Compound names -> one name per compound (rules, PubChem); concentrations -> mM.", "chemistry"),
    "mixing": ("Concentrations in the mixture from stock solutions and the volumes combined.", "chemistry"),
    "molar_ratios": ("Concentrations from stated molar ratios.", "chemistry"),
    "amounts": ("Concentrations from amounts (mmol) and the reaction volume; totals split by ratio.", "chemistry"),
    "peptide_totals": ("Total peptide yield per row (the sum of the peptide yields).", "chemistry"),
    "oligomer_totals": ("Total nucleic-acid oligomer yield and the longest oligomer per row.", "chemistry"),
    "water_type": ("Solvent named as a water type ('water' -> distilled water, flagged).", ""),
    "ambient_conditions": ("'Ambient' temperature / pressure -> 25 °C / 1 bar.", ""),
    "atmospheric_start": ("A sealed batch experiment starts at 1 bar unless stated.", ""),
    "results_check": ("Flags a paper with no measured results (columns starting 'sampled_').", ""),
    "row_labels": ("Planet name and fit label from the row labels (exoplanets).", ""),
    "exoplanet_masses": ("Planet masses in Earth and Jupiter masses (exoplanets).", ""),
    "reference_names": ("Reference names like 'Teng et al. 2023' (exoplanets).", ""),
    "archive_validation": ("Compares values with the NASA Exoplanet Archive (exoplanets).", ""),
}
# the built-in step each calculation was written alongside: the editor lists those of the area's steps first and
# the rest under "Other calculations" (2026-11-05)
CALCULATION_STEP = {**{n: "chemistry" for n in ("normalize_species", "mixing", "molar_ratios", "amounts",
                                                "peptide_totals", "oligomer_totals", "water_type", "ambient_conditions",
                                                "atmospheric_start", "results_check")},
                    **{n: "fit_models" for n in ("row_labels", "exoplanet_masses", "reference_names",
                                                 "archive_validation")}}
# what each calculation needs to do anything: shown in the editor's Requirements column (2026-11-06)
CALCULATION_NEEDS = {
    "normalize_species": "The chemistry step's compounds; online lookups on for PubChem.",
    "mixing": "Stock concentrations and the volumes of the solutions combined (chemistry step).",
    "molar_ratios": "Molar ratios stated by the chemistry step; one side's concentration known.",
    "amounts": "Amounts (mol, mmol ...) from the chemistry step; a solvent_volume_mL column.",
    "peptide_totals": "Peptide %yield columns (chemistry step).",
    "oligomer_totals": "Oligonucleotide %yield / length columns (chemistry step).",
    "water_type": "A solvent_name column.",
    "ambient_conditions": "initial_temperature_C / sampled_temperature_C / initial_pressure_bar columns in a stage.",
    "atmospheric_start": "experiment_type, vessel_sealed and initial_pressure_bar columns.",
    "results_check": "Result columns starting 'sampled_' or 'total_sampled_'.",
    "row_labels": "Row labels 'planet [solution]'; pl_name / pl_fitlabel columns.",
    "exoplanet_masses": "pl_bmassj / pl_masse / pl_msinij-style mass columns.",
    "reference_names": "pl_refname / st_refname / disc_refname columns; the paper's authors and year.",
    "archive_validation": "pl_name rows and online lookups on (NASA Exoplanet Archive).",
}
# shared prompts a pack can add rules to (prompts/<name>.rules.md): what they do
RULE_PROMPTS = {
    "structure_planner": "Planning rows: which results become rows and how they group into sets.",
    "figure_planner": "Suggestions when digitizing a figure: which columns its axes and series go into.",
    "focused_search": "Focused searches across many papers: what a set and an object are.",
    "metadata": "Reading the paper's title, authors, year and journal.",
}
# the template's examples: still there in a pack made from it -> a note
TEMPLATE_EXAMPLE_STAGE = "example_measurements"
TEMPLATE_EXAMPLE_RULES = "EXAMPLE RULES"
TEMPLATE_EXAMPLE_FORMULA = "temperature_K"

STAGE_NAME = re.compile(r"[a-z][a-z0-9_]{1,60}")
BAD_COLUMN_CHARS = re.compile(r'[,"\n\t]')


def rules_to_items(text: str) -> List[str]:
    """A rules file as the editor's rows (2026-11-05): each '- ' line starts a rule, the indented lines after it
    continue it (joined with spaces); text before the first '- ' is a rule of its own per paragraph."""
    items: List[str] = []
    current: Optional[str] = None
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped == "-":
            if current is not None:
                items.append(current)
            current = stripped[2:].strip()
        elif not stripped:
            if current is not None and not line.startswith(" "):
                items.append(current)
                current = None
        else:
            current = stripped if current is None else f"{current} {stripped}"
    if current is not None:
        items.append(current)
    return [i for i in items if i]


def items_to_rules(items: List[str]) -> str:
    """The rows back into a rules file: one '- ' line per rule ('' when there are none)."""
    rules = [" ".join(i.split()) for i in items if i and i.strip()]
    return "".join(f"- {r}\n" for r in rules)


@dataclass
class Problem:
    level: str            # "error" | "warning" | "note"
    where: str            # "Columns", "Stage 'measurements'", ...
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper()} -- {self.where}: {self.message}"


def _read(path: Path, default):
    return json.loads(path.read_text()) if path.is_file() else default


@dataclass
class PackDraft:
    folder: Path
    manifest: dict
    columns_file: dict                     # the template file as read: all_columns, species_names, _about...
    standard_file: dict
    stages: Dict[str, dict]                # file name -> spec (in file order)
    rules: Dict[str, str]                  # prompt name -> its rules text ('' = none)
    own_prompts: List[str] = field(default_factory=list)     # whole prompts of its own (prompts/<name>.md)
    removed_stage_files: List[str] = field(default_factory=list)
    # the analysis step's techniques and settings (analysis_vocab.json; None = the pack has none) and the compound
    # vocabulary's PubChem identities (species_cids.json: {"species": {name: {cid, title, synonyms, ...}}})
    analysis_vocab: Optional[dict] = None
    cids_file: dict = field(default_factory=lambda: {"species": {}})

    # ---- loading ---------------------------------------------------------------------

    @classmethod
    def load(cls, folder: Path) -> "PackDraft":
        folder = Path(folder)
        manifest = json.loads((folder / "pack.json").read_text())
        columns = _read(folder / manifest.get("template", "template_vocab.json"), {"all_columns": [], "species_names": []})
        standard = _read(folder / manifest["standard_columns"], {"columns": []}) if manifest.get("standard_columns") \
            else {"columns": []}
        stages = {p.name: json.loads(p.read_text()) for p in sorted((folder / "stages").glob("*.json"))}
        prompts = folder / "prompts"
        rules = {name: (prompts / f"{name}.rules.md").read_text() if (prompts / f"{name}.rules.md").is_file() else ""
                 for name in RULE_PROMPTS}
        own = sorted(p.stem for p in prompts.glob("*.md") if not p.name.endswith(".rules.md")) if prompts.is_dir() else []
        analysis = _read(folder / ANALYSIS_FILE, None)
        cids = _read(folder / manifest["species_cids"], {"species": {}}) if manifest.get("species_cids") \
            else {"species": {}}
        cids.setdefault("species", {})
        return cls(folder, manifest, columns, standard, stages, rules, own, analysis_vocab=analysis, cids_file=cids)

    @property
    def builtin(self) -> bool:
        """One of the app's own packs (inside the app): read-only -- copy it to change it."""
        try:
            self.folder.resolve().relative_to(packs.BUILTIN_DIR.resolve())
            return True
        except ValueError:
            return False

    # ---- the parts as the editor sees them ----------------------------------------------

    @property
    def columns(self) -> List[str]:
        return list(self.columns_file.get("all_columns", []))

    @columns.setter
    def columns(self, value: List[str]) -> None:
        self.columns_file["all_columns"] = [c.strip() for c in value if c.strip()]

    @property
    def species(self) -> List[str]:
        return list(self.columns_file.get("species_names", []))

    @species.setter
    def species(self, value: List[str]) -> None:
        self.columns_file["species_names"] = [s.strip() for s in value if s.strip()]

    @property
    def compounds(self) -> List[dict]:
        """The compound vocabulary with its PubChem identities: [{name, cid, title, synonyms}] in list order."""
        known = self.cids_file.get("species", {})
        return [{"name": n, "cid": (known.get(n) or {}).get("cid", 0) or 0, "title": (known.get(n) or {}).get("title", ""),
                 "synonyms": list((known.get(n) or {}).get("synonyms", []))} for n in self.species]

    @compounds.setter
    def compounds(self, rows: List[dict]) -> None:
        """Names (in order) and CIDs; a compound whose CID is unchanged keeps its stored title and synonyms."""
        self.species = [r["name"] for r in rows]
        old = self.cids_file.get("species", {})
        new = {}
        for r in rows:
            name, cid = r["name"].strip(), int(r.get("cid") or 0)
            if not name or not cid:
                continue
            entry = dict(old.get(name, {})) if (old.get(name) or {}).get("cid") == cid else {}
            entry["cid"] = cid
            new[name] = entry
        self.cids_file["species"] = new

    def stage_columns(self) -> Dict[str, List[str]]:
        """column -> the stages that fill it."""
        out: Dict[str, List[str]] = {}
        for spec in self.stages.values():
            for p in spec.get("parameters", []):
                if p.get("column"):
                    out.setdefault(p["column"], []).append(spec.get("name", "?"))
        return out

    def all_columns(self) -> List[str]:
        """Every column the pack can write: its columns, extra columns, stage columns and the shared ones."""
        seen = list(self.columns) + [e["column"] for e in self.standard_file.get("columns", [])]
        seen += [c for c in self.stage_columns() if c not in seen]
        seen += [f.get("column", "") for f in self.manifest.get("formulas", []) if f.get("column", "") not in seen]
        seen += [e["column"] for e in packs.common_columns() if e["column"] not in seen]
        from parameter_extractor.ingestion.flatten_to_template import OPTIONAL_PROVENANCE_COLUMNS, PROVENANCE_COLUMNS
        row = ["entry_number", "full_id", "set_id", "sample_id", "set_type", "duration_hr", "duration_range_hr"]
        seen += [c for c in row + PROVENANCE_COLUMNS + OPTIONAL_PROVENANCE_COLUMNS if c not in seen]
        return seen

    def new_stage(self, name: str, label: str) -> str:
        """Add a stage (a spec with the essentials filled in); returns its file name."""
        if not STAGE_NAME.fullmatch(name):
            raise ValueError("A stage name is lower-case letters, digits and '_', starting with a letter.")
        if any(s.get("name") == name for s in self.stages.values()):
            raise ValueError(f"There is already a stage called '{name}'.")
        file = f"{name}.json"
        n = 2
        while file in self.stages or (self.folder / "stages" / file).exists() and file not in self.removed_stage_files:
            file, n = f"{name}_{n}.json", n + 1
        words = self.manifest.get("units", {})
        self.stages[file] = {
            "name": name, "label": label or name.replace("_", " ").capitalize(), "description": "",
            "origin": label.lower() if label else name.replace("_", " "),
            "schema_name": "".join(w.capitalize() for w in name.split("_")) + "Result",
            "system_prompt": "Extract values from a scientific paper. Report only what the paper states.",
            "trigger": {"always": True}, "per": "sample", "set_word": words.get("set", "set"),
            "error_suffixes": ["_err_plus", "_err_minus"], "suffix_separator": "_", "table_images": True,
            "intro": f"For every {words.get('set', 'set')} (and {words.get('sample', 'sample')}) in the structure "
                     "plan below, extract the values the paper reports. A value that holds for every set goes in ONE "
                     "row with `set` ''; one that differs between sets goes in each set's row; one that differs "
                     "between the samples of a set goes in each sample's row.",
            "parameters": [], "rules": []}
        if file in self.removed_stage_files:
            self.removed_stage_files.remove(file)
        return file

    def remove_stage(self, file: str) -> None:
        if self.stages.pop(file, None) is not None and (self.folder / "stages" / file).exists():
            self.removed_stage_files.append(file)

    # ---- saving ------------------------------------------------------------------------

    def save(self) -> None:
        """Write every file. The app's own packs can't be saved (copy them first)."""
        if self.builtin:
            raise PermissionError("The app's own data packs can't be changed: copy one to a new data pack.")
        f = self.folder
        if self.cids_file.get("species") and not self.manifest.get("species_cids"):
            self.manifest["species_cids"] = "species_cids.json"
        (f / "pack.json").write_text(json.dumps(self.manifest, indent=2, ensure_ascii=False) + "\n")
        if self.manifest.get("species_cids"):
            (f / self.manifest["species_cids"]).write_text(json.dumps(self.cids_file, indent=2, ensure_ascii=False) + "\n")
        if self.analysis_vocab is not None:
            (f / ANALYSIS_FILE).write_text(json.dumps(self.analysis_vocab, indent=2, ensure_ascii=False) + "\n")
        template = self.manifest.get("template") or "columns.json"
        self.manifest["template"] = template
        (f / template).write_text(json.dumps(self.columns_file, indent=2, ensure_ascii=False) + "\n")
        if self.manifest.get("standard_columns"):
            (f / self.manifest["standard_columns"]).write_text(
                json.dumps(self.standard_file, indent=2, ensure_ascii=False) + "\n")
        (f / "stages").mkdir(exist_ok=True)
        for file in self.removed_stage_files:
            (f / "stages" / file).unlink(missing_ok=True)
        self.removed_stage_files = []
        for file, spec in self.stages.items():
            (f / "stages" / file).write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
        (f / "prompts").mkdir(exist_ok=True)
        for name, text in self.rules.items():
            path = f / "prompts" / f"{name}.rules.md"
            if text.strip():
                path.write_text(text.rstrip() + "\n")
            else:
                path.unlink(missing_ok=True)
        (f / "pack.json").write_text(json.dumps(self.manifest, indent=2, ensure_ascii=False) + "\n")
        _forget_cached(f)


def _forget_cached(folder: Path) -> None:
    """Saved files are read again: stage specs and the active pack are cached."""
    from parameter_extractor import analysis_vocab
    from parameter_extractor.stages import optional
    optional._specs_in.cache_clear()
    analysis_vocab._load.cache_clear()
    if packs._current is not None and Path(packs._current.folder).resolve() == Path(folder).resolve():
        packs._current = None


ANALYSIS_FILE = "analysis_vocab.json"


def analysis_problems(vocab: dict) -> List["Problem"]:
    """The analysis vocabulary's problems: names that can't be column slots, unknown families, duplicates,
    units the app doesn't convert, aliases shared by two techniques."""
    from parameter_extractor.analysis_vocab import UNIT_TOKENS, _key, token
    out, where = [], "Analysis methods"
    add = lambda level, message: out.append(Problem(level, where, message))
    fams = vocab.get("families", {}) or {}
    if "general" not in fams:
        add("note", "there is no 'general' family (settings every technique has: instrument, calibration, ...).")
    for fid, fam in fams.items():
        seen = set()
        for st in fam.get("settings", []):
            name = st.get("name", "")
            if not name or token(name) != name:
                add("error", f"setting '{name}' ({fid}): a name is words joined by hyphens -- no spaces, "
                             f"underscores or brackets (it becomes part of a column name).")
            if name in seen:
                add("error", f"setting '{name}' is listed twice in {fid}.")
            seen.add(name)
            if st.get("unit") and st["unit"] not in UNIT_TOKENS:
                add("warning", f"setting '{name}' ({fid}): the unit '{st['unit']}' isn't one the app converts to; "
                               f"values will be kept as printed.")
            if not st.get("description"):
                add("note", f"setting '{name}' ({fid}) has no description.")
    names, owner = set(), {}
    for t in vocab.get("techniques", []):
        name = t.get("name", "")
        if not name or token(name) != name:
            add("error", f"technique '{name}': a name is words joined by hyphens -- no spaces or underscores.")
        if name in names:
            add("error", f"technique '{name}' is listed twice.")
        names.add(name)
        for f in t.get("families", []):
            if f not in fams:
                add("error", f"technique '{name}' names an unknown family '{f}'.")
        for a in [name] + list(t.get("aliases", [])):
            k = _key(a)
            if k in owner and owner[k] != name:
                add("warning", f"'{a}' names both {owner[k]} and {name}: the first listed wins.")
            owner.setdefault(k, name)
    return out


# ---- the check ---------------------------------------------------------------------------

def check(draft: PackDraft) -> List[Problem]:
    """Everything that would break the pack or make it quietly misbehave (see the module's docstring)."""
    from parameter_extractor.packs import PackManifest
    from parameter_extractor.stages.optional import StageSpec
    out: List[Problem] = []
    add = lambda level, where, message: out.append(Problem(level, where, message))
    m = draft.manifest

    # manifest
    try:
        PackManifest.model_validate(m)
    except Exception as e:
        add("error", "pack.json", f"not a valid manifest: {_first_error(e)}")
    if not str(m.get("label", "")).strip():
        add("error", "General", "the data pack has no name.")
    for stage in m.get("builtin_stages", []):
        if stage not in BUILTIN_STAGES and stage != "methodology":
            add("error", "General", f"unknown built-in step '{stage}'.")
    for calc in m.get("postprocess", []):
        if calc not in CALCULATIONS:
            add("error", "Calculations", f"unknown calculation '{calc}'.")
        elif CALCULATIONS[calc][1] and CALCULATIONS[calc][1] not in m.get("builtin_stages", []):
            add("warning", "Calculations", f"'{calc}' works on the results of the '{CALCULATIONS[calc][1]}' step, "
                                           f"which this data pack doesn't use: it will do nothing.")
    for key in ("standard_columns", "species_cids"):
        if m.get(key) and not (draft.folder / m[key]).is_file():
            add("error", "pack.json", f"{key} names '{m[key]}', which isn't in the folder.")

    # columns
    columns = draft.columns
    if not columns:
        add("error", "Columns", "the dataset has no columns.")
    for c in sorted({c for c in columns if columns.count(c) > 1}):
        add("error", "Columns", f"'{c}' is listed twice.")
    for c in columns:
        if BAD_COLUMN_CHARS.search(c) or c != c.strip() or " " in c:
            add("error", "Columns", f"'{c}': column names can't contain spaces, commas, quotes or tabs.")
    if "analysis" in m.get("builtin_stages", []) and draft.analysis_vocab is None:
        add("warning", "Analysis methods", "the analysis step has no vocabulary (analysis_vocab.json): every technique "
                                           "and setting it finds will go to the review.")
    if draft.analysis_vocab is not None:
        out += analysis_problems(draft.analysis_vocab)
        if "analysis" not in m.get("builtin_stages", []):
            add("note", "Analysis methods", "the vocabulary is only used by the analysis step, which isn't ticked "
                                            "under Built-in extraction steps.")
    names = draft.species
    for n in sorted({n for n in names if names.count(n) > 1}):
        add("error", "Compounds", f"'{n}' is listed twice.")
    if "chemistry" in m.get("builtin_stages", []) and not draft.species:
        add("warning", "Columns", "the chemistry step uses a compound vocabulary, but none is listed.")

    # stages
    if not draft.stages and not m.get("builtin_stages"):
        add("error", "Stages", "nothing extracts values: add a stage.")
    names, schemas, fills = {}, {}, {}
    for file, spec in draft.stages.items():
        where = f"Stage '{spec.get('name') or file}'"
        try:
            StageSpec.model_validate(spec)
        except Exception as e:
            add("error", where, f"not a valid stage: {_first_error(e)}")
            continue
        name, schema = spec["name"], spec.get("schema_name", "")
        if not STAGE_NAME.fullmatch(name):
            add("error", where, "the name must be lower-case letters, digits and '_', starting with a letter.")
        if name in names:
            add("error", where, f"another stage ({names[name]}) has the same name.")
        names.setdefault(name, file)
        if schema and not schema.isidentifier():
            add("error", where, f"answer format name '{schema}' must be one word of letters and digits.")
        elif schema and schema in schemas:
            add("error", where, f"stage '{schemas[schema]}' uses the same answer format name.")
        schemas.setdefault(schema, name)
        trigger = spec.get("trigger", {})
        if not (trigger.get("always") or trigger.get("keywords") or trigger.get("set_types")
                or trigger.get("set_patterns") or trigger.get("sample_fields")):
            add("warning", where, "it never runs: tick 'always', or give keywords / set types / set patterns.")
        params = spec.get("parameters", [])
        if not params and not spec.get("open_ended"):
            add("error", where, "it has no parameters.")
        seen, outside, unnamed_units = set(), [], []
        for p in params:
            col = (p.get("column") or "").strip()
            if not col:
                add("error", where, "a parameter has no column.")
                continue
            if col in seen:
                add("error", where, f"'{col}' is a parameter twice.")
            seen.add(col)
            fills.setdefault(col, []).append(name)
            if BAD_COLUMN_CHARS.search(col) or " " in col:
                add("error", where, f"'{col}': column names can't contain spaces, commas, quotes or tabs.")
            if not (p.get("description") or "").strip():
                add("warning", where, f"'{col}' has no description: the model only sees the column name.")
            if col not in columns and col not in {e["column"] for e in draft.standard_file.get("columns", [])}:
                outside.append(col)
            for level, msg in _unit_problems(p):
                if level == "note":
                    unnamed_units.append(f"{col} ({(p.get('unit') or '').strip()})")
                else:
                    add(level, where, msg)
            if p.get("choices") and p.get("kind", "number") != "text":
                add("warning", where, f"'{col}' has allowed choices but is a number: choices apply to text.")
        if outside:                    # grouped: one note per stage, not one per column
            add("note", where, f"{len(outside)} column(s) aren't in the columns list and are added to the dataset "
                               f"after them: {', '.join(outside)}.")
        if unnamed_units:
            add("note", where, f"{len(unnamed_units)} column(s) have a unit that isn't at the end of their name, so "
                               f"values are stored in that unit: {', '.join(unnamed_units)}.")
        if name == TEMPLATE_EXAMPLE_STAGE:
            add("note", where, "this is the template's example stage: rename it and replace its parameters.")
    for col, stages in fills.items():
        if len(stages) > 1:
            add("warning", "Stages", f"'{col}' is filled by {len(stages)} stages ({', '.join(stages)}): a second, "
                                     "different value is reported as a conflict.")

    # rules
    if "structure_planner" not in draft.own_prompts and not draft.rules.get("structure_planner", "").strip():
        add("warning", "Rules", "no rules for planning rows: the shared prompt only knows the general rules. Say "
                                "what one row is.")
    for name, text in draft.rules.items():
        if TEMPLATE_EXAMPLE_RULES in text:
            add("note", "Rules", f"the {name} rules still contain the template's example rules.")

    out += _formula_problems(draft)

    # categories
    from parameter_extractor import variable_categories as vc
    shared = {c.id for c in vc.shared_categories()} | {"figure", "assumed"}
    own = [c.get("id", "") for c in m.get("variable_categories", [])]
    for cid in sorted({c for c in own if own.count(c) > 1}):
        add("error", "Categories", f"category id '{cid}' is used twice.")
    for cid in own:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", cid or ""):
            add("error", "Categories", f"category id '{cid}' must be lower-case letters, digits and '_'.")
    known = set(draft.all_columns())
    for cid, entry in m.get("category_columns", {}).items():
        if cid not in own and cid not in shared:
            add("error", "Categories", f"columns are placed in '{cid}', which isn't a category.")
        for col in entry.get("columns", []):
            if col not in known:
                add("warning", "Categories", f"'{col}' (in {cid}) isn't a column of this data pack.")
        for pattern in entry.get("patterns", []):
            try:
                re.compile(pattern)
            except re.error as e:
                add("error", "Categories", f"pattern '{pattern}' (in {cid}) isn't a valid pattern: {e}.")
    return sorted(out, key=lambda p: ("error", "warning", "note").index(p.level))


def _formula_problems(draft: PackDraft) -> List[Problem]:
    """Formulas (formulas.py): they parse, have a column, name columns the pack has, come after the formulas whose
    columns they use."""
    from parameter_extractor.formulas import IF_PRESENT, Formula, FormulaError
    out = []
    formulas = draft.manifest.get("formulas", [])
    outputs = [(f.get("column") or "").strip() for f in formulas]
    known = set(draft.all_columns()) - set(outputs)
    for i, raw in enumerate(formulas):
        f = Formula.from_dict(raw)
        where = f"Formula '{f.column or i + 1}'"
        if not f.column:
            out.append(Problem("error", where, "the formula has no column to fill."))
        elif BAD_COLUMN_CHARS.search(f.column) or " " in f.column:
            out.append(Problem("error", where, f"'{f.column}': column names can't contain spaces, commas, quotes or tabs."))
        if f.column and outputs.count(f.column) > 1 and outputs.index(f.column) < i:
            out.append(Problem("error", where, "another formula fills the same column."))
        if f.if_present not in IF_PRESENT:
            out.append(Problem("error", where, f"'if a value exists' must be one of {', '.join(IF_PRESENT)}."))
        try:
            inputs = f.inputs()
        except FormulaError as e:
            out.append(Problem("error", where, f"{e}."))
            continue
        if f.column in inputs:
            out.append(Problem("error", where, "the formula uses its own column."))
        earlier = set(outputs[:i])
        later = [c for c in inputs if c in outputs[i + 1:] and c not in earlier]
        if later:
            out.append(Problem("warning", where, f"uses {', '.join(later)}, filled by a LATER formula: move this "
                                                 "one after it (formulas run in order)."))
        unknown = [c for c in inputs if c not in known and c not in earlier and c not in later]
        if unknown:
            out.append(Problem("warning", where, f"uses column(s) this data pack doesn't have: "
                                                 f"{', '.join(unknown)} (rows will have no value for them)."))
        if not f.description.strip():
            out.append(Problem("note", where, "no description: say what the formula calculates."))
        if f.column == TEMPLATE_EXAMPLE_FORMULA:
            out.append(Problem("note", where, "this is the template's example formula: replace or remove it."))
    return out


def _unit_problems(p: dict) -> List[tuple]:
    """A parameter's unit against its column's name (the name's suffix is the unit values are stored in)."""
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.units import canonical_unit
    col, unit = p["column"], (p.get("unit") or "").strip()
    named = unit_for_column(col)
    if named == "pH":                   # a pH column: no unit to convert
        named = ""
    text = p.get("kind", "number") == "text"
    if text:
        return [("warning", f"'{col}' is text but has a unit ({unit}).")] if unit else []
    if named and not unit:
        return [("warning", f"'{col}' is named in {named} but the parameter has no unit: values aren't converted.")]
    if unit and named and (canonical_unit(unit) or unit) != (canonical_unit(named) or named):
        return [("error", f"'{col}' is named in {named} but the parameter's unit is {unit}.")]
    if unit and not named and canonical_unit(unit):
        return [("note", f"'{col}' has unit {unit} but no unit at the end of its name.")]
    return []


def _first_error(e: Exception) -> str:
    errors = getattr(e, "errors", None)
    if callable(errors):
        first = errors()[0]
        return f"{'.'.join(str(x) for x in first.get('loc', ()))}: {first.get('msg', '')}".strip(": ")
    return str(e).splitlines()[0]
