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
from typing import Callable, List, Optional, Tuple

from parameter_extractor.errors import PaperSourceError

API_URL = "https://export.arxiv.org/api/query"
HTML_URL = "https://arxiv.org/html/{id}"
PDF_URL = "https://arxiv.org/pdf/{id}"
CROSSREF_URL = "https://api.crossref.org/works/{doi}"
ADS_URL = "https://api.adsabs.harvard.edu/v1/search/query"
USER_AGENT = "ParameterExtractor/0.1 (desktop research tool; reads papers the user names)"
MIN_INTERVAL_SEC = 3.0            # arXiv's API terms: no more than one request every three seconds
CROSSREF_INTERVAL_SEC = 1.0       # CrossRef's public pool answers 429 to bursts (a focused search of 19 papers)
RETRIES = 6                       # busy (429 / 503) or timed out: wait and try again (Retry-After, else
BACKOFF_SEC = (5, 10, 20, 40, 60, 60)   # these, ~3 min in all); a busy answer also slows the service down
MAX_INTERVAL_SEC = 15.0           # ... to at most one request per 15 s, easing back after successes
TIMEOUT_SEC = 60
TITLE_MATCH = 0.85                # title similarity needed to accept an arXiv search result

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_lock = threading.Lock()
_last_request = [0.0, MIN_INTERVAL_SEC]               # [time of the last request, current interval]
_crossref_lock = threading.Lock()
_crossref_last = [0.0, 0.0]

