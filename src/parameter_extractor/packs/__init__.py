"""
Domain packs: everything that ties the app to one data pack, kept out of
the code so another area is a new folder, not a rewrite.

A pack is a folder with a pack.json manifest:

  id, label, description, version
  template          JSON with "all_columns" (the dataset's columns, in order) and
                    "species_names" (the species vocabulary, if any)
  standard_columns  JSON {"columns": [{"column", "description"}]}: columns the pack
                    adds beyond its template (optional). Every pack also gets the shared
                    columns of packs/common_columns.json (paper title, DOI, authors, year,
                    journal, arXiv version) unless its template has them
  species_cids      PubChem CIDs of the template's species (optional; pubchem.py)
  builtin_stages    code stages the pack uses: "methodology", "chemistry" (the rest
                    of a pack's extraction is its optional-stage specs)
  postprocess       calculators run on the results, in order: "normalize_species",
                    "mixing", "molar_ratios", "peptide_totals"
  units             what a set and a sample are called, e.g. {"set": "planetary
                    system", "sample": "planet"}, and optionally a row ("row": "object model
                    instance": one planet as one fit models it), used in messages
  compact_text      collapse long runs of layout spaces in the text sent to the model
  formulas          calculations without code: [{column, expression, description, if_present}], run on every
                    row after the review, in order (formulas.py: the expression language)
  modules           shared modules the pack uses, by id ("analysis", "solution_chemistry", "kinetics", "wet_dry",
                    "peptides_oligomers"; parameter_extractor/modules/): linked, not copied -- `Pack.manifest` is the
                    pack's own manifest with the modules' steps, calculations, categories and columns merged in
                    (`own_manifest` is the file as written); prompts, rules, standard columns, stages and data files
                    (analysis_vocab.json) come from the pack first, then its modules
  is_template       the TEMPLATE pack (packs/_template/, 2026-11-05): a complete, working pack with every
                    file explained, copied by create_pack() to start a new data pack. Never listed
                    (available() leaves it out) and never run directly.

and, next to it:
  prompts/*.md      the pack's prompts (structure_planner, ...); a prompt the pack
                    doesn't have comes from the app's own prompts/
  prompts/*.rules.md  extra rules for a shared prompt (figure_planner.rules.md): they
                    fill its {{PACK_RULES}} slot, so the pack needs no copy of it
  stages/*.json     its optional stages (stages/optional.py)

Packs are found in the app's own packs/ folder and in the user's
<app data>/packs/ (so a new area needs no code changes). The active pack is
set at the start of each run (pipeline._start) from RunConfig.pack; code that
needs the template, vocabulary, prompts or stages asks `current()`.
"""
from __future__ import annotations
import json
import re
from functools import cached_property
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

BUILTIN_DIR = Path(__file__).resolve().parent
DEFAULT_PACK = "prebiotic_chemistry"


class PackManifest(BaseModel):
    id: str
    label: str
    description: str = ""
    version: int = 1
    template: str = "template_vocab.json"
    standard_columns: str = ""
    species_cids: str = ""
    builtin_stages: List[str] = Field(default_factory=list)
    postprocess: List[str] = Field(default_factory=list)
    units: Dict[str, str] = Field(default_factory=lambda: {"set": "set", "sample": "sample"})
    # send the paper text with long runs of layout spaces collapsed (-20% tokens; tables go
    # as images anyway)
    compact_text: bool = False
    # focused search plans each paper's rows like a full extraction by default (focused_search.py)
    focused_row_plan: bool = False
    # categories of suggested new variables beyond the shared ones (variable_categories.py)
    variable_categories: List[dict] = Field(default_factory=list)
    # columns (and patterns, table_order) the pack puts in a category -- its own or a shared one -- for the
    # column order of the CSV and the Rows tab (column_order.py)
    category_columns: Dict[str, dict] = Field(default_factory=dict)
    # the template a new pack is copied from (packs/_template/): hidden from every list of packs
    is_template: bool = False
    # calculations declared without code: [{column, expression, description, if_present}] (formulas.py)
    formulas: List[dict] = Field(default_factory=list)
    # columns the paper's experiments share (calculators/shared_values.py): {categories, columns, patterns, exclude}
    shared_columns: dict = Field(default_factory=dict)
    # ... within a group of related rows (an experiment set, a figure / table), and related column pairs
    group_columns: dict = Field(default_factory=dict)
    column_pairs: List[List[str]] = Field(default_factory=list)
    # shared modules the pack uses (parameter_extractor/modules/), linked in when the pack loads
    modules: List[str] = Field(default_factory=list)
    # the pack's changes to its modules' defaults (module_settings.py): {module id: {steps, parameters, ...}}
    module_settings: Dict[str, dict] = Field(default_factory=dict)


