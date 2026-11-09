"""
Modules: parts of a data pack kept in ONE place and linked into every pack that uses them (Mickey, 2026-11-09: a
reference-based design, so an improvement to a module reaches every pack, and no pack carries its own slightly
different copy).

A module is a folder with a module.json:

  id, label, description, version
  covers             what the module records, in a sentence for drafting a pack (the design leaves those out)
  builtin_stages     code steps it switches on ("analysis", "chemistry")
  postprocess        calculations it switches on ("amounts", "peptide_totals", ...)
  stages/*.json      its own optional stages (kinetics, wet-dry), run like a pack's
  needs              other modules it brings along (product_totals -> solution_chemistry)
  variable_categories / category_columns
                     column blocks for its columns (a pack's own category with the same id, or with the same review
                     sources, wins -- the module's is left out)
  standard_columns   [{column, description}] columns it fills that aren't stage parameters
  pack_parameters    parameters the pack's first always-on stage gets when no stage of the pack has the column
                     (solution chemistry needs the reaction volume and the solvent)
  stage_rules        rules added to each of the pack's own stages
  stage_hints        hint_by_stage entries for the pack's open-ended stages that don't have one for that step
  row_rules          rules for planning rows (added to the pack's structure_planner rules)
  fixed              {column: why} columns the app's calculations read by name (their unit can't be changed in a
                     pack's module settings -- module_settings.py)

and, next to it, files a pack can't do without when it uses the module: prompts/*.md (the chemistry step's prompt),
analysis_vocab.json (the analysis step's techniques). A pack's own file of the same name wins.

Modules ship with the app (this folder); the loader also reads <app data>/modules/ for the user's own.
A pack lists the ones it uses in pack.json: "modules": ["analysis", "solution_chemistry"]. packs.Pack merges them
when it loads (its `manifest` is the merged one, `own_manifest` the file's).
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

BUILTIN_DIR = Path(__file__).resolve().parent


class ModuleManifest(BaseModel):
    id: str
    label: str
    description: str = ""
    covers: str = ""                # what it records, for drafting a pack (pack_drafting: don't design those again)
    version: int = 1
    builtin_stages: List[str] = Field(default_factory=list)
    postprocess: List[str] = Field(default_factory=list)
    needs: List[str] = Field(default_factory=list)
    variable_categories: List[dict] = Field(default_factory=list)
    category_columns: Dict[str, dict] = Field(default_factory=dict)
    standard_columns: List[dict] = Field(default_factory=list)
    pack_parameters: List[dict] = Field(default_factory=list)
    stage_rules: List[str] = Field(default_factory=list)
    stage_hints: Dict[str, dict] = Field(default_factory=dict)
    row_rules: List[str] = Field(default_factory=list)
    # columns the app's own code reads by name: {column: why} -- a pack's module settings can't change their unit
    fixed: Dict[str, str] = Field(default_factory=dict)


class Module:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.manifest = ModuleManifest.model_validate_json((self.folder / "module.json").read_text())

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def label(self) -> str:
        return self.manifest.label

    @property
    def stages_dir(self) -> Path:
        return self.folder / "stages"

    @property
    def builtin(self) -> bool:
        return BUILTIN_DIR in self.folder.parents

    def file(self, name: str) -> Optional[Path]:
        path = self.folder / name
        return path if path.is_file() else None

    def stage_files(self) -> List[Path]:
        return sorted(self.stages_dir.glob("*.json")) if self.stages_dir.is_dir() else []


def user_modules_dir() -> Path:
    from parameter_extractor.registry import default_registry_path
    return default_registry_path().parent / "modules"


_extra_dirs: List[Path] = []          # more places to look (tests)


def available() -> Dict[str, Module]:
    """Every module found, by id: the app's own first, then the user's (which can't replace one of the app's)."""
    return dict(_available(tuple(str(d) for d in [BUILTIN_DIR, user_modules_dir(), *_extra_dirs])))


@lru_cache(maxsize=8)
def _available(dirs: tuple) -> tuple:
    found: Dict[str, Module] = {}
    for base in map(Path, dirs):
        if not base.is_dir():
            continue
        for manifest in sorted(base.glob("*/module.json")):
            try:
                module = Module(manifest.parent)
            except (ValueError, OSError):
                continue                     # a broken user module shouldn't stop the app
            found.setdefault(module.id, module)
    return tuple(found.items())


def clear_cache() -> None:
    _available.cache_clear()


def resolve(ids: List[str]) -> List[Module]:
    """The modules for a pack's list, with what they need (before them), each once; unknown ids are skipped (the
    pack's check reports them)."""
    found = available()
    out: List[Module] = []

    def add(mid: str, seen: tuple = ()) -> None:
        if mid in seen or any(m.id == mid for m in out) or mid not in found:
            return
        for need in found[mid].manifest.needs:
            add(need, seen + (mid,))
        out.append(found[mid])
    for mid in ids:
        add(mid)
    return out


def unknown(ids: List[str]) -> List[str]:
    found = available()
    return [m for m in ids if m not in found]
