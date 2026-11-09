"""
Analytical techniques and their instrument settings (Mickey, 2026-11-07): the vocabulary a pack ships as
`analysis_vocab.json` (the prebiotic pack's is grounded in Rouessac & Rouessac, Chemical Analysis, 3rd ed., and
the settings prebiotic papers report), and the column format of the values the analysis step extracts:

    analysis_<technique>_<setting>[_<unit>]

e.g. 'analysis_MALDI-TOF-MS_laser-intensity_%', 'analysis_RP-HPLC_flow-rate_mL_min', 'analysis_RP-HPLC_column'
(text). Technique and setting use hyphens inside and underscores only between the parts -- the slot format of
the compound columns ('<role>_<name>_<phase>_<measure>') -- so a column can be read back (`parse_column`). A range
puts 'range' before the unit ('..._laser-intensity_range_%', cell 'low:high'), like every other range column.

A column whose technique is in the vocabulary and whose setting belongs to one of that technique's families (or
to 'general') is KNOWN: the pack defines it, as it defines its template columns. Any other technique or setting
is offered in the review (category Analysis) with its column already in this format.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PREFIX = "analysis"
FILE = "analysis_vocab.json"

# column unit -> the unit token at the end of the column name (the existing suffixes where there are some)
UNIT_TOKENS = {
    "°C": "C", "K": "K", "mm": "mm", "µm": "um", "nm": "nm", "cm": "cm", "m": "m", "mL/min": "mL_min",
    "µL/min": "uL_min", "µL": "uL", "mL": "mL", "min": "min", "s": "sec", "h": "hr", "ns": "ns", "%": "%",
    "V": "V", "kV": "kV", "eV": "eV", "Hz": "Hz", "MHz": "MHz", "cm-1": "per_cm", "mW": "mW", "W": "W",
    "mA": "mA", "mV/s": "mV_s", "mM": "mM", "bar": "bar",
}
TOKEN_UNITS = {t: u for u, t in UNIT_TOKENS.items()}


@dataclass
class Setting:
    name: str
    unit: str = ""                # the column's unit; '' = text
    description: str = ""
    aliases: List[str] = field(default_factory=list)
    integer: bool = False
    family: str = ""

    @property
    def kind(self) -> str:
        return "integer" if self.integer else ("number" if self.unit else "text")


@dataclass
class Technique:
    name: str
    families: List[str]
    description: str = ""
    aliases: List[str] = field(default_factory=list)


@dataclass
class Vocabulary:
    families: Dict[str, Tuple[str, List[Setting]]]        # id -> (label, settings)
    techniques: List[Technique]

    def technique(self, name: str) -> Optional[Technique]:
        """The vocabulary's technique for a name as written ('MALDI-TOF MS', 'reversed-phase HPLC'), else None."""
        key = _key(name)
        if not key:
            return None
        for t in self.techniques:
            if key == _key(t.name) or key in (_key(a) for a in t.aliases):
                return t
        return None

    def settings_for(self, technique: Technique) -> List[Setting]:
        """The technique's settings: its families' (in order), then the general ones; a name once (first wins)."""
        out, seen = [], set()
        for fam in list(technique.families) + ["general"]:
            for s in self.families.get(fam, ("", []))[1]:
                if s.name not in seen:
                    seen.add(s.name)
                    out.append(s)
        return out

    def setting(self, technique: Optional[Technique], name: str) -> Optional[Setting]:
        """A technique's setting by name or alias (a setting name the model made up -> None)."""
        if technique is None:
            return None
        key = _key(name)
        settings = self.settings_for(technique)
        for s in settings:                      # the setting's own name first (aliases of different settings overlap)
            if key == _key(s.name):
                return s
        for s in settings:
            if key in (_key(a) for a in s.aliases):
                return s
        return None


def _key(text: str) -> str:
    """Comparison key: case, spaces, hyphens, slashes, dots and brackets don't matter ('MALDI-TOF MS' =
    'maldi tof ms'; '1H NMR' = '1H-NMR')."""
    return re.sub(r"[\s\-_/.,()\[\]]+", "", (text or "").lower().replace("μ", "µ"))


def token(text: str) -> str:
    """A name as one column slot: words joined by hyphens, no underscores, nothing a file name can't hold
    ('ion source 1 voltage' -> 'ion-source-1-voltage', 'MALDI-TOF MS' -> 'MALDI-TOF-MS')."""
    t = re.sub(r"[()\[\]{},;:\"'`]+", " ", text or "")
    t = re.sub(r"[\s_/]+", "-", t.strip())
    return re.sub(r"-{2,}", "-", t).strip("-")


def column(technique: str, setting: str, unit: str = "", is_range: bool = False) -> str:
    """'analysis_<technique>_<setting>[_range][_<unit>]' (unit = the column's unit, e.g. 'mL/min')."""
    parts = [PREFIX, token(technique), token(setting)]
    if is_range:
        parts.append("range")
    if unit:
        parts.append(UNIT_TOKENS.get(unit) or token(unit))
    return "_".join(parts)


