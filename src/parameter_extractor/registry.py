"""
The variable registry: which columns exist, and which extracted names map to
them.

  - Base list (bundled, read-only): PaperDataTemplate's 280 columns, from
    schemas/template_vocab.json (the app never edits the template), plus the
    app's own standard columns from schemas/standard_columns.json (e.g. the
    wet/dry phase conditions).
  - Local additions (per user, a JSON file in the user's app-data folder):
    columns the user accepted in the "Review new variables" screen, and
    aliases -- "this extracted name means that column" -- so the same
    variable is recognised automatically on later runs instead of being
    reviewed again.

Columns added locally are written after the template's block in the CSV.
"""
from __future__ import annotations
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Set

APP_NAME = "Parameter Extractor"
_TEMPLATE_VOCAB = Path(__file__).resolve().parent / "schemas" / "template_vocab.json"
_STANDARD_COLUMNS = Path(__file__).resolve().parent / "schemas" / "standard_columns.json"


def standard_columns() -> list:
    """App-defined standard columns (beyond the template), in their defined order."""
    return [c["column"] for c in json.loads(_STANDARD_COLUMNS.read_text())["columns"]]


def default_registry_path() -> Path:
    """Per-user location: ~/Library/Application Support/Parameter Extractor/ on macOS,
    %APPDATA%\\Parameter Extractor\\ on Windows, ~/.local/share/parameter-extractor/ elsewhere."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "parameter-extractor"
    return base / "variable_registry.json"


def default_pubchem_cache_path() -> Path:
    """Next to the registry: names already looked up on PubChem."""
    return default_registry_path().parent / "pubchem_cache.json"


def _alias_key(kind: str, name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip().lower())
    return f"{kind}:{normalized}"


def suggest_column_name(kind: str, name: str, role: Optional[str] = None) -> str:
    """A column name for a new variable in the template's style."""
    slug = re.sub(r"[^A-Za-z0-9+\-']+", "_", name.strip()).strip("_")
    if kind == "species":
        return f"{role or 'initial'}_{slug}_aq_mM"
    return slug.lower()


