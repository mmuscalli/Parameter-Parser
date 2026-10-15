"""
Is a "quote" really the paper's words?

The model is asked for verbatim quotes, but sometimes writes its own
description instead (eder1994: "Table 1 conditions list the reaction
temperature, 81 C"). Shown as "Quote from the paper", that misleads. Each
flag's quote is checked against the paper's extracted text; parts not found
word for word are moved to `unverified_quote` and labelled as such.

The comparison ignores case, spacing, punctuation and symbols (°, µ, the
PDF's "(cid:N)" placeholders), so line breaks and hyphenation don't count as
differences. Two-column pages come out of the PDF with the columns' lines
interleaved (eder1994), so a quote's words are matched IN ORDER with gaps
allowed for the other column's text in between, and a few words may be
missing (OCR, a line split across columns). A value read from a table IMAGE can fail the check when the
table's text layer is garbled -- the label says that too.
"""
from __future__ import annotations
import re
from typing import Iterable

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
    def __init__(self, text: str):
        self.compact = compact(text)
        self.words = words(text)
        self.positions: dict = {}
        for i, w in enumerate(self.words):
            self.positions.setdefault(w, []).append(i)

    def _next(self, word: str, after: int, limit: int):
        for p in self.positions.get(word, ()):
            if after < p <= limit:
                return p
        return None

    def contains(self, quote: str) -> bool:
        q = compact(quote)
        if not q:
            return False
        if q in self.compact:
            return True
        qw = words(quote)
        if len(qw) <= SHORT_QUOTE_WORDS:
            return False
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
                    return True
        return False


def is_verbatim(quote: str, paper) -> bool:
    paper = paper if isinstance(paper, PaperText) else PaperText(paper)
    return paper.contains(quote)


def check_flag_quotes(flags: Iterable, paper_text: str) -> None:
    """Splits each flag's quote into verbatim parts (kept as `quote`) and the rest
    (`unverified_quote`)."""
    paper = PaperText(paper_text)
    for f in flags:
        if not f.quote:
            continue
        parts = list(dict.fromkeys(p.strip() for p in f.quote.split(QUOTE_SEPARATOR) if p.strip()))
        found = [p for p in parts if is_verbatim(p, paper)]
        missing = [p for p in parts if p not in found]
        f.quote = QUOTE_SEPARATOR.join(found) or None
        if missing:
            f.unverified_quote = QUOTE_SEPARATOR.join(missing)
