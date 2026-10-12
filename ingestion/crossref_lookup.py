"""
Resolve a paper's DOI via the CrossRef REST API when it isn't printed on the
page (which is common for older PDFs like eder1994.pdf -- no DOI exists on a
1994 print scan; it was assigned retroactively).

IMPORTANT -- developed but not live-tested from this sandboxed session: this
project's cloud container AND the linked computer both have an organization
egress policy that rejects api.crossref.org (confirmed via direct curl from
both; see README.md "Network restrictions" section). The code below follows
CrossRef's public REST API exactly (https://api.crossref.org/swagger-ui/)
and is exercised against a realistic recorded fixture in
tests/test_crossref_lookup.py, but has not been confirmed against a live
response. Re-verify the first few real calls once this runs somewhere with
normal internet access.

Never silently accepts a low-confidence match -- CrossRef's bibliographic
search is a fuzzy match, not a lookup by known ID, so a wrong-but-plausible
DOI is a real failure mode here. Two independent signals are required before
a match is accepted: CrossRef's own relevance `score`, AND a title-similarity
ratio computed locally against the title we already extracted.
"""
from __future__ import annotations
import difflib
from dataclasses import dataclass
from typing import List, Optional

from config import settings

CROSSREF_WORKS_URL = "https://api.crossref.org/works"


@dataclass
class CrossRefMatch:
    accepted: bool
    doi: Optional[str] = None
    matched_title: Optional[str] = None
    matched_authors: Optional[List[str]] = None
    matched_year: Optional[int] = None
    crossref_score: Optional[float] = None
    title_similarity: Optional[float] = None
    reason: str = ""


def _title_similarity(a: str, b: str) -> float:
    norm = lambda s: " ".join(s.lower().split())
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def lookup_doi(
    title: str,
    authors: Optional[List[str]] = None,
    year: Optional[int] = None,
    timeout: float = 10.0,
) -> CrossRefMatch:
    """
    Queries CrossRef's bibliographic search and only ACCEPTS a result when:
      - title_similarity >= settings.CROSSREF_MIN_TITLE_SIMILARITY, AND
      - CrossRef's own relevance score clears settings.CROSSREF_MIN_SCORE
        (its scale is query-dependent, not 0-1, so this is a coarse floor,
        not treated as a probability)
    Anything short of that comes back with accepted=False and a `reason`
    explaining why -- callers should leave the DOI null rather than use a
    rejected candidate.
    """
    import requests  # local import: this module is the only thing in the
                      # pipeline with a hard runtime network dependency

    query_bits = {"query.bibliographic": title}
    if authors:
        query_bits["query.author"] = " ".join(authors[:3])  # CrossRef weighs more names as noise, not signal

    headers = {"User-Agent": settings.crossref_user_agent()}

    try:
        resp = requests.get(
            CROSSREF_WORKS_URL,
            params={**query_bits, "rows": 3},
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        items = resp.json()["message"]["items"]
    except Exception as e:  # network blocked, rate-limited, malformed response, etc.
        return CrossRefMatch(accepted=False, reason=f"CrossRef request failed: {e!r}")

    if not items:
        return CrossRefMatch(accepted=False, reason="CrossRef returned no candidates.")

    best = items[0]
    candidate_title = (best.get("title") or [""])[0]
    sim = _title_similarity(title, candidate_title)
    score = best.get("score")

    candidate_authors = [
        f"{a.get('given', '')} {a.get('family', '')}".strip()
        for a in best.get("author", [])
    ] or None
    candidate_year = None
    for date_field in ("published-print", "published-online", "issued"):
        parts = best.get(date_field, {}).get("date-parts")
        if parts and parts[0]:
            candidate_year = parts[0][0]
            break

    if sim < settings.CROSSREF_MIN_TITLE_SIMILARITY:
        return CrossRefMatch(
            accepted=False, doi=best.get("DOI"), matched_title=candidate_title,
            crossref_score=score, title_similarity=sim,
            reason=f"Top candidate's title similarity ({sim:.2f}) is below the "
                   f"{settings.CROSSREF_MIN_TITLE_SIMILARITY} threshold -- "
                   f"likely a different paper, not accepting.",
        )
    if score is not None and score < settings.CROSSREF_MIN_SCORE:
        return CrossRefMatch(
            accepted=False, doi=best.get("DOI"), matched_title=candidate_title,
            crossref_score=score, title_similarity=sim,
            reason=f"Title similarity looks fine ({sim:.2f}) but CrossRef's own "
                   f"relevance score ({score}) is below {settings.CROSSREF_MIN_SCORE} "
                   f"-- not accepting without a second confirming signal.",
        )
    if year and candidate_year and abs(int(year) - int(candidate_year)) > 1:
        return CrossRefMatch(
            accepted=False, doi=best.get("DOI"), matched_title=candidate_title,
            matched_year=candidate_year, crossref_score=score, title_similarity=sim,
            reason=f"Title matches well but publication year disagrees "
                   f"(extracted {year} vs CrossRef {candidate_year}) -- flagging "
                   f"rather than accepting silently.",
        )

    return CrossRefMatch(
        accepted=True, doi=best.get("DOI"), matched_title=candidate_title,
        matched_authors=candidate_authors, matched_year=candidate_year,
        crossref_score=score, title_similarity=sim,
        reason=f"Accepted: title_similarity={sim:.2f}, crossref_score={score}.",
    )
