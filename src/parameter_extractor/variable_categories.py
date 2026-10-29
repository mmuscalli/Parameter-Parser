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


def categories(pack: Optional[Pack] = None) -> List[VariableCategory]:
    """The pack's own categories (the domain's own kinds of variable first), then the shared ones
    it doesn't replace (same id), then the built-in groups."""
    pack = pack or current()
    shared = [VariableCategory(**c) for c in json.loads(SHARED_FILE.read_text())["categories"]]
    own = [VariableCategory(**c) for c in pack.manifest.variable_categories]
    ids = {c.id for c in own}
    return own + [c for c in shared if c.id not in ids] + [FIGURE, ASSUMED]


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
