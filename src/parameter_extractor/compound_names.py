"""
Compound names in the output (Mickey, 2026-11-03): every compound the app knows has a DEFAULT name -- the one the
pipeline matches and builds columns with (the vocabulary's 'NaCl', 'Gly'; a newly accepted compound keeps the
paper's name) -- plus the synonyms PubChem lists for it (pubchem.useful_synonyms; bundled in the pack's
species_cids.json for vocabulary species, kept in the registry for compounds accepted in a review). One of them
is the ACTIVE name: the one written into column names ('initial_NaCl_aq_mM' -> 'initial_sodium_chloride_aq_mM'),
chosen in the Remembered variables window's Compounds tab.

Only the files are renamed: the run itself, the registry's synonyms and the template order use default names, so
switching the active name never changes what is extracted. `CompoundNames.harmonize` converts a column written
under ANY of a compound's names (an older dataset, another choice) to the active one; `to_default` goes back.
"""
import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ROLES = ("initial", "sampled", "stock")
_COLUMN = re.compile(r"^(?P<role>initial|sampled|stock)_(?P<rest>.+)$")


@dataclass
class Compound:
    name: str                          # the default name (columns are built with it)
    cid: int = 0
    synonyms: List[str] = field(default_factory=list)
    active: str = ""                   # '' = the default name
    builtin: bool = False              # a vocabulary species of the pack (synonyms bundled)
    area: str = ""                     # research area the choice is kept for

    @property
    def shown(self) -> str:
        return self.active or self.name

    @property
    def names(self) -> List[str]:
        """The default name first, then the synonyms (the choices for the active name)."""
        out, seen = [], set()
        for n in [self.name] + list(self.synonyms):
            if n.lower() not in seen:
                seen.add(n.lower())
                out.append(n)
        return out


def bundled(pack=None) -> Dict[str, dict]:
    """The pack's vocabulary species with a PubChem CID: {name: {cid, title, synonyms}}."""
    from parameter_extractor import packs
    path = (pack or packs.current()).species_cids_path
    if not path or not Path(path).is_file():
        return {}
    return json.loads(Path(path).read_text()).get("species", {})


def slug(name: str) -> str:
    from parameter_extractor.ingestion.flatten_to_template import column_safe_name
    return column_safe_name(name)


class CompoundNames:
    """The compounds of one research area (bundled + accepted) with their active names."""

    def __init__(self, registry=None, pack=None):
        from parameter_extractor import packs
        self.pack = pack or (registry.pack if registry is not None else packs.current())
        self.compounds: Dict[str, Compound] = {}
        for name, info in bundled(self.pack).items():
            self.compounds[name] = Compound(name, int(info.get("cid") or 0), list(info.get("synonyms", [])),
                                            builtin=True, area=self.pack.id)
        if registry is not None:
            for name, info in registry.compounds().items():
                c = self.compounds.get(name) or Compound(name, int(info.get("cid") or 0),
                                                         list(info.get("synonyms", [])), area=info.get("area", ""))
                if not c.builtin:
                    c.synonyms = list(info.get("synonyms", c.synonyms))
                c.active = info.get("active", "") if info.get("active", "") != name else ""
                c.area = info.get("area", c.area)
                self.compounds[name] = c
        # every slug a compound's columns may carry -> the compound (unique ones only: two compounds sharing a
        # synonym, like the hydrates' 'sodium phosphate', never convert)
        owners: Dict[str, set] = {}
        for c in self.compounds.values():
            for n in c.names:
                owners.setdefault(slug(n), set()).add(c.name)
        self._by_slug = {s: next(iter(o)) for s, o in owners.items() if len(o) == 1}
        self._by_lower = {}
        lower: Dict[str, set] = {}
        for c in self.compounds.values():
            for n in c.names:
                lower.setdefault(n.lower(), set()).add(c.name)
        self._by_lower = {n: next(iter(o)) for n, o in lower.items() if len(o) == 1}

    def default_for(self, name: str) -> Optional[str]:
        """The default name of the compound `name` is one of the names of (exact, case-insensitive; a synonym
        shared by two compounds names neither)."""
        return self._by_lower.get((name or "").strip().lower())

    def _split(self, column: str):
        """(role, compound default name, the rest after its slug) for a species column, else None."""
        m = _COLUMN.match(column)
        if not m:
            return None
        rest = m.group("rest")
        # the longest slug that is followed by '_' (names may contain '_' themselves)
        best = None
        for i in [j for j, ch in enumerate(rest) if ch == "_"]:
            name = self._by_slug.get(rest[:i])
            if name is not None:
                best = (m.group("role"), name, rest[i:])
        return best

    def harmonize(self, column: str) -> str:
        """A column under any name of a compound -> under its active name (unchanged when not a species column)."""
        parts = self._split(column)
        if not parts:
            return column
        role, name, tail = parts
        return f"{role}_{slug(self.compounds[name].shown)}{tail}"

    def to_default(self, column: str) -> str:
        parts = self._split(column)
        if not parts:
            return column
        role, name, tail = parts
        return f"{role}_{slug(name)}{tail}"

    def renames(self, columns) -> Dict[str, str]:
        """{column: active-name column} for the columns an active name changes."""
        out = {}
        for c in columns:
            new = self.harmonize(c)
            if new != c:
                out[c] = new
        return out

    @property
    def active_choices(self) -> Dict[str, str]:
        return {n: c.active for n, c in self.compounds.items() if c.active}


def renames_for(columns, registry) -> Dict[str, str]:
    """The output renames of a run: empty unless the user chose an active name for some compound."""
    if registry is None or not registry.compounds():
        return {}
    names = CompoundNames(registry)
    if not names.active_choices:
        return {}
    return {c: n for c, n in names.renames(columns).items() if c != n}


def convert_dataset_csv(path, out_path, registry, to: str = "active") -> Dict[str, str]:
    """Rewrites a dataset CSV's header with every compound under its active (or default, `to='default'`) name;
    columns that become the same (one paper wrote 'NaCl', another 'sodium chloride') are merged, the first
    non-empty cell winning. Returns the renames."""
    names = CompoundNames(registry)
    convert = names.harmonize if to == "active" else names.to_default
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return {}
    header = rows[0]
    new_header = []
    for c in header:
        n = convert(c)
        if n not in new_header:
            new_header.append(n)
    index = {n: i for i, n in enumerate(new_header)}
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(new_header)
        for r in rows[1:]:
            out = [""] * len(new_header)
            for c, v in zip(header, r):
                i = index[convert(c)]
                if not out[i]:
                    out[i] = v
            w.writerow(out)
    return {c: convert(c) for c in header if convert(c) != c}
