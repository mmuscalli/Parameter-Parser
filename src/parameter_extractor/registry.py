"""
The variable registry: which columns exist, and which extracted names map to
them.

  - Base list (bundled, read-only): PaperDataTemplate's 280 columns, from
    schemas/template_vocab.json. The app never edits the template.
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


def _alias_key(kind: str, name: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip().lower())
    return f"{kind}:{normalized}"


def suggest_column_name(kind: str, name: str, role: Optional[str] = None) -> str:
    """A column name for a new variable in the template's style."""
    slug = re.sub(r"[^A-Za-z0-9+\-]+", "_", name.strip()).strip("_")
    if kind == "species":
        return f"{role or 'initial'}_{slug}_aq_mM"
    return slug.lower()


class VariableRegistry:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        vocab = json.loads(_TEMPLATE_VOCAB.read_text())
        self.template_columns = list(vocab["all_columns"])
        self._template_set: Set[str] = set(self.template_columns)
        self.added_columns: Dict[str, dict] = {}     # column -> {kind, added, note}
        self.aliases: Dict[str, str] = {}            # "kind:name" -> column
        if self.path and self.path.is_file():
            data = json.loads(self.path.read_text())
            self.added_columns = data.get("columns", {})
            self.aliases = data.get("aliases", {})

    # ---- lookups -------------------------------------------------------------

    def is_known_column(self, column: Optional[str]) -> bool:
        return bool(column) and (column in self._template_set or column in self.added_columns)

    def is_template_column(self, column: str) -> bool:
        return column in self._template_set

    def known_columns(self) -> list:
        return self.template_columns + sorted(self.added_columns)

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
        if not self.is_template_column(column) and column not in self.added_columns:
            self.added_columns[column] = {"kind": kind, "added": date.today().isoformat(), "note": note}

    def add_alias(self, kind: str, name: str, column: str) -> None:
        self.aliases[_alias_key(kind, name)] = column

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"columns": self.added_columns, "aliases": self.aliases},
                                        indent=2, ensure_ascii=False, sort_keys=True))
