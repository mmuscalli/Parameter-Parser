"""
Categories of suggested new variables (Mickey, 2026-10-26).

A category says what KIND of variable a suggestion is and how its values are reported:
  - value_type "number": one number with a unit -- the proposed column gets the unit's suffix
    ("reaction time" in h -> reaction_time_hr) and values are converted to it; anything else
    (a range, words) is kept as text with a format note;
  - "text": words, at most max_words (longer values get a note; the user can shorten them);
  - "any": a number if the value is one, else short text.

Every pack gets packs/variable_categories.json (Metadata, Experimental Methodology); a pack adds
its own (listed first) -- or replaces a shared one by id -- with "variable_categories" in its pack.json.
The user can change the bundled ones' label / description / format / order and add their own, per pack or for
every pack (Variables > Variable categories; kept in the registry file, applied via `use_local`).
Categories with `sources` are filled from where a value comes from (species with no column,
added solution volumes); the others (and any with model_assigns) are the ones the model chooses from (`cat` on an open-ended
stage's `other` items). Two built-in groups end the list: hand-typed figure columns and values
the model assumed. The review window shows suggestions grouped by category, in this order.
"""
from __future__ import annotations
import json
import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from parameter_extractor.packs import BUILTIN_DIR, Pack, current

SHARED_FILE = BUILTIN_DIR / "variable_categories.json"


class VariableCategory(BaseModel):
    id: str
    label: str
    description: str = ""
    value_type: Literal["number", "text", "any"] = "any"
    max_words: int = 0                       # text values: longer gets a note (0 = no limit)
    sources: List[str] = Field(default_factory=list)
    model_assigns: Optional[bool] = None     # default: only categories without sources
    # the dataset's columns in this category, for the column order (column_order.py): by name, and by
    # regular expression; table_order places the category's block (lower = further left)
    columns: List[str] = Field(default_factory=list)
    patterns: List[str] = Field(default_factory=list)
    table_order: int = 500

    @property
    def assignable(self) -> bool:
        """The model can put a value in this category (its open-ended `other` items)."""
        return self.model_assigns if self.model_assigns is not None else not self.sources

    def format_rule(self) -> str:
        if self.value_type == "number":
            return "one number with its unit"
        words = f"at most {self.max_words} words" if self.max_words else "short"
        return f"text, {words}" if self.value_type == "text" else f"a number with its unit, or text ({words})"


# built-in groups, after the pack's categories
FIGURE = VariableCategory(id="figure", label="Figure columns (typed in the digitizer)", value_type="number",
                          sources=["figure_axis"])
ASSUMED = VariableCategory(id="assumed", label="Assumed values (not stated in the paper)", sources=["assumed"])


STANDARD = "standard"          # = registry.STANDARD: the user's edits of the shared categories
EDITABLE_FIELDS = ("label", "description", "value_type", "max_words", "table_order", "model_assigns")
RESERVED_IDS = {FIGURE.id, ASSUMED.id}

# the user's category edits (the registry file's "categories": {area: {"added": [...], "changed": {id: {...}}}}),
# set by pipeline._start from RunConfig.registry_path and by the GUI; empty = the bundled categories only
_local: dict = {}


def use_local(edits: Optional[dict]) -> None:
    global _local
    _local = dict(edits or {})


def _edited(cats: List[VariableCategory], edits: dict) -> List[VariableCategory]:
    """The bundled categories with the user's changes, then the user's own."""
    changed = edits.get("changed", {})
    out = [c.model_copy(update={k: v for k, v in changed[c.id].items() if k in EDITABLE_FIELDS})
           if c.id in changed else c for c in cats]
    return out + [VariableCategory(**c) for c in edits.get("added", [])]


def bundled_shared() -> List[VariableCategory]:
    return [VariableCategory(**c) for c in json.loads(SHARED_FILE.read_text())["categories"]]


def bundled_own(pack: Pack) -> List[VariableCategory]:
    return [VariableCategory(**c) for c in pack.manifest.variable_categories]


def _with_added_before_other(cats: List[VariableCategory], added: List[dict]) -> List[VariableCategory]:
    at = next((i for i, c in enumerate(cats) if c.id == "other"), len(cats))
    return cats[:at] + [VariableCategory(**c) for c in added] + cats[at:]


def shared_categories(local: Optional[dict] = None, pack: Optional[Pack] = None) -> List[VariableCategory]:
    """The categories every pack gets (minus those `pack` replaces, with its columns for them), with the user's
    edits; the user's own shared categories go before Other."""
    local = _local if local is None else local
    edits = local.get(STANDARD, {})
    replaced = {c.id for c in bundled_own(pack)} if pack else set()
    cats = [c for c in bundled_shared() if c.id not in replaced]
    if pack:
        _add_pack_columns(cats, pack)
    cats = _edited(cats, {"changed": edits.get("changed", {})})
    return _with_added_before_other(cats, edits.get("added", []))


