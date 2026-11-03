"""
Data types of columns (Mickey, 2026-11-03): a column can be restricted to a basic type so values of one
kind don't arrive in several shapes ('3' on some rows, 'triplicate experiments; lengths averaged' on others).

  any      -- as found (the default for a new column, and for text columns without a rule)
  number   -- a number (after unit conversion, where the column has a unit)
  integer  -- a whole number; counting words are read: 'triplicate' -> 3, 'in duplicate' -> 2, 'three' -> 3
  text     -- text; a number is written as text ('3')
  yes_no   -- 'yes' / 'no' (also from true/false, present/absent, 1/0)

A column's type: the one the user chose in the review (remembered in the registry's added columns), else the
pack's stage parameter (`integer` -> integer, kind text -> text, else number), else 'number' for a column with
a unit, else 'any'. `coerce` converts a value or says why it can't.
"""
from __future__ import annotations
import re
from typing import Optional, Tuple

TYPES = {"any": "Any (as found)", "number": "Number", "integer": "Whole number", "text": "Text",
         "yes_no": "Yes / no"}

_MULTIPLES = {"single": 1, "singly": 1, "singlicate": 1, "duplicate": 2, "duplicated": 2, "triplicate": 3,
              "quadruplicate": 4, "quintuplicate": 5, "sextuplicate": 6, "septuplicate": 7, "octuplicate": 8,
              "nonuplicate": 9, "decuplicate": 10}
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "eleven": 11, "twelve": 12, "once": 1, "twice": 2, "thrice": 3}
_NUMBER = re.compile(r"[-+−]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")
_YES = {"yes", "y", "true", "1", "present", "used", "with"}
_NO = {"no", "n", "false", "0", "absent", "none", "not used", "without"}


def whole_number(text) -> Optional[int]:
    """A count read from a value: 3, 3.0, '3', 'n = 3', 'triplicate experiments; averaged', 'in duplicate',
    'three runs'. None when there's no count or more than one ('3 runs of 5 mg')."""
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return int(text) if float(text).is_integer() else None
    low = str(text or "").lower()
    words = re.findall(r"[a-z]+", low)
    counts = {_MULTIPLES[w] for w in words if w in _MULTIPLES} | {
        _MULTIPLES[w[:-1]] for w in words if w.endswith("s") and w[:-1] in _MULTIPLES}
    if len(counts) == 1:
        return counts.pop()
    if counts:
        return None
    numbers = {float(n.replace(",", ".").replace("−", "-")) for n in _NUMBER.findall(low)}
    named = {_WORDS[w] for w in words if w in _WORDS}
    found = numbers | {float(n) for n in named}
    if len(found) == 1:
        n = found.pop()
        return int(n) if n.is_integer() else None
    return None


def coerce(value, value_type: str) -> Tuple[object, str]:
    """(the value as `value_type`, problem). The problem is '' when it fits; the value is None when it doesn't."""
    if value_type in ("", "any", None) or value is None or value == "":
        return value, ""
    if value_type == "integer":
        n = whole_number(value)
        return (n, "") if n is not None else (None, f"'{value}' isn't a whole number")
    if value_type == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value, ""
        text = str(value).strip().replace("−", "-")
        if _NUMBER.fullmatch(text):
            return float(text.replace(",", ".")), ""
        return None, f"'{value}' isn't a number"
    if value_type == "text":
        if isinstance(value, float) and value.is_integer():
            return str(int(value)), ""
        return (f"{value:g}" if isinstance(value, float) else str(value)), ""
    if value_type == "yes_no":
        low = str(value).strip().lower().rstrip(".")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            low = "1" if value == 1 else "0" if value == 0 else low
        if low in _YES:
            return "yes", ""
        if low in _NO:
            return "no", ""
        return None, f"'{value}' isn't yes or no"
    return value, ""


def column_type(column: str, registry=None) -> str:
    """The data type a column holds (see the module docstring)."""
    if registry is not None:
        chosen = (getattr(registry, "added_columns", {}).get(column) or {}).get("type")
        if chosen:
            return chosen
    try:
        from parameter_extractor.stages.optional import load_specs
        for spec in load_specs().values():
            for p in spec.parameters:
                if p.column == column:
                    return "integer" if p.integer else ("text" if p.kind == "text" else "number")
    except Exception:
        pass
    from parameter_extractor.ingestion.observations import unit_for_column
    return "number" if unit_for_column(column) else "any"
