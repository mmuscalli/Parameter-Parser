"""
Is a "quote" really the paper's words?

The model is asked for verbatim quotes, but sometimes writes its own
description instead (eder1994: "Table 1 conditions list the reaction
temperature, 81 C"). Shown as "Quote from the paper", that misleads. Each
flag's quote is checked against the paper's extracted text; parts not found
word for word are moved to `unverified_quote` and labelled as such.

The comparison ignores case, spacing, punctuation and symbols (°, µ, the
PDF's "(cid:N)" placeholders), so line breaks and hyphenation don't count as
differences. A quote that isn't in the text but whose source is a table that
was sent to the model as an IMAGE (tables' text layers are often garbled) is
reported as read from a table image rather than as the model's wording.

Two-column pages come out of the PDF with the columns' lines
interleaved (eder1994), so a quote's words are matched IN ORDER with gaps
allowed for the other column's text in between, and a few words may be
missing (OCR, a line split across columns). A value read from a table IMAGE can fail the check when the
table's text layer is garbled -- the label says that too.
"""
from __future__ import annotations
import bisect
import re
from typing import Iterable, List, Optional

QUOTE_SEPARATOR = " | "          # grouped flags join several quotes with this


def compact(text: str) -> str:
    text = re.sub(r"\(cid:\d+\)", "", text or "")
    text = re.sub(r"-\s*\n\s*", "", text)                 # words hyphenated across lines
    return re.sub(r"[^0-9a-z]+", "", text.lower())


MAX_GAP_WORDS = 40          # other-column text between two consecutive words of a quote
MIN_MATCHED = 0.85          # share of a quote's words that must be found in order (sub/superscripts drift)
SHORT_QUOTE_WORDS = 4       # shorter quotes must match exactly (no gaps, nothing missing)


def words(text: str) -> list:
    text = re.sub(r"\(cid:\d+\)", " ", text or "")
    text = re.sub(r"-\s*\n\s*", "", text)
    return re.findall(r"[0-9]+|[a-z]+", text.lower())      # "0.5M" = "0.5 M"; "Gly13" = "Gly 13"


class PaperText:
    """The paper for quote matching. Given its pages, it also says which page a quote is on --
    kept with every value (CellSource.page, Flag.page), so a short quote can be found in context."""
    def __init__(self, text: str, page_texts: Optional[List[str]] = None):
        pages = page_texts if page_texts else [text]
        self.compact, self.words = "", []
        self._compact_starts, self._word_starts = [], []
        for page in pages:
            self._compact_starts.append(len(self.compact))
            self._word_starts.append(len(self.words))
            self.compact += compact(page)
            self.words += words(page)
        self.paged = bool(page_texts)
        self.positions: dict = {}
        for i, w in enumerate(self.words):
            self.positions.setdefault(w, []).append(i)

    def page_of(self, quote: str) -> Optional[int]:
        """1-based page the quote starts on, or None (not found / no pages given)."""
        found = self._find(quote)
        if found is None or not self.paged:
            return None
        kind, at = found
        starts = self._compact_starts if kind == "compact" else self._word_starts
        return bisect.bisect_right(starts, at)

    def _next(self, word: str, after: int, limit: int):
        for p in self.positions.get(word, ()):
            if after < p <= limit:
                return p
        return None

    def contains(self, quote: str) -> bool:
        return self._find(quote) is not None

    def _find(self, quote: str):
        """("compact", offset) or ("words", index) of the match, or None."""
        quote = (quote or "").replace("…", " ")          # a quote cut to length (schemas.common.capped)
        q = compact(quote)
        if not q:
            return None
        at = self.compact.find(q)
        if at >= 0:
            return "compact", at
        qw = words(quote)
        if len(qw) <= SHORT_QUOTE_WORDS:
            return None
        allowed_missing = int(len(qw) * (1 - MIN_MATCHED))
        for start_word in range(allowed_missing + 1):          # the first words may be the missing ones
            for start in self.positions.get(qw[start_word], ()):
                pos, missing = start, start_word
                for w in qw[start_word + 1:]:
                    nxt = self._next(w, pos, pos + MAX_GAP_WORDS)
                    if nxt is None:
                        missing += 1
                        if missing > allowed_missing:
                            break
                    else:
                        pos = nxt
                else:
                    return "words", start
        return None


