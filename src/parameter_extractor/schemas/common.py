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
        description="Short verbatim snippet from the paper that supports this value; empty "
                    "if none. Required whenever status == 'found'; absence of a quote is itself "
                    "a signal to distrust the value.",
    )
    source: str = Field(
        default="",
        description="Where in the paper, e.g. 'Table 1', 'Experimental section, para 2', "
                    "'page 3'; empty if not found.",
    )
    confidence: Confidence = "low"
    note: str = Field(
        default="",
        description="Free-text explanation when status is ambiguous/conflicting/below_threshold "
                    "-- e.g. 'paper states <0.15% for all samples, exact value not given'; "
                    "empty otherwise.",
    )

    @field_validator("quote", "source", "note", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return "" if v is None else v       # outputs saved before this change used null
