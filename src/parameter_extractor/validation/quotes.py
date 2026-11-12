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
from typing import Iterable, List, Optional, Tuple

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


_TABLE_REF = re.compile(r"\btables?\s*([A-Z]?\d+|(?-i:[IVX]{1,6})\b)", re.IGNORECASE)   # 'Table IV' too


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


def species_named_in(name: str, quote: str) -> bool:
    """Does the quote name this species -- its name, or for amino acids and peptides their
    residues as full names, three-letter or one-letter codes (Table 3's 'FF, FA, AF')? A quote
    that doesn't (Chen2007: 'Entry 1 ... Yield (%) 2' for a product drawn as a structure)
    supports the value but not WHICH species it is."""
    from parameter_extractor.names import AMINO_ACIDS, _ONE_LETTER, _aa_code, cyclic_codes, peptide_codes
    if not quote:
        return False
    q = compact(quote)
    base = re.sub(r"\s*\(.*\)\s*$", "", name or "")             # 'X (sequence not determined)'
    if compact(base) and compact(base) in q:
        return True
    from parameter_extractor.names import match_species
    words = re.findall(r"[\w\[\]()+'’,-]+", quote)
    for size in (4, 3, 2, 1):                                       # a phrase naming it: 'potassium ferricyanide'
        for i in range(len(words) - size + 1):
            hit = match_species(" ".join(words[i:i + size]).strip(",()"), vocab=(base,))
            if hit and hit[0] == base:
                return True
    ion = re.match(r"(NH4|[A-Z][a-z]?)(?=[A-Z(\[]|\d*$)", base) if re.search(r"(Cl|Br|I|SO4|NO3)\d*$", base) else None
    if ion and re.search(rf"(?<![A-Za-z]){ion.group(1)}\s*(?:\d?\s*\+|\(?I+\)?(?![a-z]))", quote):
        return True                                               # 'Na+' / 'Ca2+' / 'CuII' for the chloride
    m = re.fullmatch(r"(\d+)peptide_([A-Za-z]{3})", base)
    codes = (peptide_codes(base) or cyclic_codes(base) or ([m.group(2)] * int(m.group(1)) if m else None)
             or ([c] if (c := _aa_code(base)) else None))
    if not codes:
        return False
    one = {v: k for k, v in _ONE_LETTER.items()}
    letters = "".join(one.get(c, "?") for c in codes)
    if len(codes) > 1 and re.search(rf"(?<![A-Za-z]){re.escape(letters)}(?![A-Za-z])", quote):
        return True                                               # 'FA' for Phe-Ala
    return all(c.lower() in quote.lower() or AMINO_ACIDS.get(c, "~").lower() in quote.lower() for c in set(codes))


def unnamed_species(solutes, page_texts: Optional[List[str]] = None) -> list:
    """Chemistry entries with a value whose species was inferred: the model said how (`identified_by`),
    or neither the quote nor the page it's on names the species (see species_named_in). A table row
    quoted as bare numbers ('97.3 2.77 0.064') is named by its column header, on the same page."""
    paper = PaperText("\n".join(page_texts), page_texts) if page_texts else None
    named_on_page: dict = {}
    out = []
    for s in solutes:
        if ((s.concentration_value is None and s.concentration_mM is None and not getattr(s, "detection", ""))
                or (getattr(s, "derived", False) and not getattr(s, "calculated_from", ""))):
            continue
        if getattr(s, "identified_by", ""):
            out.append(s)
            continue
        if species_named_in(s.name, s.quote):
            continue
        # a table cell's quote is just '<row> <value>'; its column header (in the source: '..., column
        # Recovered Nicotinamide (%)') names it -- kim2017's quote '1 93.1' couldn't be placed on a page
        header = re.search(r"\bcolumn\s+(.+)$", s.source or "")
        if header and species_named_in(s.name, header.group(1)):
            continue
        page = paper.page_of(s.quote) if paper and s.quote else None
        if page:
            key = (s.name, page)
            if key not in named_on_page:
                named_on_page[key] = species_named_in(s.name, page_texts[page - 1])
            if named_on_page[key]:
                continue
        out.append(s)
    return out


# ---- quotes that don't contain their value (2026-11-11, Mickey's eder1994 review: reagent_suppliers 'Fluka (...);
# Merck (...)' quoted as "All chemicals were used without further purification.") ------------------------------------
_STOP = set("the and with was were for from that this used each all other into than then only also been have has not "
            "are its their which these those under using without some such more most most very".split())
