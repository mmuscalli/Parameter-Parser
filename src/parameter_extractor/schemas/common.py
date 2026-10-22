"""
Shared building blocks for every stage schema.

The central idea: a value pulled from a paper is never just "the number." It's a
number plus a claim about where it came from and how sure the model is. Extracted
is used anywhere a field could plausibly be unreported or ambiguous; plain types are
used where that would be overkill (e.g. "how many solute entries did we find").
"""
from __future__ import annotations
from typing import Generic, Literal, Optional, TypeVar
from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")

# How much of the paper each value carries back (Mickey, 2026-10-22: quotes and notes were bulky --
# output tokens are most of a long paper's cost). The model is asked for short ones; what's kept is
# capped too (row_schema.CellSource, plausibility_checks.Flag), and every value keeps a precise
# `source` plus the page its quote was found on (validation/quotes.py) to find the full context.
QUOTE_WORDS = 20
NOTE_WORDS = 15
QUOTE_MAX_CHARS = 200          # kept; longer quotes are cut at a word with " …"
NOTE_MAX_CHARS = 150
QUOTE_SEPARATOR_SAFE = " | "   # = validation.quotes.QUOTE_SEPARATOR (grouped flags join quotes with it)
QUOTE_DESC = (f"The SHORTEST span of the paper's own words that shows the value -- at most {QUOTE_WORDS} words, "
              f"copied exactly (for a table value: its row label, column label and the value as printed). "
              f"Never your own words.")
SOURCE_DESC = ("Exactly where: e.g. 'Table 3, row HD 14067 b, column e', 'Sect. 4.2, 2nd paragraph', "
               "'Fig. 5 caption', 'Methods, p. 4'.")
NOTE_DESC = f"At most {NOTE_WORDS} words of your own (e.g. how a derived value was calculated); '' if none."


def capped(text: str, limit: int) -> str:
    """Cut at a word boundary with ' …' if longer than `limit` characters."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return f"{cut} …"

Confidence = Literal["high", "medium", "low"]
CONFIDENCE_ORDER = ("low", "medium", "high")

# Where a value comes from. "assumed" (the paper doesn't state it -- including
# when the paper itself hedges: "perhaps", "probably", "not documented") is never
# written to the CSV automatically: it's flagged and offered in the review, where
# the user decides (and that decision is never remembered for later papers).
Basis = Literal["stated", "derived", "assumed"]


def confidence_below(confidence: Optional[str], threshold: Optional[str]) -> bool:
    """True if `confidence` ranks strictly below `threshold`. A None threshold
    means "no threshold" (never below); a None confidence counts as lowest.
    A label outside the high/medium/low scale (e.g. "digitized" for values
    read off a figure by the user) isn't ranked, so it's never "below"."""
    if threshold is None:
        return False
    if confidence is None:
        return True
    if confidence not in CONFIDENCE_ORDER:
        return False
    return CONFIDENCE_ORDER.index(confidence) < CONFIDENCE_ORDER.index(threshold)

# First-class states -- the point made in the design discussion: never let a
# missing/ambiguous value collapse silently into a guess or a bare null.
Status = Literal[
    "found",            # value located and extracted with reasonable confidence
    "not_reported",     # paper doesn't state this parameter at all
    "below_threshold",  # paper explicitly says "below X%"/"not detected" rather than giving a number
    "ambiguous",        # found, but extraction required an uncertain judgment call (unit, identity, etc.)
    "conflicting",       # paper states this more than once with different values
]


class Extracted(BaseModel, Generic[T]):
    """
    A single extracted datum with provenance. `value` is None whenever `status`
    isn't "found" -- code downstream should branch on `status`, not on
    `value is None`, since "not stated" and "stated as zero" are different things.
    """
    value: Optional[T] = None
    status: Status = "not_reported"
    # quote/source/note are plain strings ("" = none) rather than Optional: every
    # optional field adds an alternative to the structured-output grammar, and the
    # Methodology schema (10 of these) hit the API's grammar size limit with them.
    quote: str = Field(
        default="",
        description=QUOTE_DESC + " Required whenever status == 'found'; empty if none.",
    )
    source: str = Field(
        default="",
        description=SOURCE_DESC + " Empty if not found.",
    )
    confidence: Confidence = "low"
    note: str = Field(
        default="",
        description=f"At most {NOTE_WORDS} words, only when status is ambiguous/conflicting/below_threshold "
                    "-- e.g. '<0.15% for all samples, exact value not given'; empty otherwise.",
    )

    @field_validator("quote", "source", "note", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return "" if v is None else v       # outputs saved before this change used null
