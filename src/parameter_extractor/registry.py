"""
The variable registry: which columns exist, and which extracted names map to
them.

  - Base list (bundled, read-only): the active domain pack's template columns
    (prebiotic chemistry: PaperDataTemplate's 280, which the app never edits)
    plus its standard columns and its optional stages' columns (packs/).
  - Local additions (per user, a JSON file in the user's app-data folder):
    columns the user accepted in the "Review new variables" screen, and
    aliases -- "this extracted name means that column" -- so the same
    variable is recognised automatically on later runs instead of being
    reviewed again.
  - Research areas (2026-11-03): every added column and synonym belongs to one pack, or to Standard (every
    pack); a registry object is one pack's view (`for_pack` for another's). The file also keeps the user's
    choices for built-in columns (data type, category) and their variable-category edits.

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


def standard_columns(pack=None) -> list:
    """App-defined standard columns (beyond the template), in their defined order: the
    ones the pack (default: the active one) lists (packs/), then its optional stages' parameter
    columns that aren't template columns (the pack's stages/*.json), in spec order."""
    from parameter_extractor.packs import current
    from parameter_extractor.stages.optional import spec_standard_columns
    pack = pack or current()
    listed = [c["column"] for c in pack.standard_column_entries]
    template = set(pack.template_columns)
    extra = list(spec_standard_columns(pack))
    if pack.uses("fit_models"):                 # exoplanets: how the values were obtained
        from parameter_extractor.calculators.exoplanet_fits import fit_columns
        extra += fit_columns(pack)
    for column, _ in extra:
        if column not in template and column not in listed:
            listed.append(column)
    return listed


# research area of columns, synonyms and categories every pack shares (2026-11-03): the rest belong to one pack
STANDARD = "standard"
STANDARD_LABEL = "Standard (every research area)"


def area_label(area: str) -> str:
    if area == STANDARD:
        return STANDARD_LABEL
    from parameter_extractor.packs import available
    pack = available().get(area)
    return pack.label if pack else area


def areas() -> list:
    """[(id, label)]: Standard first, then every pack."""
    from parameter_extractor.packs import available
    return [(STANDARD, STANDARD_LABEL)] + [(p.id, p.label) for p in available().values()]


def common_column_names() -> list:
    from parameter_extractor.packs import common_columns
    return [c["column"] for c in common_columns()]


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


_COMPOUND_COLUMN = re.compile(r"(?:initial|sampled)_(?P<name>.+)_(?:aq|gas|s)(?:_avg)?_(?:mM|%yield|%recovered)")


def is_peptide_column(column: str) -> bool:
    """A compound column of a peptide named by the convention (names.peptide_name; Mickey, 2026-11-04):
    '<role>_<sequence>_<phase>_<mM|%yield>' -- 'sampled_Gly-Gly_aq_%yield', 'sampled_(Gly)10_aq_mM',
    'sampled_Gly-Ala-Ala_aq_mM', 'sampled_cyclo_Gly-Gly_aq_mM' -- any length >= 2 and any sequence, written in
    the convention's own form. Used to find a row's peptides (calculators/peptide_totals.py); NOT a reason to
    accept the column -- a peptide outside the pack's vocabulary is reviewed like any new compound (2026-11-04)."""
    from parameter_extractor.names import cyclic_name, peptide_codes, peptide_name
    m = _COMPOUND_COLUMN.fullmatch(column or "")
    if not m:
        return False
    name = m.group("name")
    cyclic = name.startswith("cyclo_")
    codes = peptide_codes(name.removeprefix("cyclo_"))
    if not codes or len(codes) < 2:
        return False
    return name == (cyclic_name(codes) if cyclic else peptide_name(codes))


_OLIGO_COLUMN = re.compile(r"(?:initial|sampled)_\d{1,3}mer_(?P<letters>d?[ACGTU]+)_(?:aq|gas|s)(?:_avg)?_(?:mM|%yield)")


def is_oligonucleotide_column(column: str) -> bool:
    """Columns of the nucleic-acid naming convention (names.oligonucleotide_name; Mickey, 2026-11-03):
    '<role>_<n>mer_<letters>_<phase>_<mM|%yield>' -- 'sampled_4mer_A_aq_%yield', 'sampled_12mer_dT_aq_mM'. Finds a
    row's oligomers (calculators/oligomer_totals.py); not a reason to accept the column (reviewed, 2026-11-04)."""
    m = _OLIGO_COLUMN.fullmatch(column or "")
    if not m:
        return False
    from parameter_extractor.names import oligonucleotide_match
    return oligonucleotide_match(f"1mer_{m.group('letters')}") is not None


def default_arxiv_cache_dir() -> Path:
    """arXiv lookups and full texts kept between runs (ingestion/arxiv_source.LookupCache)."""
    return default_registry_path().parent / "arxiv_cache"


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


class _Store:
    """What the registry file holds, shared by every pack's view of it (VariableRegistry.for_pack)."""

    def __init__(self, path: Optional[Path]):
        self.columns: Dict[str, dict] = {}        # column -> {kind, added, note, pack, category, type}
        self.aliases: Dict[str, str] = {}         # "kind:name" -> column (name lowercased for matching)
        self.alias_labels: Dict[str, str] = {}    # same key -> the name as first written, for display
        self.alias_areas: Dict[str, str] = {}     # same key -> research area (pack id or 'standard')
        self.species_ids: Dict[str, str] = {}     # PubChem CID -> species name accepted in a review
        self.builtin: Dict[str, Dict[str, dict]] = {}   # area -> built-in column -> {type, category} chosen
        self.categories: Dict[str, dict] = {}     # area -> {"added": [...], "changed": {id: {...}}}
        self.compounds: Dict[str, Dict[str, dict]] = {}   # area -> name -> {cid, synonyms, active} (compound_names)
        self.changed = False
        self.migrated = False
        self.path = path
        if path and path.is_file():
            data = json.loads(path.read_text())
            self.columns = data.get("columns", {})
            self.aliases = data.get("aliases", {})
            self.alias_labels = data.get("alias_labels", {})
            self.alias_areas = data.get("alias_areas", {})
            self.species_ids = data.get("species_ids", {})
            self.builtin = data.get("builtin_columns", {})
            self.categories = data.get("categories", {})
            self.compounds = data.get("compounds", {})
            self.migrated = self._migrate_compound_columns()

    def _migrate_compound_columns(self) -> bool:
        """Columns remembered before 2026-11-04 in the old compound format ('sampled_2peptide_Gly_%yield',
        'initial_Gly_mM', 'sampled_Foo_%yield') -> the current one (flatten_to_template.current_column_name);
        old peptide names of compounds -> sequences. True when something changed (saved with a backup)."""
        from parameter_extractor.ingestion.flatten_to_template import current_column_name as new
        from parameter_extractor.names import match_species
        def name(n):
            if re.fullmatch(r"\d+peptide_[A-Z][a-z]{2}|DKP_[A-Z][a-z]{2}", n or ""):
                return (match_species(n) or (n,))[0]
            return n
        before = json.dumps([self.columns, self.aliases, self.builtin, self.compounds, self.species_ids], sort_keys=True)
        self.columns = {new(c): info for c, info in self.columns.items()}
        self.aliases = {k: new(c) for k, c in self.aliases.items()}
        self.builtin = {a: {new(c): v for c, v in cols.items()} for a, cols in self.builtin.items()}
        self.compounds = {a: {name(n): v for n, v in names.items()} for a, names in self.compounds.items()}
        self.species_ids = {cid: name(n) for cid, n in self.species_ids.items()}
        changed = before != json.dumps([self.columns, self.aliases, self.builtin, self.compounds, self.species_ids],
                                       sort_keys=True)
        self.changed = self.changed or changed
        return changed


class VariableRegistry:
    """One research area's view of the registry: the pack's built-in columns, plus the columns and synonyms
    remembered for that pack or for every pack (STANDARD). Entries remembered before research areas existed
    count as Standard. `all_columns` / `all_aliases` hold every area's."""

    def __init__(self, path: Optional[Path] = None, pack=None, _store: Optional[_Store] = None):
        self.path = Path(path) if path else None
        from parameter_extractor.packs import available, current
        self.pack = available()[pack] if isinstance(pack, str) else (pack or current())
        self.pack_id = self.pack.id
        self.template_columns = self.pack.template_columns
        self.standard_columns = standard_columns(self.pack)
        self._template_set: Set[str] = set(self.template_columns)
        self._base_set: Set[str] = self._template_set | set(self.standard_columns)
        self._store = _store or _Store(self.path)

    def for_pack(self, pack) -> "VariableRegistry":
        """Another research area's view of the same registry (edits are shared; one save writes them)."""
        return VariableRegistry(self.path, pack, _store=self._store)

    # ---- the stored data -------------------------------------------------------

    all_columns = property(lambda self: self._store.columns)
    all_aliases = property(lambda self: self._store.aliases)
    alias_labels = property(lambda self: self._store.alias_labels)
    species_ids = property(lambda self: self._store.species_ids)
    local_categories = property(lambda self: self._store.categories)

    @property
    def _changed(self) -> bool:
        return self._store.changed

    @_changed.setter
    def _changed(self, value: bool) -> None:
        self._store.changed = value

    def column_area(self, column: str) -> str:
        return (self._store.columns.get(column) or {}).get("pack", STANDARD)

    def alias_area(self, key: str) -> str:
        if key in self._store.alias_areas:
            return self._store.alias_areas[key]
        target = self._store.aliases.get(key)
        return self.column_area(target) if target in self._store.columns else STANDARD

    def in_scope(self, area: str) -> bool:
        return area in (STANDARD, self.pack_id)

    @property
    def added_columns(self) -> Dict[str, dict]:
        """Columns remembered for this pack or for every pack (the info dicts themselves: edits stick)."""
        return {c: info for c, info in self._store.columns.items() if self.in_scope(info.get("pack", STANDARD))}

    @property
    def aliases(self) -> Dict[str, str]:
        return {k: c for k, c in self._store.aliases.items() if self.in_scope(self.alias_area(k))}

    # ---- lookups -------------------------------------------------------------

    def is_known_column(self, column: Optional[str]) -> bool:
        if not column:
            return False
        if column in self._base_set or column in self.added_columns:
            return True
        # no automatic acceptance by naming rule: a new compound of ANY type -- peptide, oligonucleotide, ... -- is
        # reviewed (Mickey, 2026-11-04); only the pack's own columns and the user's accepted ones are known
        # the uncertainty of a known value ('<column>_err_plus' / '_err_minus', the prebiotic pack's naming)
        m = re.fullmatch(r"(.+)_err_(?:plus|minus)", column)
        if m and self.is_known_column(m.group(1)):
            return True
        # a range of a known quantity ('<name>_range_<unit>', 'low:high') is the same variable (2026-10-31)
        if "_range" in column:
            from parameter_extractor.ingestion.flatten_to_template import without_range
            if (base := without_range(column)) != column and self.is_known_column(base):
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

    def add_column(self, column: str, kind: str, note: str = "", category: str = "", value_type: str = "",
                   area: str = "") -> None:
        """Remember a column accepted in a review, for this pack (or `area`: another pack, or STANDARD). A column
        another pack already remembers becomes Standard (both use it)."""
        if column in self._store.columns and column not in self.added_columns:
            self._store.columns[column]["pack"] = STANDARD
            self._changed = True
        if column not in self._base_set and column not in self.added_columns:
            self._store.columns[column] = {"kind": kind, "added": date.today().isoformat(), "note": note,
                                           "pack": area or self.pack_id,
                                           **({"category": category} if category else {}),
                                           **({"type": value_type} if value_type and value_type != "any" else {})}
            self._changed = True
        elif value_type:
            self.set_column_type(column, value_type)

    def _set_field(self, info: dict, field: str, value: str, empty: str = "") -> None:
        if info.get(field, empty) == (value or empty):
            return
        if value and value != empty:
            info[field] = value
        else:
            info.pop(field, None)
        self._changed = True

    def set_column_type(self, column: str, value_type: str) -> None:
        """The data type values of a column the user added are converted to (value_types.py); 'any' clears
        it. Built-in columns: set_builtin."""
        info = self._store.columns.get(column)
        if info is not None:
            self._set_field(info, "type", value_type, "any")

    def set_column_category(self, column: str, category: str) -> None:
        """The variable category an added column is placed under (column_order.py); '' = by its name."""
        info = self._store.columns.get(column)
        if info is not None:
            self._set_field(info, "category", category)

    def set_column_area(self, column: str, area: str) -> None:
        """Move an added column to another research area (pack id or STANDARD); its synonyms follow."""
        info = self._store.columns.get(column)
        if info is None or info.get("pack", STANDARD) == area:
            return
        info["pack"] = area
        for key in self.aliases_to(column):
            self._store.alias_areas[key] = area
        self._changed = True

    def set_alias_area(self, key: str, area: str) -> None:
        if key in self._store.aliases and self.alias_area(key) != area:
            self._store.alias_areas[key] = area
            self._changed = True

    def add_alias(self, kind: str, name: str, column: str, area: str = "") -> None:
        key = _alias_key(kind, name)
        self._store.aliases[key] = column
        self._store.alias_areas[key] = area or (self.column_area(column) if column in self._store.columns
                                                else self.pack_id)
        self.alias_labels.setdefault(key, name.strip())
        self._changed = True

    # ---- built-in columns: the user's choices (the Remembered variables window) --------

    def builtin_area(self, column: str) -> str:
        """Where a built-in column's choices are kept: STANDARD for the columns every pack has."""
        return STANDARD if column in common_column_names() else self.pack_id

    def builtin_choice(self, column: str) -> dict:
        """{type, category} the user chose for a built-in column of this pack (empty: the defaults)."""
        if column not in self._base_set:
            return {}
        return dict(self._store.builtin.get(self.builtin_area(column), {}).get(column, {}))

    def set_builtin(self, column: str, value_type: Optional[str] = None, category: Optional[str] = None) -> None:
        """Change a built-in column's data type or category ('' = back to the default). Changes how values
        are stored and where the column sits; the pack's prompts and stages are unchanged."""
        if column not in self._base_set:
            raise ValueError(f"'{column}' isn't a built-in column of {self.pack.label}.")
        area = self.builtin_area(column)
        info = self._store.builtin.setdefault(area, {}).setdefault(column, {})
        if value_type is not None:
            self._set_field(info, "type", value_type)
        if category is not None:
            self._set_field(info, "category", category)
        if not info:
            del self._store.builtin[area][column]
            if not self._store.builtin[area]:
                del self._store.builtin[area]

    def chosen_type(self, column: str) -> str:
        """The data type the user chose for a column (added or built-in), or ''."""
        info = self.added_columns.get(column)
        return (info or self.builtin_choice(column)).get("type", "")

    def chosen_categories(self) -> Dict[str, str]:
        """{column: category} the user chose for added columns of this pack."""
        return {c: info["category"] for c, info in self.added_columns.items() if info.get("category")}

    def builtin_categories(self) -> Dict[str, str]:
        """{column: category} the user chose for built-in columns (these win over the pack's own placement)."""
        out = {}
        for area in (STANDARD, self.pack_id):
            for column, info in self._store.builtin.get(area, {}).items():
                if info.get("category") and column in self._base_set:
                    out[column] = info["category"]
        return out

    def builtin_types(self) -> Dict[str, str]:
        out = {}
        for area in (STANDARD, self.pack_id):
            for column, info in self._store.builtin.get(area, {}).items():
                if info.get("type") and column in self._base_set:
                    out[column] = info["type"]
        return out

    # ---- variable categories (the Variable categories window; variable_categories.py applies them) ----

    def set_local_categories(self, area: str, edits: dict) -> None:
        """{"added": [category dicts], "changed": {id: {field: value}}} for one area ('standard' or a pack)."""
        edits = {k: v for k, v in edits.items() if v}
        if self._store.categories.get(area, {}) != edits:
            if edits:
                self._store.categories[area] = edits
            else:
                self._store.categories.pop(area, None)
            self._changed = True

    def species_for_cid(self, cid: int) -> Optional[str]:
        """The name a species with this PubChem CID was accepted under, if its
        aliases still exist -- so a different name for the same compound in a
        later paper lands in the same column."""
        name = self.species_ids.get(str(cid))
        return name if name and self._species_named(name, self.aliases) else None

    def _species_named(self, name: str, aliases) -> bool:
        return any(self.split_alias(k)[1].split(" ", 1)[-1].removesuffix(" %") == name.lower()
                   for k in aliases if k.startswith("species:"))

    def remember_species_id(self, cid: int, name: str) -> None:
        if cid and self.species_ids.get(str(cid)) is None:
            self.species_ids[str(cid)] = name
            self._changed = True

    # ---- compound names (compound_names.py; the Compounds tab) ----------------------

    def compounds(self) -> Dict[str, dict]:
        """{default name: {cid, synonyms, active, area}} remembered for this pack or every pack."""
        out = {}
        for area in (STANDARD, self.pack_id):
            for name, info in self._store.compounds.get(area, {}).items():
                out[name] = {**info, "area": area}
        return out

    def remember_compound(self, name: str, cid: int = 0, synonyms=None, area: str = "") -> None:
        """A compound accepted in a review: its paper name stays the default (and active) name; PubChem's
        synonyms are kept as the other names it can be shown under."""
        if not name:
            return
        entry = self._store.compounds.setdefault(area or self.pack_id, {}).setdefault(name, {})
        before = dict(entry)
        if cid:
            entry["cid"] = int(cid)
        if synonyms:
            entry["synonyms"] = [n for n in dict.fromkeys(synonyms) if n.lower() != name.lower()]
        if entry != before:
            self._changed = True

    def set_active_name(self, name: str, active: str) -> None:
        """The name compound `name` is written under in column names ('' or the default name = the default)."""
        area = next((a for a in (self.pack_id, STANDARD) if name in self._store.compounds.get(a, {})), self.pack_id)
        entry = self._store.compounds.setdefault(area, {}).setdefault(name, {})
        self._set_field(entry, "active", "" if active == name else active)
        if not entry:
            del self._store.compounds[area][name]
            if not self._store.compounds[area]:
                del self._store.compounds[area]

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
                recovered = species.endswith(" % recovered")
                ratio = species.endswith(" ratio")
                pct = species.endswith(" %")
                species = species.removesuffix(" % recovered").removesuffix(" %").removesuffix(" ratio")
                what = {"initial": "starting concentration", "stock": "stock solution, before mixing"}.get(
                    role, "measured, % recovered" if recovered else "measured, ratio" if ratio else
                    "measured, % yield" if pct else "measured")
                return f"{species} ({what})"
        return label

    def aliases_to(self, column: str) -> list:
        """Every synonym pointing to `column` (any research area)."""
        return sorted(k for k, c in self._store.aliases.items() if c == column)

    def set_alias_column(self, key: str, column: str) -> None:
        if self._store.aliases.get(key) != column:
            self._store.aliases[key] = column
            self._changed = True

    def remove_alias(self, key: str) -> None:
        if self._store.aliases.pop(key, None) is not None:
            self.alias_labels.pop(key, None)
            self._store.alias_areas.pop(key, None)
            self._changed = True

    def remove_column(self, column: str) -> list:
        """Forget an added column and every alias pointing to it (those variables will
        be reviewed again). Template and standard columns can't be removed. Returns
        the aliases removed."""
        if column not in self._store.columns:
            return []
        del self._store.columns[column]
        removed = self.aliases_to(column)
        for k in removed:
            del self._store.aliases[k]
            self.alias_labels.pop(k, None)
            self._store.alias_areas.pop(k, None)
        # identities whose names no longer point anywhere are forgotten too
        self._store.species_ids = {cid: n for cid, n in self.species_ids.items()
                                   if self._species_named(n, self._store.aliases)}
        self._changed = True
        return removed

    def rename_column(self, old: str, new: str) -> None:
        """Rename an added column; aliases follow. Fails if `new` already exists."""
        if old not in self._store.columns:
            raise ValueError(f"'{old}' isn't a column you added.")
        if self.is_known_column(new) or new in self._store.columns:
            raise ValueError(f"A column called '{new}' already exists.")
        self._store.columns[new] = self._store.columns.pop(old)
        for k, c in list(self._store.aliases.items()):
            if c == old:
                self._store.aliases[k] = new
        self._changed = True

    def save(self) -> None:
        """Writes the local additions -- only if something was actually added."""
        if self.path is None or not self._changed:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        st = self._store
        if st.migrated and self.path.is_file():      # the file before the compound-column migration, kept once
            backup = self.path.with_name(self.path.stem + ".before-compound-columns-2026-11-04.json")
            if not backup.exists():
                backup.write_text(self.path.read_text())
            st.migrated = False
        data = {"columns": st.columns, "aliases": st.aliases, "alias_labels": st.alias_labels,
                "alias_areas": st.alias_areas, "species_ids": st.species_ids}
        if st.builtin:
            data["builtin_columns"] = st.builtin
        if st.categories:
            data["categories"] = st.categories
        if st.compounds:
            data["compounds"] = st.compounds
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
        self._changed = False