def is_verbatim(quote: str, paper) -> bool:
    paper = paper if isinstance(paper, PaperText) else PaperText(paper)
    return paper.contains(quote)


_TABLE_REF = re.compile(r"\btables?\s*(\d+)", re.IGNORECASE)


def image_table_numbers(table_pages: dict) -> set:
    """Numbers of the tables on pages that were rasterized for the model
    (ParsedPaper.table_pages: page -> caption lines)."""
    return {m.group(1) for lines in table_pages.values() for line in lines for m in _TABLE_REF.finditer(line)}


def from_table_image(source: str, image_tables: set) -> bool:
    return any(m.group(1) in image_tables for m in _TABLE_REF.finditer(source or ""))


def table_page_numbers(table_pages: dict) -> dict:
    """{table number: page} from ParsedPaper.table_pages (page -> caption lines)."""
    out = {}
    for page, lines in sorted(table_pages.items(), key=lambda kv: int(kv[0])):
        for line in lines:
            for m in _TABLE_REF.finditer(line):
                out.setdefault(m.group(1), int(page))
    return out


def _table_page(source: str, table_pages: dict) -> Optional[int]:
    m = _TABLE_REF.search(source or "")
    return table_pages.get(m.group(1)) if m else None


def check_flag_quotes(flags: Iterable, paper_text: str, image_tables: set = frozenset(),
                      page_texts: Optional[List[str]] = None, table_pages: Optional[dict] = None) -> None:
    """Splits each flag's quote into verbatim parts (kept as `quote`), parts read from a
    table image (`table_image_quote`) and the rest (`unverified_quote`); notes the page."""
    paper = PaperText(paper_text, page_texts)
    for f in flags:
        if not f.quote:
            continue
        parts = list(dict.fromkeys(p.strip() for p in f.quote.split(QUOTE_SEPARATOR) if p.strip()))
        found = [p for p in parts if paper.contains(p)]
        f.page = next((pg for pg in (paper.page_of(p) for p in found) if pg), None) or \
            _table_page(f.source, table_pages or {})
        missing = [p for p in parts if p not in found]
        f.quote = QUOTE_SEPARATOR.join(found) or None
        if missing and from_table_image(f.source, image_tables):
            f.table_image_quote = QUOTE_SEPARATOR.join(missing)
        elif missing:
            f.unverified_quote = QUOTE_SEPARATOR.join(missing)


def check_row_quotes(rows, paper_text: str, image_tables: set = frozenset(),
                     page_texts: Optional[List[str]] = None, table_pages: Optional[dict] = None) -> int:
    """Marks every value's provenance quote: found in the paper's text, read from a
    table image, or not found (CellSource.quote_check), and the page it's on (CellSource.page:
    where the quote was found, else the page of the table its source names). Returns how
    many were not found."""
    paper = PaperText(paper_text, page_texts)
    seen: dict = {}
    missing = 0
    for row in rows:
        for src in row.provenance.values():
            if not src.quote:
                continue
            if src.quote not in seen:
                seen[src.quote] = paper.page_of(src.quote) if paper.paged else paper.contains(src.quote)
            page = seen[src.quote]
            src.page = (page if isinstance(page, int) and not isinstance(page, bool) else None) or \
                _table_page(src.source, table_pages or {})
            if page:
                src.quote_check = "in text"
            elif from_table_image(src.source, image_tables):
                src.quote_check = "table image"
            else:
                src.quote_check = "not found"
                missing += 1
    return missing
