"""
Papers from arXiv by identifier: an arXiv ID, a DOI or an ADS bibcode -> the arXiv record and its
full text (evaluated 2026-10-24, see CLAUDE.md "arXiv full text evaluated").

- export.arxiv.org/api/query gives METADATA only (title, authors, DOI, journal reference, versions).
- The full text comes from arxiv.org/html/<id> (LaTeXML rendering of the source; tables as text
  with exact uncertainties -- ingestion/html_text.py), else the PDF at arxiv.org/pdf/<id>.
- DOI -> arXiv: arXiv's own `doi:` search works only when the authors entered the DOI (teng2023's
  2308.05343 has none), so the fallback is CrossRef's title + first author for that DOI, then an
  arXiv title/author search accepted only on a close title match.
- ADS bibcodes: arXiv-style ones (2023arXiv230805343T) contain the ID; journal ones need the ADS API
  and the user's ADS token (free account at ui.adsabs.harvard.edu).
- arXiv asks for at most one request every 3 seconds: all arXiv requests share one rate limit.

Values come from a PREPRINT; the version is recorded so a run says exactly what it read.
Standard library HTTP (urllib), like pubchem.py.
"""
from __future__ import annotations
import difflib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from parameter_extractor.errors import PaperSourceError

API_URL = "https://export.arxiv.org/api/query"
HTML_URL = "https://arxiv.org/html/{id}"
PDF_URL = "https://arxiv.org/pdf/{id}"
CROSSREF_URL = "https://api.crossref.org/works/{doi}"
ADS_URL = "https://api.adsabs.harvard.edu/v1/search/query"
USER_AGENT = "ParameterExtractor/0.1 (desktop research tool; reads papers the user names)"
MIN_INTERVAL_SEC = 3.0            # arXiv's API terms: no more than one request every three seconds
TIMEOUT_SEC = 60
TITLE_MATCH = 0.85                # title similarity needed to accept an arXiv search result

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_lock = threading.Lock()
_last_request = [0.0]