# identifiers -------------------------------------------------------------------------------------
_NEW_ID = r"\d{4}\.\d{4,5}"
_OLD_ID = r"[a-z][a-z\-]+(?:\.[A-Z]{2})?/\d{7}"
_ARXIV_ID = re.compile(rf"^(?:arxiv:\s*)?(?P<id>{_NEW_ID}|{_OLD_ID})(?P<v>v\d+)?$", re.IGNORECASE)
_ARXIV_URL = re.compile(rf"arxiv\.org/(?:abs|pdf|html)/(?P<id>{_NEW_ID}|{_OLD_ID})(?P<v>v\d+)?", re.IGNORECASE)
_DOI = re.compile(r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(?P<doi>10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
# the 14th character is a qualifier letter, '.', or a page digit when the page has 5+ digits
# (2024MNRAS.52710955B, 2024NatSR..1427219L -- Mickey's 1,389-paper run, 2026-10-25)
_BIBCODE = re.compile(r"^\d{4}[A-Za-z&.]{5}[A-Za-z0-9.]{4}[A-Za-z0-9.][A-Za-z0-9.]{4}[A-Za-z.]$")
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


class PaperRef(str):
    """A paper identifier as text (what lists and the GUI pass around), plus the reference label it came
    with, e.g. 'Tala Pinto et al. 2020' from an Exoplanet Archive reference link."""
    label: str = ""

    def __new__(cls, value: str, label: str = ""):
        obj = super().__new__(cls, value)
        obj.label = label
        return obj

    @property
    def first_author(self) -> str:
        """'Tala Pinto et al. 2020' -> 'Tala Pinto'; 'Michel & Mugrauer 2024' -> 'Michel'."""
        m = re.match(r"\s*(.+?)(?:\s+et\s+al\.?|\s*&|\s+and\s+|,|\s+\(?\d{4})", self.label or "")
        return m.group(1).strip() if m else ""


_ADS_URL = re.compile(r"adsabs\.harvard\.edu/(?:abs|cgi-bin/nph-bib_query\?bibcode=)/?(?P<bib>[^/\s\"'<>&?]{19})")


def identifier_in_cell(cell: str) -> Optional[PaperRef]:
    """One cell of a paper list -> its identifier: a bare arXiv ID / DOI / bibcode, or one inside a link --
    the NASA Exoplanet Archive's reference cells ('<a refstr=... href=https://ui.adsabs.harvard.edu/abs/
    2020A&A...644A...1T/abstract ...>Tala Pinto et al. 2020</a>'), an arxiv.org or doi.org link."""
    import html as _html
    text = urllib.parse.unquote(_html.unescape(cell or "")).strip()
    if not text:
        return None
    label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip() if "<" in text else ""
    m = re.search(r"adsabs\.harvard\.edu/abs/(?P<bib>\d{4}[^/\s\"'<>]{15})", text)
    if m:
        return PaperRef(m.group("bib"), label)
    found = parse_identifier(text)
    if found is None:
        m = _ARXIV_URL.search(text) or _DOI.search(text)
        found = parse_identifier(m.group(0)) if m else None
    return PaperRef(found.value if found.kind != "arxiv" else f"arXiv:{found.value}", label) if found else None


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


def _spaced(lock: threading.Lock, last: list, interval: float, req) -> bytes:
    """One request at a time per service, at least `interval` apart. A busy answer (429 / 503) or a
    timeout is retried after the wait the service asks for (Retry-After), else BACKOFF_SEC; a busy
    answer also doubles the service's spacing (up to MAX_INTERVAL_SEC), which eases back by 10% per
    success -- over 1,400 papers arXiv answered 429 / 503 / timed out on 44 of them (2026-10-25)."""
    import socket
    if not last[1]:
        last[1] = interval
    for attempt in range(RETRIES + 1):
        with lock:
            wait = last[0] + max(interval, last[1]) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                    data = resp.read()
                last[1] = max(interval, last[1] * 0.9)
                return data
            except urllib.error.HTTPError as e:
                if e.code not in (429, 503) or attempt == RETRIES:
                    raise
                last[1] = min(max(interval, last[1]) * 2, MAX_INTERVAL_SEC)
                retry_after = e.headers.get("Retry-After", "") if e.headers else ""
                pause = float(retry_after) if retry_after.isdigit() else BACKOFF_SEC[attempt]
            except (TimeoutError, socket.timeout, urllib.error.URLError) as e:
                if attempt == RETRIES or (isinstance(e, urllib.error.URLError)
                                          and not isinstance(getattr(e, "reason", None), (TimeoutError, socket.timeout,
                                                                                           ConnectionError, OSError))):
                    raise
                pause = BACKOFF_SEC[attempt]
            finally:
                last[0] = time.monotonic()
        time.sleep(min(pause, 120.0))
    raise RuntimeError("unreachable")


def _get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None, arxiv: bool = True) -> bytes:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    if arxiv:                                         # one arXiv request at a time, 3 s apart
        return _spaced(_lock, _last_request, MIN_INTERVAL_SEC, req)
    if "crossref.org" in url:
        return _spaced(_crossref_lock, _crossref_last, CROSSREF_INTERVAL_SEC, req)
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
    """The title's longest plain words (letters only: arXiv rejects 'ti:low-density' / 'ti:CoRoT-' with a
    400 -- 2026-10-25, CoRoT XXIV), each once."""
    stop = {"the", "and", "for", "with", "from", "into", "around", "using", "new", "of", "in", "on", "a", "an",
            "this", "that", "their", "between", "through"}
    words = [w for w in re.findall(r"(?<![A-Za-z0-9])[A-Za-z]{4,}(?![A-Za-z0-9])", title) if w.lower() not in stop]
    return sorted(dict.fromkeys(words), key=len, reverse=True)[:n]


def by_title(title: str, first_author_surname: str = "") -> Optional[ArxivRecord]:
    """An arXiv search by title words (+ first author), accepted only on a close title match. A few
    queries with different words: a journal's spelling can differ from the preprint's
    ('Characterising' / 'Characterizing', Moutou 2026), and arXiv's author search wants one surname
    word ('Tala Pinto' -> Pinto)."""
    words = _title_words(title, 8)
    if not words:
        return None
    author = re.sub(r"[^A-Za-z\-]", "", (first_author_surname or "").split()[-1]) if first_author_surname else ""
    au = [f"au:{author}"] if author else []
    queries = [au + [f"ti:{w}" for w in words[:3]], [f"ti:{w}" for w in words[:5]]]
    if author and len(words) > 3:
        queries.append(au + [f"ti:{w}" for w in words[3:6]])
    seen = set()
    for terms in queries:
        key = " AND ".join(terms)
        if key in seen or not terms:
            continue
        seen.add(key)
        try:
            candidates = query(key, max_results=5)
        except PaperSourceError:
            continue                                   # one rejected query doesn't end the search
        best = max(candidates, key=lambda r: _similar(r.title, title), default=None)
        if best and _similar(best.title, title) >= TITLE_MATCH:
            return best
    return None


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
    title = (m.get("title") or [""])[0] + "".join(f". {t}" for t in (m.get("subtitle") or []) if t)
    title = " ".join(re.sub(r"<[^>]+>", "", title).split())     # '<i>Gaia</i> search ...' -> plain
    authors = m.get("author") or []
    journal = ((m.get("short-container-title") or m.get("container-title") or [""])[0] or "").strip()
    year = ((m.get("published") or m.get("issued") or {}).get("date-parts") or [[None]])[0][0]
    published = f"{journal} ({year})" if journal and year else journal
    return title, (authors[0].get("family") or "") if authors else "", published


def by_doi(doi: str, title_search_only: bool = False) -> ArxivRecord:
    """`title_search_only`: arXiv's doi: search was already asked (resolve_many) -- go straight to the
    CrossRef title fallback."""
    found = [] if title_search_only else [r for r in query(f'doi:"{doi}"', max_results=3)
                                           if r.doi.lower() == doi.lower()]
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


# journal bibcodes without an ADS token (Mickey's Exoplanet Archive export, 2026-10-24): a bibcode
# spells out year, journal, volume and first page; CrossRef, filtered by the journal's ISSN, the year
# and (if known) the first author, finds the article whose volume and page match -> its DOI.
JOURNAL_ISSNS = {
    "A&A": ["0004-6361", "1432-0746"], "ApJ": ["0004-637X", "1538-4357"], "ApJL": ["2041-8205", "2041-8213"],
    "ApJS": ["0067-0049", "1538-4365"], "AJ": ["0004-6256", "1538-3881"], "MNRAS": ["0035-8711", "1365-2966", "1745-3925", "1745-3933"],
    "PASJ": ["0004-6264", "2053-051X"], "PASP": ["0004-6280", "1538-3873"], "Sci": ["0036-8075", "1095-9203"],
    "Natur": ["0028-0836", "1476-4687"], "NatAs": ["2397-3366"], "AN": ["0004-6337", "1521-3994"],
    "Icar": ["0019-1035", "1090-2643"], "PSJ": ["2632-3338"], "RNAAS": ["2515-5172"],
    "A&ARv": ["0935-4956", "1432-0754"], "ARA&A": ["0066-4146", "1545-4282"], "NatCo": ["2041-1723"],
    "PNAS": ["0027-8424", "1091-6490"], "SSRv": ["0038-6308", "1572-9672"], "EM&P": ["0167-9295", "1573-0794"],
    "NatSR": ["2045-2322"], "PASA": ["1323-3580", "1448-6083"], "RAA": ["1674-4527"], "AcA": ["0001-5237"],
    "JApA": ["0250-6335", "0973-7758"], "ExA": ["0922-6435", "1572-9508"], "Galax": ["2075-4434"],
    "Univ": ["2218-1997"], "FrASS": ["2296-987X"], "NewA": ["1384-1076"], "Ap&SS": ["0004-640X", "1572-946X"],
}


@dataclass
class Bibcode:
    year: int
    journal: str                  # 'A&A', 'ApJ', 'MNRAS', ...
    volume: str
    page: str                     # 'A1', 'L5', '583' (letter qualifiers kept: A&A article numbers, letters)
    initial: str

    @classmethod
    def parse(cls, bibcode: str) -> Optional["Bibcode"]:
        if len(bibcode) != 19 or not bibcode[:4].isdigit():
            return None
        journal, volume, qualifier = bibcode[4:9].strip("."), bibcode[9:13].strip("."), bibcode[13]
        page = bibcode[14:18].strip(".")
        if qualifier.isalpha():
            page = qualifier + page
        elif qualifier.isdigit():                        # a 5-digit page: 10955
            page = (qualifier + bibcode[14:18]).lstrip("0")
        if journal == "ApJ" and qualifier == "L":
            journal = "ApJL"
        return cls(int(bibcode[:4]), journal, volume, page, bibcode[18])


def _first_page(item: dict) -> str:
    page = (item.get("page") or "").split("-")[0].strip()
    return (item.get("article-number") or page or "").strip()


def _same_page(bib: Bibcode, item: dict) -> bool:
    found = _first_page(item).upper()
    want = bib.page.upper()
    digits = lambda t: re.sub(r"\D", "", t).lstrip("0")
    return bool(found) and (found == want or (digits(found) == digits(want) and digits(want) != ""))


# IOP's older DOIs are built from volume / issue / page (10.1088/0004-637X/812/2/112): journal ->
# (ISSN in the DOI, issues per volume)
IOP_DOI = {"ApJ": ("0004-637X", 2), "ApJL": ("2041-8205", 2), "ApJS": ("0067-0049", 2), "AJ": ("0004-6256", 6)}
LISTING_PAGES = 20                # whole-journal listing fallback: at most 20 x 1000 articles per year
_listings: dict = {}              # (journal, year) -> [CrossRef items]: one listing serves a whole run
_listings_lock = threading.Lock()


def _works(params: dict) -> dict:
    try:
        return json.loads(_get(CROSSREF_URL.format(doi="").rstrip("/"), params, arxiv=False))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise _network_error("CrossRef", e) from e


def _matching(bib: "Bibcode", items) -> Optional[str]:
    for item in items:
        if (item.get("volume") or "").strip() == bib.volume and _same_page(bib, item):
            return item["DOI"]
    return None


def _iop_doi(bib: "Bibcode") -> Optional[str]:
    """Older ApJ / AJ DOIs follow volume / issue / page: try the few possible issues (CrossRef lookups)."""
    if bib.journal not in IOP_DOI or not bib.page.isdigit():
        return None
    issn, issues = IOP_DOI[bib.journal]
    prefixes = ["10.1088", "10.3847"] if bib.year < 2016 else ["10.3847", "10.1088"]
    for prefix in prefixes:
        for issue in range(1, issues + 1):
            doi = f"{prefix}/{issn}/{bib.volume}/{issue}/{bib.page}"
            try:
                data = json.loads(_get(CROSSREF_URL.format(doi=doi), arxiv=False))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue
                raise _network_error("CrossRef", e) from e
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                raise _network_error("CrossRef", e) from e
            if _matching(bib, [data.get("message", {})]):
                return data["message"]["DOI"]
    return None


def _listing_doi(bib: "Bibcode", issns: List[str]) -> Optional[str]:
    """Last resort: every article CrossRef lists for the journal in the bibcode's year (cursor pages
    of 1000, kept for the run), matched on volume and page locally."""
    key = (bib.journal, bib.year)
    with _listings_lock:
        items = _listings.get(key)
    if items is None:
        items, cursor = [], "*"
        for _ in range(LISTING_PAGES):
            data = _works({"rows": 1000, "cursor": cursor, "select": "DOI,volume,page,article-number",
                           "filter": f"from-pub-date:{bib.year},until-pub-date:{bib.year},"
                                     + ",".join(f"issn:{i}" for i in issns)}).get("message", {})
            batch = data.get("items", [])
            items += batch
            cursor = data.get("next-cursor")
            if len(batch) < 1000 or not cursor:
                break
        with _listings_lock:
            _listings[key] = items
    return _matching(bib, items)


def doi_from_bibcode(bibcode: str, surname: str = "") -> str:
    """A journal bibcode's DOI via CrossRef (no ADS token): the article with the bibcode's volume and
    first page in that journal and year. Searched by first author when known, else by volume + page;
    then (older ApJ / AJ) the DOI pattern; then the journal's whole listing for that year (2026-10-25:
    20 of 22 label-less bibcodes missed by the volume + page search alone). PaperSourceError when it
    can't be pinned down."""
    bib = Bibcode.parse(bibcode)
    if bib is None:
        raise PaperSourceError(f"'{bibcode}' isn't a valid ADS bibcode.")
    issns = JOURNAL_ISSNS.get(bib.journal)
    params = {"rows": 100, "select": "DOI,volume,page,article-number,issued,title,author",
              "filter": f"from-pub-date:{bib.year - 1},until-pub-date:{bib.year + 1}"}
    if issns:
        params["filter"] += "," + ",".join(f"issn:{i}" for i in issns)
        if surname:
            params["query.author"] = surname
        else:
            params["query.bibliographic"] = f"{bib.volume} {bib.page} {bib.initial}"
    else:
        params["query.bibliographic"] = f"{bib.journal} {bib.volume} {bib.page} {bib.year} {surname}".strip()
    found = _matching(bib, _works(params).get("message", {}).get("items", []))
    if found is None and issns:
        found = _iop_doi(bib) or _listing_doi(bib, issns)
    if found:
        return found
    raise PaperSourceError(f"ADS bibcode {bibcode} ({bib.journal} {bib.volume}, {bib.page}, {bib.year}): no "
                           f"matching article found without an ADS token. Add an ADS token in Settings, or give "
                           f"its DOI or arXiv ID.")


def by_bibcode(bibcode: str, ads_token: str = "", surname: str = "") -> ArxivRecord:
    m = _ARXIV_BIBCODE.match(bibcode)
    if m:
        return by_arxiv_id(f"{m.group(1)}.{m.group(2)}")
    if not ads_token:                                  # no token: journal, volume, page -> CrossRef -> DOI
        return by_doi(doi_from_bibcode(bibcode, surname))
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


def resolve(identifier, ads_token: str = "", surname: str = "") -> ArxivRecord:
    """An Identifier (or text) -> its arXiv record. PaperSourceError says why not."""
    ident = identifier if isinstance(identifier, Identifier) else parse_identifier(str(identifier))
    if ident is None:
        raise PaperSourceError(f"'{identifier}' isn't an arXiv ID, DOI or ADS bibcode.")
    if ident.kind == "arxiv":
        return by_arxiv_id(ident.value)
    if ident.kind == "doi":
        return by_doi(ident.value)
    return by_bibcode(ident.value, ads_token, surname or getattr(identifier, "first_author", ""))


# many papers at once -----------------------------------------------------------------------------
# A focused search over ~1,400 papers spent most of its arXiv time on one metadata query per paper
# (2026-10-25). Lookups are batched -- arXiv answers 20 DOIs or 50 IDs per query -- and kept in a cache
# (with the full texts), so a second search over the same papers downloads nothing.
DOI_BATCH, ID_BATCH = 20, 50
CACHE_RECHECK_DAYS = 30           # "not on arXiv" is asked again after this (preprints appear late)


class LookupCache:
    """Identifier -> arXiv record (or why there's none), and arXiv full texts, on disk. Thread-safe;
    `save()` writes the lookups (texts are written as they come)."""
    def __init__(self, folder: Optional[Path]):
        self.folder = Path(folder) if folder else None
        self._lock = threading.Lock()
        self._lookups: dict = {}
        self._dirty = False
        if self.folder:
            (self.folder / "texts").mkdir(parents=True, exist_ok=True)
            path = self.folder / "lookups.json"
            try:
                self._lookups = json.loads(path.read_text()) if path.is_file() else {}
            except (OSError, ValueError):
                self._lookups = {}

    def record(self, key: str):
        """An ArxivRecord, a PaperSourceError (cached 'not on arXiv'), or None (not cached)."""
        with self._lock:
            entry = self._lookups.get(key)
        if not entry:
            return None
        if "record" in entry:
            return ArxivRecord(**entry["record"])
        if time.time() - entry.get("when", 0) > CACHE_RECHECK_DAYS * 86400:
            return None
        return PaperSourceError(entry["missing"])

    def put(self, key: str, found) -> None:
        if not self.folder:
            return
        entry = ({"record": found.to_dict()} if isinstance(found, ArxivRecord) else
                 {"missing": str(found), "when": time.time()} if isinstance(found, PaperSourceError) and
                 "isn't on arXiv" in str(found) else None)       # network trouble is never cached
        if entry is not None:
            with self._lock:
                self._lookups[key] = entry
                self._dirty = True

    def save(self) -> None:
        if self.folder and self._dirty:
            with self._lock:
                tmp = self.folder / "lookups.json.tmp"
                tmp.write_text(json.dumps(self._lookups))
                tmp.replace(self.folder / "lookups.json")
                self._dirty = False

    def _text_path(self, record: "ArxivRecord") -> Optional[Path]:
        return self.folder / "texts" / (record.versioned_id.replace("/", "_") + ".txt.gz") if self.folder else None

    def text(self, record: "ArxivRecord"):
        """The cached full text; '' when arXiv has no HTML for it; None when not cached."""
        path = self._text_path(record)
        if path is None:
            return None
        if path.with_suffix(".none").is_file():
            return ""
        if path.is_file():
            import gzip
            return gzip.decompress(path.read_bytes()).decode("utf-8")
        return None

    def put_text(self, record: "ArxivRecord", text: Optional[str]) -> None:
        path = self._text_path(record)
        if path is None:
            return
        if text:
            import gzip
            path.write_bytes(gzip.compress(text.encode("utf-8")))
        else:
            path.with_suffix(".none").write_text("")


def _chunks(seq: list, n: int):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def resolve_many(items, ads_token: str = "", cache: Optional[LookupCache] = None,
                 note: Callable[[str], None] = lambda m: None) -> dict:
    """{str(item): ArxivRecord or PaperSourceError} for many identifiers (PaperRef / text) at once:
    arXiv IDs 50 per query, DOIs 20 per query (`doi:"a" OR doi:"b"`), the rest one by one as before
    (CrossRef title fallback; bibcode -> DOI). Network trouble for one paper is its error only."""
    cache = cache or LookupCache(None)
    out: dict = {}
    todo = []
    for item in items:
        key = str(item)
        cached = cache.record(key)
        if cached is not None:
            out[key] = cached
        else:
            todo.append(item)
    if out:
        note(f"{len(out)} paper(s) already looked up (cache)")
    ids, dois, bibcodes = {}, {}, []
    for item in todo:
        ident = parse_identifier(str(item))
        if ident is None:
            out[str(item)] = PaperSourceError(f"'{item}' isn't an arXiv ID, DOI or ADS bibcode.")
        elif ident.kind == "arxiv":
            ids[str(item)] = ident.value
        elif ident.kind == "doi":
            dois[str(item)] = ident.value
        elif _ARXIV_BIBCODE.match(ident.value):
            m = _ARXIV_BIBCODE.match(ident.value)
            ids[str(item)] = f"{m.group(1)}.{m.group(2)}"
        else:
            bibcodes.append(item)
    # journal bibcodes -> DOIs (CrossRef, or ADS with a token); then they join the DOI lookups
    for n, item in enumerate(bibcodes, 1):
        if n % 25 == 1:
            note(f"Finding DOIs for bibcodes ({n} of {len(bibcodes)})")
        try:
            if ads_token:
                out[str(item)] = by_bibcode(str(item), ads_token)
            else:
                dois[str(item)] = doi_from_bibcode(str(item), getattr(item, "first_author", ""))
        except PaperSourceError as e:
            out[str(item)] = e
    # arXiv IDs, 50 per query
    for group in _chunks(list(ids.items()), ID_BATCH):
        note(f"Looking up {len(group)} arXiv ID(s)")
        try:
            unique = list(dict.fromkeys(re.sub(r"v\d+$", "", a) for _, a in group))
            found = {r.arxiv_id: r for r in query(id_list=",".join(unique), max_results=len(unique))}
        except PaperSourceError as e:
            found, error = {}, e
        else:
            error = None
        for key, aid in group:
            base, version = re.sub(r"v\d+$", "", aid), (re.search(r"(v\d+)$", aid) or [None, ""])[1]
            r = found.get(base)
            if r is not None:
                out[key] = ArxivRecord(**{**r.to_dict(), "version": version or r.version})
            else:
                out[key] = error or PaperSourceError(f"arXiv has no paper {aid}.")
    # DOIs, 20 per query; the ones arXiv doesn't list go the slow way (CrossRef title -> title search)
    misses = []
    for group in _chunks(list(dois.items()), DOI_BATCH):
        note(f"Looking up {len(group)} DOI(s) on arXiv")
        try:
            records = query(" OR ".join(f'doi:"{d}"' for _, d in group), max_results=len(group) * 2)
        except PaperSourceError:
            misses += group
            continue
        by_doi_found = {r.doi.lower(): r for r in records if r.doi}
        for key, doi in group:
            r = by_doi_found.get(doi.lower())
            if r is not None:
                out[key] = r
            else:
                misses.append((key, doi))
    for n, (key, doi) in enumerate(misses, 1):
        if n % 10 == 1:
            note(f"Searching arXiv by title for papers whose DOI it doesn't list ({n} of {len(misses)})")
        try:
            out[key] = by_doi(doi, title_search_only=True)
        except PaperSourceError as e:
            out[key] = e
    for key, found in out.items():
        cache.put(key, found)
    cache.save()
    return out


# full text ---------------------------------------------------------------------------------------
def fetch_html_text(record: ArxivRecord, save_to: Optional[Path] = None,
                    cache: Optional[LookupCache] = None) -> Optional[str]:
    """The paper's text from arXiv's HTML rendering, or None when arXiv has none for it. With a
    cache, a text read before isn't downloaded again."""
    if cache is not None:
        cached = cache.text(record)
        if cached is not None:
            return cached or None
    text = _fetch_html_text(record, save_to)
    if cache is not None:
        cache.put_text(record, text)
    return text


def _fetch_html_text(record: ArxivRecord, save_to: Optional[Path] = None) -> Optional[str]:
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
