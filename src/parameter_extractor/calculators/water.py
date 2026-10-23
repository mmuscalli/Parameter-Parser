"""
Water always says which water (Mickey, 2026-10-22): "distilled", "deionized",
"Milli-Q", "ultrapure", "nanopure" or "tap". A solvent given only as "water"
is taken to be distilled water -- written as such, marked assumed in its
provenance and flagged, so the user can correct it. Spellings are normalised
("DI water", "deionised H2O", "MilliQ" ...) so the column can be searched.
"""
from __future__ import annotations
import re
from typing import List, Optional, Tuple

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value
from parameter_extractor.schemas.row_schema import CellSource

DEFAULT_TYPE = "distilled water"
WATER_COLUMNS = ("solvent_name",)
# (pattern, canonical name) -- first match wins; "double-distilled" stays a kind of distilled water
_TYPES = [
    (r"\bmilli\s*-?\s*q\b|\bmillipore\b", "Milli-Q water"),
    (r"\bnano\s*-?\s*pure\b", "nanopure water"),
    (r"\bultra\s*-?\s*pure\b|18\.2\s*m\s*(?:ω|ohm)", "ultrapure water"),
    (r"\bde\s*-?\s*ioni[sz]ed\b|\bd\.?\s*i\.?\b(?=\s*(?:water|h2o))", "deionized water"),
    (r"\b(?:double|doubly|twice|bi)\s*-?\s*distill?ed\b", "double-distilled water"),
    (r"\bdistill?ed\b", "distilled water"),
    (r"\btap\b", "tap water"),
]
_WATER = re.compile(r"\b(?:water|h2o|h₂o)\b|^aq(?:ueous)?\.?$", re.IGNORECASE)


def water_type(text: str) -> Tuple[Optional[str], bool]:
    """(canonical name, assumed) for a solvent that is water; (None, False) otherwise."""
    t = (text or "").strip()
    if not t or not _WATER.search(t):
        return None, False
    low = t.lower()
    for pattern, name in _TYPES:
        if re.search(pattern, low):
            return name, False
    if re.fullmatch(r"(?:pure\s+)?(?:water|h2o|h₂o)|aq(?:ueous)?\.?|aqueous solution", low):
        return DEFAULT_TYPE, True
    return None, False                       # water in a mixture ("water/ethanol 1:1"): left as given


def normalize_water(rows) -> List[str]:
    """Names the water type in each row's solvent; returns flag messages (one per distinct
    assumption, listing the rows)."""
    assumed: dict = {}
    for row in rows:
        values = row_to_template_dict(row)
        for column in WATER_COLUMNS:
            given = values.get(column)
            name, was_assumed = water_type(given if isinstance(given, str) else "")
            if name is None or name == given:
                continue
            old = row.provenance.get(column)
            src = CellSource(origin=(old.origin if old else "experimental conditions")
                             + (", assumed distilled" if was_assumed else ""),
                             quote=old.quote if old else "", source=old.source if old else "",
                             confidence="low" if was_assumed else (old.confidence if old else None))
            set_row_value(row, column, name, src)
            if was_assumed:
                assumed.setdefault((column, given), []).append(row.full_id)
    return [f"{column}: the paper says '{given}' without the type of water, so '{DEFAULT_TYPE}' was assumed "
            f"({len(ids)} row(s): {', '.join(ids[:6])}{' ...' if len(ids) > 6 else ''}). Correct it if the "
            f"paper specifies deionized, Milli-Q, ultrapure, nanopure or tap water elsewhere."
            for (column, given), ids in assumed.items()]
