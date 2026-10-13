"""
Shared building blocks for every stage schema.

The central idea: a value pulled from a paper is never just "the number." It's a
number plus a claim about where it came from and how sure the model is. Extracted
is used anywhere a field could plausibly be unreported or ambiguous; plain types are
used where that would be overkill (e.g. "how many solute entries did we find").
"""
from __future__ import annotations
from typing import Generic, Literal, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")

Confidence = Literal["high", "medium", "low"]
CONFIDENCE_ORDER = ("low", "medium", "high")


def confidence_below(confidence: Optional[str], threshold: Optional[str]) -> bool:
    """True if `confidence` ranks strictly below `threshold`. A None threshold
    means "no threshold" (never below); a None confidence counts as lowest."""
    if threshold is None:
        return False
    if confidence is None:
        return True
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
    quote: Optional[str] = Field(
        default=None,
        description="Short verbatim snippet from the paper that supports this value. "
                    "Required whenever status == 'found'; absence of a quote is itself "
                    "a signal to distrust the value.",
    )
    source: Optional[str] = Field(
        default=None,
        description="Where in the paper, e.g. 'Table 1', 'Experimental section, para 2', 'page 3'.",
    )
    confidence: Confidence = "low"
    note: Optional[str] = Field(
        default=None,
        description="Free-text explanation when status is ambiguous/conflicting/below_threshold "
                    "-- e.g. 'paper states <0.15% for all samples, exact value not given'.",
    )