class VariableRegistry:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        vocab = json.loads(_TEMPLATE_VOCAB.read_text())
        self.template_columns = list(vocab["all_columns"])
        self.standard_columns = standard_columns()
        self._template_set: Set[str] = set(self.template_columns)
        self._base_set: Set[str] = self._template_set | set(self.standard_columns)
        self.added_columns: Dict[str, dict] = {}     # column -> {kind, added, note}
        self.aliases: Dict[str, str] = {}            # "kind:name" -> column (name lowercased for matching)
        self.alias_labels: Dict[str, str] = {}       # same key -> the name as first written, for display
        self.species_ids: Dict[str, str] = {}        # PubChem CID -> species name accepted in a review
        self._changed = False
        if self.path and self.path.is_file():
            data = json.loads(self.path.read_text())
            self.added_columns = data.get("columns", {})
            self.aliases = data.get("aliases", {})
            self.alias_labels = data.get("alias_labels", {})
            self.species_ids = data.get("species_ids", {})

    # ---- lookups -------------------------------------------------------------

    def is_known_column(self, column: Optional[str]) -> bool:
        if not column:
            return False
        if column in self._base_set or column in self.added_columns:
            return True
        # a species' stock-solution concentration goes with its starting concentration:
        # stock_X_aq_mM is known wherever initial_X_aq_mM is
        return column.startswith("stock_") and self.is_known_column("initial_" + column.removeprefix("stock_"))

    def is_template_column(self, column: str) -> bool:
        return column in self._template_set

    def known_columns(self) -> list:
        return self.template_columns + self.standard_columns + sorted(self.added_columns)

    def alias_for(self, kind: str, name: str) -> Optional[str]:
        """The column the user mapped this (kind, name) to, if it still exists."""
        column = self.aliases.get(_alias_key(kind, name))
        return column if self.is_known_column(column) else None

    def column_for(self, kind: str, name: str, proposed: Optional[str] = None) -> Optional[str]:
        """The column a (kind, name) belongs in: an alias the user accepted
        earlier, else the proposed column if that's a known one, else None
        (still a new variable)."""
        column = self.aliases.get(_alias_key(kind, name))
        if column and self.is_known_column(column):
            return column
        return proposed if self.is_known_column(proposed) else None

    # ---- additions (from the review screen) -----------------------------------

    def add_column(self, column: str, kind: str, note: str = "") -> None:
        if column not in self._base_set and column not in self.added_columns:
            self.added_columns[column] = {"kind": kind, "added": date.today().isoformat(), "note": note}
            self._changed = True

    def add_alias(self, kind: str, name: str, column: str) -> None:
        key = _alias_key(kind, name)
        self.aliases[key] = column
        self.alias_labels.setdefault(key, name.strip())
        self._changed = True

    def species_for_cid(self, cid: int) -> Optional[str]:
        """The name a species with this PubChem CID was accepted under, if its
        aliases still exist -- so a different name for the same compound in a
        later paper lands in the same column."""
        name = self.species_ids.get(str(cid))
        if name and any(self.split_alias(k)[1].split(" ", 1)[-1].removesuffix(" %") == name.lower()
                        for k in self.aliases if k.startswith("species:")):
            return name
        return None

    def remember_species_id(self, cid: int, name: str) -> None:
        if cid and self.species_ids.get(str(cid)) is None:
            self.species_ids[str(cid)] = name
            self._changed = True

    # ---- managing local additions (the "Remembered variables" window) ------------

    @staticmethod
    def split_alias(key: str):
        """'parameter:stirring rate' -> ('parameter', 'stirring rate')."""
        kind, _, name = key.partition(":")
        return kind, name

    def display_name(self, key: str) -> str:
        """Readable name for an alias: 'RbCl (starting concentration)', 'stirring rate'."""
        kind, name = self.split_alias(key)
        label = self.alias_labels.get(key, name)
        if kind == "species":
            parts = label.split(" ", 1)
            if len(parts) == 2 and parts[0] in ("initial", "sampled", "stock"):
                role, species = parts
                pct = species.endswith(" %")
                species = species.removesuffix(" %")
                what = {"initial": "starting concentration", "stock": "stock solution, before mixing"}.get(
                    role, "measured, % yield" if pct else "measured")
                return f"{species} ({what})"
        return label

    def aliases_to(self, column: str) -> list:
        return sorted(k for k, c in self.aliases.items() if c == column)

    def set_alias_column(self, key: str, column: str) -> None:
        if self.aliases.get(key) != column:
            self.aliases[key] = column
            self._changed = True

    def remove_alias(self, key: str) -> None:
        if self.aliases.pop(key, None) is not None:
            self.alias_labels.pop(key, None)
            self._changed = True

    def remove_column(self, column: str) -> list:
        """Forget an added column and every alias pointing to it (those variables will
        be reviewed again). Template and standard columns can't be removed. Returns
        the aliases removed."""
        if column not in self.added_columns:
            return []
        del self.added_columns[column]
        removed = self.aliases_to(column)
        for k in removed:
            del self.aliases[k]
            self.alias_labels.pop(k, None)
        # identities whose names no longer point anywhere are forgotten too
        self.species_ids = {cid: n for cid, n in self.species_ids.items() if self.species_for_cid(int(cid))}
        self._changed = True
        return removed

    def rename_column(self, old: str, new: str) -> None:
        """Rename an added column; aliases follow. Fails if `new` already exists."""
        if old not in self.added_columns:
            raise ValueError(f"'{old}' isn't a column you added.")
        if self.is_known_column(new):
            raise ValueError(f"A column called '{new}' already exists.")
        self.added_columns[new] = self.added_columns.pop(old)
        for k, c in list(self.aliases.items()):
            if c == old:
                self.aliases[k] = new
        self._changed = True

    def save(self) -> None:
        """Writes the local additions -- only if something was actually added."""
        if self.path is None or not self._changed:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"columns": self.added_columns, "aliases": self.aliases,
                                         "alias_labels": self.alias_labels, "species_ids": self.species_ids},
                                        indent=2, ensure_ascii=False, sort_keys=True))
