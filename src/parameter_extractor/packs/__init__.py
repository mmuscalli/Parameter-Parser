"""
Domain packs: everything that ties the app to one research area, kept out of
the code so another area is a new folder, not a rewrite.

A pack is a folder with a pack.json manifest:

  id, label, description, version
  template          JSON with "all_columns" (the dataset's columns, in order) and
                    "species_names" (the species vocabulary, if any)
  standard_columns  JSON {"columns": [{"column", "description"}]}: columns the app
                    adds beyond the template (optional)
  species_cids      PubChem CIDs of the template's species (optional; pubchem.py)
  builtin_stages    code stages the pack uses: "methodology", "chemistry" (the rest
                    of a pack's extraction is its optional-stage specs)
  postprocess       calculators run on the results, in order: "normalize_species",
                    "mixing", "molar_ratios", "peptide_totals"
  units             what a set and a sample are called, e.g. {"set": "planetary
                    system", "sample": "planet"}
  compact_text      collapse long runs of layout spaces in the text sent to the model

and, next to it:
  prompts/*.md      the pack's prompts (structure_planner, figure_planner, ...); a
                    prompt the pack doesn't have comes from the app's own prompts/
  stages/*.json     its optional stages (stages/optional.py)

Packs are found in the app's own packs/ folder and in the user's
<app data>/packs/ (so a new area needs no code changes). The active pack is
set at the start of each run (pipeline._start) from RunConfig.pack; code that
needs the template, vocabulary, prompts or stages asks `current()`.
"""
from __future__ import annotations
import json
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


class Pack:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.manifest = PackManifest.model_validate_json((self.folder / "pack.json").read_text())

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
        if not self.manifest.standard_columns:
            return []
        path = self.folder / self.manifest.standard_columns
        return json.loads(path.read_text())["columns"] if path.is_file() else []

    @property
    def species_cids_path(self) -> Optional[Path]:
        return self.folder / self.manifest.species_cids if self.manifest.species_cids else None

    @property
    def stages_dir(self) -> Path:
        return self.folder / "stages"

    def prompt_path(self, name: str) -> Path:
        """The pack's own prompt, else the app's generic one."""
        own = self.folder / "prompts" / f"{name}.md"
        if own.is_file():
            return own
        from parameter_extractor.config import settings
        return settings.PROMPTS_DIR / f"{name}.md"


def user_packs_dir() -> Path:
    from parameter_extractor.registry import default_registry_path
    return default_registry_path().parent / "packs"


_extra_dirs: List[Path] = []          # more places to look (tests)


def available() -> Dict[str, Pack]:
    """Every pack found, by id: the app's own first, then the user's (which can't
    replace a built-in one)."""
    found: Dict[str, Pack] = {}
    for base in [BUILTIN_DIR, user_packs_dir(), *_extra_dirs]:
        if not base.is_dir():
            continue
        for manifest in sorted(base.glob("*/pack.json")):
            try:
                pack = Pack(manifest.parent)
            except (ValueError, OSError):
                continue                     # a broken user pack shouldn't stop the app
            found.setdefault(pack.id, pack)
    return found


_current: Optional[Pack] = None


def activate(pack_id: Optional[str] = None) -> Pack:
    """Make a pack the active one (pipeline._start does this for every run)."""
    global _current
    pack_id = pack_id or DEFAULT_PACK
    if _current is not None and _current.id == pack_id:
        return _current
    packs = available()
    if pack_id not in packs:
        raise ValueError(f"Unknown domain pack '{pack_id}'. Available: {', '.join(sorted(packs))}")
    _current = packs[pack_id]
    return _current


def current() -> Pack:
    return _current if _current is not None else activate(DEFAULT_PACK)


def add_search_dir(path: Path) -> None:
    """Also look for packs in `path` (used by tests)."""
    if Path(path) not in _extra_dirs:
        _extra_dirs.append(Path(path))