# identifiers -------------------------------------------------------------------------------------
_NEW_ID = r"\d{4}\.\d{4,5}"
_OLD_ID = r"[a-z][a-z\-]+(?:\.[A-Z]{2})?/\d{7}"
_ARXIV_ID = re.compile(rf"^(?:arxiv:\s*)?(?P<id>{_NEW_ID}|{_OLD_ID})(?P<v>v\d+)?$", re.IGNORECASE)
_ARXIV_URL = re.compile(rf"arxiv\.org/(?:abs|pdf|html)/(?P<id>{_NEW_ID}|{_OLD_ID})(?P<v>v\d+)?", re.IGNORECASE)
_DOI = re.compile(r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(?P<doi>10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
_BIBCODE = re.compile(r"^\d{4}[A-Za-z&.]{5}[A-Za-z0-9.]{4}[A-Za-z.][A-Za-z0-9.]{4}[A-Za-z.]$")
_ARXIV_BIBCODE = re.compile(r"^\d{4}arXiv(\d{4})(\d{4,5})[A-Z.]$")
# an arXiv stamp or reference printed in a PDF ("arXiv:2308.05343v1 [astro-ph.EP] 10 Aug 2023")
_ARXIV_IN_TEXT = re.compile(rf"arXiv:\s*(?P<id>{_NEW_ID}|{_OLD_ID})(?P<v>v\d+)?", re.IGNORECASE)


@dataclass
class Identifier:
    kind: str                     # "arxiv" | "doi" | "bibcode"
    value: str                    # the arXiv ID (version kept if given), the DOI or the bibcode

    def __str__(self) -> str:
        return {"arxiv": "arXiv:", "doi": "DOI ", "bibcode": "ADS "}[self.kind] + self.value


def parse_identifier(text: str) -> Optional[Identifier]:
    """'2308.05343', 'arXiv:2308.05343v1', an arxiv.org link, '10.1093/pasj/psad056' (or a doi.org
    link), '2023PASJ...75.1030T' -> Identifier; None if it's none of these."""
    t = (text or "").strip().strip(",;")
    if not t:
        return None
    m = _ARXIV_ID.match(t) or _ARXIV_URL.search(t)
    if m:
        return Identifier("arxiv", m.group("id") + (m.group("v") or ""))
    m = _DOI.match(t)
    if m:
        return Identifier("doi", m.group("doi").rstrip(".,;)"))
    if _ARXIV_BIBCODE.match(t) or _BIBCODE.match(t):
        return Identifier("bibcode", t)
    return None


def identifier_in_text(text: str) -> Optional[Identifier]:
    """An arXiv ID or DOI printed in a paper's first pages (to find a local PDF on arXiv)."""
    m = _ARXIV_IN_TEXT.search(text or "")
    if m:
        return Identifier("arxiv", m.group("id") + (m.group("v") or ""))
    m = _DOI.search(text or "")
    if m:
        return Identifier("doi", m.group("doi").rstrip(".,;)"))
    return None


# the arXiv record --------------------------------------------------------------------------------
@dataclass
class ArxivRecord:
    arxiv_id: str                 # without version, e.g. "2308.05343"
    version: str                  # e.g. "v1"
    title: str
    authors: List[str] = field(default_factory=list)
    doi: str = ""
    journal_ref: str = ""
    published: str = ""           # first version's date, ISO
    updated: str = ""
    comment: str = ""

    @property
    def versioned_id(self) -> str:
        return self.arxiv_id + self.version

    @property
    def label(self) -> str:
        return f"arXiv:{self.versioned_id}"

    @property
    def year(self) -> Optional[int]:
        m = re.search(r"\((\d{4})\)|\b(19|20)\d{2}\b", self.journal_ref or "")
        if m:
            return int(m.group(1) or m.group(0))
        return int(self.published[:4]) if self.published[:4].isdigit() else None

    def to_dict(self) -> dict:
        return asdict(self)


def _get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None, arxiv: bool = True) -> bytes:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    if arxiv:
        with _lock:                                   # one arXiv request at a time, 3 s apart
            wait = _last_request[0] + MIN_INTERVAL_SEC - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                    return resp.read()
            finally:
                _last_request[0] = time.monotonic()
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return resp.read()


def _network_error(what: str, e: Exception) -> PaperSourceError:
    return PaperSourceError(f"Couldn't reach {what} ({e}). Check the internet connection and try again.")


def parse_feed(xml: bytes) -> List[ArxivRecord]:
    """The arXiv API's Atom feed -> records."""
    root = ET.fromstring(xml)
    records = []
    for entry in root.findall(f"{_ATOM}entry"):
        raw_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        m = re.search(rf"abs/(?P<id>{_NEW_ID}|{_OLD_ID})(?P<v>v\d+)?$", raw_id)
        if not m:
            continue                                   # an error entry, not a paper
        records.append(ArxivRecord(
            arxiv_id=m.group("id"), version=m.group("v") or "",
            title=" ".join((entry.findtext(f"{_ATOM}title") or "").split()),
            authors=[" ".join((a.findtext(f"{_ATOM}name") or "").split()) for a in entry.findall(f"{_ATOM}author")],
            doi=(entry.findtext(f"{_ARXIV}doi") or "").strip(),
            journal_ref=" ".join((entry.findtext(f"{_ARXIV}journal_ref") or "").split()),
            published=(entry.findtext(f"{_ATOM}published") or "")[:10],
            updated=(entry.findtext(f"{_ATOM}updated") or "")[:10],
            comment=" ".join((entry.findtext(f"{_ARXIV}comment") or "").split())))
    return records


def query(search_query: str = "", id_list: str = "", max_results: int = 5) -> List[ArxivRecord]:
    params = {"max_results": max_results}
    if search_query:
        params["search_query"] = search_query
    if id_list:
        params["id_list"] = id_list
    try:
        return parse_feed(_get(API_URL, params))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise _network_error("arXiv", e) from e
    except ET.ParseError as e:
        raise PaperSourceError(f"arXiv sent an unreadable answer ({e}).") from e


def by_arxiv_id(arxiv_id: str) -> ArxivRecord:
    found = query(id_list=arxiv_id, max_results=1)
    if not found:
        raise PaperSourceError(f"arXiv has no paper {arxiv_id}.")
    record = found[0]
    m = re.search(r"(v\d+)$", arxiv_id)
    if m:                                              # the version asked for, not the latest
        record.version = m.group(1)
    return record


def _similar(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def _title_words(title: str, n: int = 6) -> List[str]:
    stop = {"the", "and", "for", "with", "from", "into", "around", "using", "new", "of", "in", "on", "a", "an"}
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", title) if w.lower() not in stop]
    return sorted(words, key=len, reverse=True)[:n]


def by_title(title: str, first_author_surname: str = "") -> Optional[ArxivRecord]:
    """An arXiv search by title words (+ first author), accepted only on a close title match."""
    words = _title_words(title)
    if not words:
        return None
    terms = [f"ti:{w}" for w in words] + ([f"au:{first_author_surname}"] if first_author_surname else [])
    candidates = query(" AND ".join(terms), max_results=5)
    best = max(candidates, key=lambda r: _similar(r.title, title), default=None)
    return best if best and _similar(best.title, title) >= TITLE_MATCH else None


def _crossref(doi: str) -> Tuple[str, str, str]:
    """(title, first author's surname, 'Journal (year)') for a DOI, from CrossRef."""
    try:
        data = json.loads(_get(CROSSREF_URL.format(doi=urllib.parse.quote(doi)), arxiv=False))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise PaperSourceError(f"No paper with the DOI {doi} was found (CrossRef).") from e
        raise _network_error("CrossRef", e) from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise _network_error("CrossRef", e) from e
    m = data.get("message", {})
    title = " ".join((m.get("title") or [""])[0].split())
    authors = m.get("author") or []
    journal = ((m.get("short-container-title") or m.get("container-title") or [""])[0] or "").strip()
    year = ((m.get("published") or m.get("issued") or {}).get("date-parts") or [[None]])[0][0]
    published = f"{journal} ({year})" if journal and year else journal
    return title, (authors[0].get("family") or "") if authors else "", published


def by_doi(doi: str) -> ArxivRecord:
    found = [r for r in query(f'doi:"{doi}"', max_results=3) if r.doi.lower() == doi.lower()]
    if found:
        return found[0]
    title, surname, published = _crossref(doi)
    record = by_title(title, surname) if title else None
    if record is None:
        raise PaperSourceError(f"DOI {doi} ('{title[:80]}') isn't on arXiv, or arXiv's version has a "
                               f"different title. Use a local PDF for it.")
    if not record.doi:
        record.doi = doi
    if not record.journal_ref and published:
        record.journal_ref = published            # where it was published, from the DOI (CrossRef)
    return record


def by_bibcode(bibcode: str, ads_token: str = "") -> ArxivRecord:
    m = _ARXIV_BIBCODE.match(bibcode)
    if m:
        return by_arxiv_id(f"{m.group(1)}.{m.group(2)}")
    if not ads_token:
        raise PaperSourceError(f"ADS bibcode {bibcode}: looking it up needs an ADS API token (Settings). "
                               f"Or give its DOI or arXiv ID instead.")
    try:
        data = json.loads(_get(ADS_URL, {"q": f'bibcode:"{bibcode}"', "fl": "identifier,doi,title"},
                               headers={"Authorization": f"Bearer {ads_token}"}, arxiv=False))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise PaperSourceError("ADS rejected the API token. Check it in Settings.") from e
        raise _network_error("NASA ADS", e) from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise _network_error("NASA ADS", e) from e
    docs = data.get("response", {}).get("docs", [])
    if not docs:
        raise PaperSourceError(f"ADS has no paper with the bibcode {bibcode}.")
    for ident in docs[0].get("identifier", []):
        found = parse_identifier(ident)
        if found and found.kind == "arxiv":
            return by_arxiv_id(found.value)
        arxiv_bib = _ARXIV_BIBCODE.match(ident)
        if arxiv_bib:
            return by_arxiv_id(f"{arxiv_bib.group(1)}.{arxiv_bib.group(2)}")
    dois = docs[0].get("doi") or []
    if dois:
        return by_doi(dois[0])
    raise PaperSourceError(f"ADS lists no arXiv version of {bibcode}. Use a local PDF for it.")


def resolve(identifier, ads_token: str = "") -> ArxivRecord:
    """An Identifier (or text) -> its arXiv record. PaperSourceError says why not."""
    ident = identifier if isinstance(identifier, Identifier) else parse_identifier(str(identifier))
    if ident is None:
        raise PaperSourceError(f"'{identifier}' isn't an arXiv ID, DOI or ADS bibcode.")
    if ident.kind == "arxiv":
        return by_arxiv_id(ident.value)
    if ident.kind == "doi":
        return by_doi(ident.value)
    return by_bibcode(ident.value, ads_token)


# full text ---------------------------------------------------------------------------------------
def fetch_html_text(record: ArxivRecord, save_to: Optional[Path] = None) -> Optional[str]:
    """The paper's text from arXiv's HTML rendering, or None when arXiv has none for it."""
    from parameter_extractor.ingestion.html_text import html_to_text, looks_like_paper
    try:
        raw = _get(HTML_URL.format(id=record.versioned_id))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise _network_error("arXiv", e) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise _network_error("arXiv", e) from e
    html = raw.decode("utf-8", errors="replace")
    if not looks_like_paper(html):
        return None
    if save_to is not None:
        save_to.write_text(html, encoding="utf-8")
    text = html_to_text(html)
    return text if len(text) > 2000 else None         # a stub page, not the paper


def fetch_pdf(record: ArxivRecord, dest: Path) -> Path:
    try:
        dest.write_bytes(_get(PDF_URL.format(id=record.versioned_id)))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise _network_error("arXiv", e) from e
    return dest
