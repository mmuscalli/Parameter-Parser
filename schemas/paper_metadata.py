"""Stage 3a: bibliographic metadata.

Usually unambiguous, which is why these fields aren't wrapped in the heavier
`Extracted[T]` provenance type the way methodology/chemistry fields are --
not every field needs the same amount of ceremony. The DOI is the exception:
older papers frequently don't print one at all (DOIs were often assigned
retroactively), so `doi_source` tracks whether it came straight off the page
or was resolved after the fact -- a reader should never have to guess which.
"""
from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel

DoiSource = Literal[
    "paper_text",          # printed on the page, extracted directly
    "crossref_api",        # resolved automatically via CrossRef bibliographic search
    "manual_fallback",     # resolved by a human (or a research step outside the
                            # automated pipeline, e.g. web search) when CrossRef
                            # wasn't reachable -- see README "Network restrictions"
    "not_found",           # not on the page and not resolved
]


class PaperMetadata(BaseModel):
    paper_id: str
    paper_doi: Optional[str] = None
    doi_source: DoiSource = "not_found"
    doi_confidence: Optional[float] = None  # title-similarity ratio when doi_source == "crossref_api"
    doi_match_title: Optional[str] = None   # what the DOI source matched against, for human spot-checking
    doi_note: Optional[str] = None
    paper_title: str
    authors: List[str]
    year_published: int
    journal_published: str
    source: str = "title page / header"