SHARED_CATEGORY_IDS = {"metadata", "methodology", "other"}


def _module_columns(mod) -> List[str]:
    """The columns a module's stages and standard columns fill (read from its files)."""
    cols = [e["column"] for e in mod.manifest.standard_columns]
    for path in mod.stage_files():
        try:
            cols += [p["column"] for p in json.loads(path.read_text()).get("parameters", [])]
        except (ValueError, OSError):
            pass
    return cols


def merged_manifest(own: PackManifest, mods) -> PackManifest:
    """The pack's manifest with its modules merged in: their steps and calculations added, their categories added
    unless the pack has one with the same id or the same review sources (the pack's own wins), their category
    columns added to the categories that exist. The pack's own entries keep their places."""
    from parameter_extractor import module_settings as ms
    m = own.model_copy(deep=True)
    for mod in mods:
        mm = mod.manifest
        settings = ms.settings_for(own.module_settings, mod.id)
        names = ms.renames(mod, settings)
        m.builtin_stages += [x for x in mm.builtin_stages if x not in m.builtin_stages]
        m.postprocess += [x for x in mm.postprocess if x not in m.postprocess and x not in settings.calculations_off]
        placed = {c for e in m.category_columns.values() for c in e.get("columns", [])}
        for cat in mm.variable_categories:
            ids = {c.get("id") for c in m.variable_categories}
            sources = {s for c in m.variable_categories for s in c.get("sources", []) or []}
            if cat["id"] in ids or set(cat.get("sources", []) or []) & sources:
                continue
            # nothing left for it to hold: the pack places every module column the category would take (prebiotic
            # puts the wet-dry columns in its conditions block)
            patterns = [re.compile(p) for p in mm.category_columns.get(cat["id"], {}).get("patterns", [])]
            mine = [c for c in _module_columns(mod) if any(p.search(c) for p in patterns)]
            if mine and all(c in placed for c in mine) and not cat.get("sources"):
                continue
            m.variable_categories.append(dict(cat, module=mod.id))
        ids = {c.get("id") for c in m.variable_categories} | SHARED_CATEGORY_IDS
        for cid, entry in ms.apply_to_category_columns(mm.category_columns, names).items():
            if cid not in ids:
                continue
            target = m.category_columns.setdefault(cid, {})
            for key in ("columns", "patterns"):
                if entry.get(key):
                    have = target.setdefault(key, [])
                    have += [x for x in entry[key] if x not in have]
    return m