# values whose quote isn't meant to contain them: computed or composed by the app, paper details, method summaries
_NOT_QUOTED_ORIGINS = {"", "calculated", "pipeline", "metadata", "fitting models"}
_NOT_QUOTED_COLUMNS = {"solvent_name", "author_list", "data_location", "original_data_reference"}


def _distinctive(text: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z0-9+\-]{3,}", (text or "").lower()) if w not in _STOP}


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _span(line: str, wanted: set, room: int = 3, most: int = 30) -> str:
    tokens = line.split()
    hits = [k for k, t in enumerate(tokens) if _distinctive(t) & wanted]
    lo, hi = max(0, hits[0] - room), min(len(tokens), hits[-1] + room + 1)
    hi = min(hi, lo + most)
    return ("… " if lo else "") + " ".join(tokens[lo:hi]) + (" …" if hi < len(tokens) else "")


def _best_passage(page_texts: List[str], wanted: set) -> Tuple[str, Optional[int]]:
    """Where the paper names the value: up to five lines of one page, chosen for the value's RAREST words (a
    supplier's name counts more than 'grade'), each cut to the span of those words (+-3 words), in reading order.
    Two-column scans interleave their columns on a line, so a span can carry the other column's words too."""
    lines = [(page_no, line) for page_no, page in enumerate(page_texts, start=1) for line in page.splitlines()]
    counts: dict = {}
    for _, line in lines:
        for w in _distinctive(line) & wanted:
            counts[w] = counts.get(w, 0) + 1
    if not counts:
        return "", None
    weight = lambda words: sum(1.0 / counts[w] for w in words)        # noqa: E731
    first = max(range(len(lines)), key=lambda i: weight(_distinctive(lines[i][1]) & wanted))
    page_no = lines[first][0]
    chosen, covered = [first], _distinctive(lines[first][1]) & wanted
    while len(chosen) < 5:
        rest = [i for i, (pg, _) in enumerate(lines) if pg == page_no and i not in chosen]
        if not rest:
            break
        i = max(rest, key=lambda i: weight((_distinctive(lines[i][1]) & wanted) - covered))
        new = (_distinctive(lines[i][1]) & wanted) - covered
        if not new or weight(new) < 0.5:              # only common words left: no more lines
            break
        chosen.append(i)
        covered |= new
    if len(covered) < 2:
        return "", None
    text = " … ".join(_span(lines[i][1], wanted) for i in sorted(chosen))
    return re.sub(r"(?:\s*…\s*){2,}", " … ", text)[:400], page_no


def unrelated_quotes(observations: Iterable, page_texts: List[str]) -> list:
    """One `quote_unrelated` flag per column whose text values have a quote sharing none of their distinctive words
    (at least two, of four letters or more) -- the quote is in the paper but isn't where the value is said -- with the
    passage of the paper that does contain them. Numbers aren't checked (often converted from the printed unit);
    values the app composes or rewrites aren't either."""
    from parameter_extractor.validation.plausibility_checks import Flag
    by_column: dict = {}
    for o in observations:
        column, value, quote = o.column, o.value, o.quote or ""
        if (not quote or not isinstance(value, str) or _is_number(value) or o.origin in _NOT_QUOTED_ORIGINS
                or column in _NOT_QUOTED_COLUMNS or column.startswith(("paper_", "year_", "journal_"))
                or re.search(r"(method|desc|note|ref|refname)$", column)):
            continue
        wanted = _distinctive(value)
        if len(wanted) < 2 or wanted & _distinctive(quote):
            continue
        entry = by_column.setdefault(column, {"rows": [], "value": value, "quote": quote, "source": o.source,
                                              "wanted": wanted})
        entry["rows"].append(o.full_id)
    flags = []
    for column, e in by_column.items():
        passage, page = _best_passage(page_texts or [], e["wanted"])
        where = f" The paper says it here (p. {page}): “{passage}”" if passage and page else (
            f" The paper says it here: “{passage}”" if passage else " Its words weren't found in the paper either.")
        flags.append(Flag("quote_unrelated",
                          f"{column}: the quote given for this value doesn't contain it ({len(e['rows'])} row(s)) -- "
                          f"the quote is in the paper, but it isn't where the value is said.{where} Check the value.",
                          quote=e["quote"], source=e["source"] or None, page=page))
    return flags