def _add_pack_columns(cats: List[VariableCategory], pack: Pack) -> None:
    """The pack's columns for any category, shared ones included ("category_columns" in pack.json)."""
    for c in cats:
        extra = pack.manifest.category_columns.get(c.id, {})
        c.columns = list(extra.get("columns", [])) + [x for x in c.columns if x not in extra.get("columns", [])]
        c.patterns = list(extra.get("patterns", [])) + c.patterns
        if "table_order" in extra:
            c.table_order = extra["table_order"]


def categories(pack: Optional[Pack] = None, local: Optional[dict] = None) -> List[VariableCategory]:
    """The pack's own categories (the domain's own kinds of variable first; then the user's for this pack),
    then the shared ones it doesn't replace (same id), then the built-in groups. `local` = the user's edits
    (default: the ones in use, `use_local`)."""
    pack = pack or current()
    local = _local if local is None else local
    own = bundled_own(pack)
    _add_pack_columns(own, pack)
    own = _edited(own, local.get(pack.id, {}))
    return own + shared_categories(local, pack) + [FIGURE, ASSUMED]


def table_categories(pack: Optional[Pack] = None, local: Optional[dict] = None,
                     area: Optional[str] = None) -> List[VariableCategory]:
    """Categories a column can be placed under (no built-in review groups). area STANDARD: the shared ones."""
    if area == STANDARD:
        return shared_categories(local)
    return [c for c in categories(pack, local) if c.id not in RESERVED_IDS]


def by_id(category_id: str, pack: Optional[Pack] = None) -> Optional[VariableCategory]:
    return next((c for c in categories(pack) if c.id == category_id), None)


def assignable(pack: Optional[Pack] = None) -> List[VariableCategory]:
    return [c for c in categories(pack) if c.assignable]


def prompt_listing(pack: Optional[Pack] = None) -> str:
    """For the open-ended rule: '`metadata` (about the study ...; text, at most 12 words), ...'."""
    return "; ".join(f"`{c.id}` ({c.description}; {c.format_rule()})" for c in assignable(pack))


def for_source(source: str, role: Optional[str] = None, pack: Optional[Pack] = None) -> Optional[str]:
    """The category that collects values from `source` ('species', 'added_solution', 'figure_axis',
    'assumed'); a role-qualified source ('species:sampled') wins over the plain one."""
    cats = categories(pack)
    for wanted in ([f"{source}:{role}"] if role else []) + [source]:
        for c in cats:
            if wanted in c.sources:
                return c.id
    return None


def guess(value: str, pack: Optional[Pack] = None) -> str:
    """A category for a value nobody categorised (a targeted search finding, an answer recorded
    before categories): a quantity -> the first assignable number category, else methodology (or
    the first assignable one)."""
    from parameter_extractor.units import parse_quantity
    options = assignable(pack)
    if parse_quantity(value) is not None:
        number = next((c for c in options if c.value_type == "number"), None)
        if number:
            return number.id
    fallback = next((c for c in options if c.id == "methodology"), options[0] if options else None)
    return fallback.id if fallback else ""


# canonical unit -> the column suffix of that dimension's usual column unit (the template's style:
# times in hours, temperatures in °C, volumes in mL; observations.unit_for_column reads them back)
_SUFFIX = {"concentration": "_mM", "volume": "_mL", "time": "_hr", "temperature": "_C", "pressure": "_bar",
           "mass": "_g"}
_UNIT_SUFFIX = {"nm": "_nm", "rpm": "_rpm", "%": "_pct", "mL/min": "_mL_min", "K": "_C", "°F": "_C",
                "µL": "_uL"}      # microlitre volumes keep a µL column (the dataset's added_*_uL style)


def unit_suffix(unit: str) -> str:
    """Column suffix for values in `unit` (canonical, as units.parse_quantity gives it), or ''."""
    from parameter_extractor.units import _UNITS
    if unit in _UNIT_SUFFIX:
        return _UNIT_SUFFIX[unit]
    dimension = _UNITS.get(unit, ("",))[0]
    return _SUFFIX.get(dimension, "")


# a bare lowercase 'm': units.py reads it as molar (as papers use it for concentrations), but in a
# condition it's as likely metres
_BARE_M = re.compile(r"^\s*[-+]?[\d.,]+(?:\s*[×x]\s*10\S*)?\s*m\s*$")


def check_format(category: Optional[VariableCategory], value_text: Optional[str]):
    """(number, canonical unit, note) for a value given as text, following its category's format:
    a number category's value is parsed (note if it isn't one number with a unit); a text value
    longer than max_words gets a note. Nothing is cut or changed beyond parsing."""
    from parameter_extractor.units import parse_quantity
    if category is None or not value_text:
        return None, None, ""
    if _BARE_M.match(value_text):           # faisal2005's '20 m' tube length had become 20 M (molar)
        return None, None, "unit 'm' could be metres or molar; kept as text"
    parsed = parse_quantity(value_text) if category.value_type in ("number", "any") else None
    if parsed is not None:
        return parsed[0], parsed[1], ""
    if category.value_type == "number":
        return None, None, f"expected one number with a unit ({category.label}); kept as text"
    words = len(value_text.split())
    if category.max_words and words > category.max_words:
        return None, None, f"{words} words; {category.label} values are at most {category.max_words} words"
    return None, None, ""