class Pack:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.own_manifest = PackManifest.model_validate_json((self.folder / "pack.json").read_text())
        from parameter_extractor import modules as _modules
        self.modules = _modules.resolve(self.own_manifest.modules)
        self.manifest = merged_manifest(self.own_manifest, self.modules) if self.modules else self.own_manifest

    def module_ids(self) -> List[str]:
        return [m.id for m in self.modules]

    def file(self, name: str) -> Optional[Path]:
        """A data file the pack or one of its modules provides (analysis_vocab.json): the pack's own wins."""
        own = self.folder / name
        if own.is_file():
            return own
        for mod in self.modules:
            if (found := mod.file(name)) is not None:
                return found
        return None

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def label(self) -> str:
        return self.manifest.label

    def uses(self, feature: str) -> bool:
        """A built-in stage or a post-processing step this pack declares."""
        return feature in self.manifest.builtin_stages or feature in self.manifest.postprocess

    @cached_property
    def _template(self) -> dict:
        return json.loads((self.folder / self.manifest.template).read_text())

    @property
    def template_columns(self) -> List[str]:
        return list(self._template["all_columns"])

    @property
    def species_names(self) -> List[str]:
        return list(self._template.get("species_names", []))

    @property
    def vocab(self) -> dict:
        """The template as the pipeline has always passed it around."""
        return {"all_columns": self.template_columns, "species_names": self.species_names}

    @cached_property
    def standard_column_entries(self) -> List[dict]:
        """The columns every pack gets (packs/common_columns.json: which paper a row comes from),
        then the pack's own standard columns -- leaving out any its template already has."""
        own = []
        if self.manifest.standard_columns:
            path = self.folder / self.manifest.standard_columns
            own = json.loads(path.read_text())["columns"] if path.is_file() else []
        template, out = set(self.template_columns), []
        from_modules = [e for mod in self.modules for e in mod.manifest.standard_columns]
        for entry in common_columns() + own + from_modules:
            if entry["column"] not in template and entry["column"] not in {e["column"] for e in out}:
                out.append(entry)
        return out

    @property
    def species_cids_path(self) -> Optional[Path]:
        return self.folder / self.manifest.species_cids if self.manifest.species_cids else None

    @property
    def stages_dir(self) -> Path:
        return self.folder / "stages"

    def prompt_rules(self, name: str) -> str:
        """The pack's extra rules for a shared prompt (prompts/<name>.rules.md), then its modules' row rules (for the
        row planner), or ''."""
        path = self.folder / "prompts" / f"{name}.rules.md"
        text = path.read_text() if path.is_file() else ""
        if name == "structure_planner":
            from parameter_extractor import module_settings as ms
            extra = [r for mod in self.modules for r in mod.manifest.row_rules if r not in text
                     and r not in ms.settings_for(self.own_manifest.module_settings, mod.id).row_rules_off]
            if extra:
                text = (text.rstrip() + "\n" if text.strip() else "") + "".join(f"- {r}\n" for r in extra)
        return text

    def module_prompt_rules(self, name: str) -> str:
        """The rules the pack's modules add to a built-in step's prompt ('- rule' lines for its {{MODULE_RULES}} slot),
        minus the ones the pack's module settings leave out."""
        from parameter_extractor import module_settings as ms
        lines = []
        for mod in self.modules:
            off = ms.settings_for(self.own_manifest.module_settings, mod.id).prompt_rules_off
            lines += [f"- {r}" for r in mod.manifest.prompt_rules.get(name, []) if r not in off]
        return "\n".join(lines)

    def prompt_path(self, name: str) -> Path:
        """The pack's own prompt, else one of its modules', else the app's generic one."""
        own = self.folder / "prompts" / f"{name}.md"
        if own.is_file():
            return own
        for mod in self.modules:
            if (found := mod.file(f"prompts/{name}.md")) is not None:
                return found
        from parameter_extractor.config import settings
        return settings.PROMPTS_DIR / f"{name}.md"


def row_word(pack: Optional["Pack"] = None) -> str:
    """What the active pack calls one row in messages ('object model instance' for exoplanets)."""
    return (pack or current()).manifest.units.get("row", "row")


COMMON_COLUMNS = BUILTIN_DIR / "common_columns.json"


def common_columns() -> List[dict]:
    """[{column, description}] every pack gets (bibliographic metadata, the arXiv version read)."""
    return json.loads(COMMON_COLUMNS.read_text())["columns"]


def user_packs_dir() -> Path:
    from parameter_extractor.registry import default_registry_path
    return default_registry_path().parent / "packs"


_extra_dirs: List[Path] = []          # more places to look (tests)