def parse_column(name: str) -> Optional[Tuple[str, str, str, bool]]:
    """(technique, setting, column unit or '', range?) for an analysis column, else None."""
    if not name or not name.startswith(PREFIX + "_"):
        return None
    parts = name.split("_", 3)
    if len(parts) < 3 or not parts[1] or not parts[2]:
        return None
    rest = parts[3] if len(parts) == 4 else ""
    is_range = rest == "range" or rest.startswith("range_")
    if is_range:
        rest = rest[len("range"):].lstrip("_")
    for suffix in ("err_plus", "err_minus"):          # an uncertainty is in its value's unit
        if rest.endswith(suffix):
            rest = rest[: -len(suffix)].rstrip("_")
    unit = TOKEN_UNITS.get(rest, rest)
    return parts[1], parts[2], unit, is_range


def unit_for_column(name: str) -> Optional[str]:
    """The unit of an analysis column ('' for text), None if it isn't one."""
    found = parse_column(name)
    return None if found is None else found[2]


@lru_cache(maxsize=16)
def _load(path: str) -> Optional[Vocabulary]:
    p = Path(path)
    if not p.exists():
        return None
    raw = json.loads(p.read_text())
    fams = {}
    for fid, fam in raw.get("families", {}).items():
        fams[fid] = (fam.get("label", fid), [Setting(name=s["name"], unit=s.get("unit", ""),
                                                     description=s.get("description", ""),
                                                     aliases=list(s.get("aliases", [])),
                                                     integer=bool(s.get("integer")), family=fid)
                                             for s in fam.get("settings", [])])
    techs = [Technique(name=t["name"], families=list(t.get("families", [])), description=t.get("description", ""),
                       aliases=list(t.get("aliases", []))) for t in raw.get("techniques", [])]
    return Vocabulary(fams, techs)


def vocabulary(pack=None) -> Optional[Vocabulary]:
    """The pack's analysis vocabulary (default: the active pack), or None when it has none."""
    from parameter_extractor import packs
    pack = pack or packs.current()
    path = pack.file(FILE) if hasattr(pack, "file") else Path(pack.folder) / FILE   # the pack's own, else its module's
    vocab = _load(str(path or Path(pack.folder) / FILE))
    off = _families_off(pack)
    if vocab is None or not off:
        return vocab
    return _without_families(vocab, tuple(sorted(off)))


def _families_off(pack) -> set:
    """Instrument families the pack's module settings switch off (module_settings.py; never 'general')."""
    from parameter_extractor import module_settings as ms
    own = getattr(pack, "own_manifest", None)
    raw = getattr(own, "module_settings", None) or {}
    return {f for mid in raw for f in ms.settings_for(raw, mid).families_off if f != "general"}


_FILTERED: dict = {}


def _without_families(vocab: "Vocabulary", off: tuple) -> "Vocabulary":
    key = (id(vocab), off)
    if key not in _FILTERED:
        fams = {fid: f for fid, f in vocab.families.items() if fid not in off}
        techs = [t for t in vocab.techniques if not t.families or any(f not in off for f in t.families)]
        _FILTERED[key] = Vocabulary(fams, techs)
    return _FILTERED[key]


def is_vocab_column(name: str, pack=None) -> bool:
    """A column the pack's vocabulary defines (known without a review): its technique is listed (by its
    canonical name) and the setting -- with that setting's unit -- belongs to it."""
    found = parse_column(name)
    vocab = vocabulary(pack) if found else None
    if vocab is None:
        return False
    tech_name, setting_name, unit, _ = found
    tech = next((t for t in vocab.techniques if t.name == tech_name), None)
    setting = next((s for s in vocab.settings_for(tech) if s.name == setting_name), None) if tech else None
    return setting is not None and setting.unit == unit


def prompt_listing(vocab: Vocabulary, families: Optional[List[str]] = None) -> str:
    """The vocabulary as the model reads it, compact (names and units; the app matches other wordings through
    each setting's aliases, so descriptions stay in the file): settings per family, then the techniques.
    `families`: only those (and 'general'), for a run narrowed to some instrument families (scopes.py)."""
    keep = None if not families else set(families) | {"general"}
    lines = ["VOCABULARY. Settings by instrument family ([unit] for numbers; [n] whole number; others text):"]
    for fid, (label, settings) in vocab.families.items():
        if keep is not None and fid not in keep:
            continue
        names = ", ".join(s.name + (f" [{s.unit}]" if s.unit else " [n]" if s.integer else "") for s in settings)
        lines.append(f"- {fid}: {names}")
    lines.append("Techniques (families; general applies to all):")
    lines.append("; ".join(f"{t.name} ({', '.join(t.families) or '-'})" for t in vocab.techniques
                           if keep is None or set(t.families) & keep - {"general"}))
    return "\n".join(lines)
