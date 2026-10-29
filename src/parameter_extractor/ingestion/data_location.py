"""
`data_location` (Mickey, 2026-10-29): where in the paper a row's data point was found, in one
consistent format, for every pack -- the same value for every row from the same figure or table:

    Figure. 1      Figure. 3b (a panel)      Table. 2      Table. S1 (supplementary)
    Text: Results  (no table or figure named: the section, as the set's source gives it; 'Text' alone
                    when it names none)

The format follows Mickey's example ("Figure. 1"); FIGURE / TABLE below set it. Rows from tables and the
text take it from the structure plan's source for the sample (else for the set); digitized rows from
the figure they were read from.
"""
from __future__ import annotations
import re

COLUMN = "data_location"
FIGURE, TABLE, TEXT = "Figure. {}", "Table. {}", "Text: {}"

_FIGURE_OR_TABLE = re.compile(
    r"\b(?:supp(?:lementary|l)?\.?\s+|extended\s+data\s+)?(fig(?:ure)?s?|tab(?:le)?s?)\.?\s*"
    r"(S?\d+)\s*(?:\(?([a-h])\)?(?![a-z]))?", re.IGNORECASE)


def location(*sources: str) -> str:
    """The data location named by the first source that names one ('Table 1, Na+ row' -> 'Table. 1',
    'Fig. 3a' -> 'Figure. 3a'); else 'Text: <first part of the source>'; '' when nothing is given."""
    for text in sources:
        m = _FIGURE_OR_TABLE.search(text or "")
        if m:
            kind, number, panel = m.group(1).lower(), m.group(2).upper(), (m.group(3) or "").lower()
            if "extended data" in m.group(0).lower() or re.match(r"supp", m.group(0), re.IGNORECASE):
                number = number if number.startswith("S") else f"S{number}"
            return FIGURE.format(number + panel) if kind.startswith("fig") else TABLE.format(number)
    # the text: the broadest source given (the set's section, passed last), so every row from one passage
    # gets the same value; 'Main text, Campbell et al. results (...)' -> 'Text: Campbell et al. results'
    given = [t.strip() for t in sources if t and t.strip()]
    if not given:
        return ""
    parts = [p.strip() for p in re.split(r"[,;(]", given[-1]) if p.strip()]
    parts = [p for p in parts if not re.fullmatch(r"(?:main\s+|body\s+)?text", p, re.IGNORECASE)]
    return TEXT.format(parts[0][:60]) if parts else "Text"