def available(include_template: bool = False) -> Dict[str, Pack]:
    """Every pack found, by id: the app's own first, then the user's (which can't
    replace a built-in one). The template pack only with `include_template`."""
    found: Dict[str, Pack] = {}
    for base in [BUILTIN_DIR, user_packs_dir(), *_extra_dirs]:
        if not base.is_dir():
            continue
        for manifest in sorted(base.glob("*/pack.json")):
            try:
                pack = Pack(manifest.parent)
            except (ValueError, OSError):
                continue                     # a broken user pack shouldn't stop the app
            if pack.manifest.is_template and not include_template:
                continue
            found.setdefault(pack.id, pack)
    return found


TEMPLATE_DIR = BUILTIN_DIR / "_template"
PACK_ID = re.compile(r"[a-z][a-z0-9_]{1,40}")


def template_pack() -> Pack:
    """The template every new pack starts from (packs/_template/)."""
    return Pack(TEMPLATE_DIR)


def create_pack(pack_id: str, label: str, description: str = "", base: Optional[Path] = None,
                source: Optional[Pack] = None, units: Optional[Dict[str, str]] = None) -> Pack:
    """A new data pack: a copy of the template pack (or of `source`, another pack -- the way to change one of
    the app's own) in `base` (default the user's packs folder) with its own id, label, description and, given
    `units`, words for a set / a row. The copy is a working pack straight away, to be edited into the new area's
    own (Data Packs menu). Raises ValueError for a bad or taken id."""
    import shutil
    if not PACK_ID.fullmatch(pack_id or ""):
        raise ValueError(f"'{pack_id}' isn't a usable id: lower-case letters, digits and '_', starting with a letter "
                         f"(2-41 characters).")
    if pack_id in available(include_template=True):
        raise ValueError(f"A data pack with the id '{pack_id}' already exists.")
    if not (label or "").strip():
        raise ValueError("Give the data pack a name.")
    folder = Path(base or user_packs_dir()) / pack_id
    if folder.exists():
        raise ValueError(f"The folder {folder} already exists.")
    shutil.copytree((source.folder if source is not None else TEMPLATE_DIR), folder,
                    ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    manifest = json.loads((folder / "pack.json").read_text())
    manifest.update(id=pack_id, label=label.strip(), description=description.strip(), is_template=False)
    if units:
        manifest["units"] = {**manifest.get("units", {}), **{k: v.strip() for k, v in units.items() if v.strip()}}
    (folder / "pack.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return Pack(folder)


_current: Optional[Pack] = None


def activate(pack_id: Optional[str] = None) -> Pack:
    """Make a pack the active one (pipeline._start does this for every run)."""
    global _current
    pack_id = pack_id or DEFAULT_PACK
    if _current is not None and _current.id == pack_id:
        return _current
    packs = available(include_template=True)      # (the template only when asked for by id: tests, checks)
    if pack_id not in packs:
        raise ValueError(f"Unknown domain pack '{pack_id}'. Available: {', '.join(sorted(packs))}")
    _current = packs[pack_id]
    return _current


def current() -> Pack:
    return _current if _current is not None else activate(DEFAULT_PACK)


def delete_pack(pack_id: str) -> Path:
    """Remove one of the user's data packs: its folder is deleted (Data Packs > Remove data pack, after two
    confirmations). The app's own packs and the template can't be removed. Remembered variables and categories kept
    under its id stay in the registry (harmless; they come back if an area with that id is made again). Returns the
    folder removed."""
    import shutil
    pack = available().get(pack_id)
    if pack is None:
        raise ValueError(f"There is no data pack '{pack_id}'.")
    folder = Path(pack.folder).resolve()
    if pack.manifest.is_template or folder == BUILTIN_DIR.resolve() or BUILTIN_DIR.resolve() in folder.parents:
        raise PermissionError(f"'{pack.label}' is part of the app and can't be removed.")
    global _current
    if _current is not None and _current.id == pack_id:
        _current = None                      # the default becomes active again on the next use
    shutil.rmtree(folder)
    from parameter_extractor.stages import optional
    optional._specs_in.cache_clear()
    optional._pack_specs.cache_clear()
    return folder


def add_search_dir(path: Path) -> None:
    """Also look for packs in `path` (used by tests)."""
    if Path(path) not in _extra_dirs:
        _extra_dirs.append(Path(path))
