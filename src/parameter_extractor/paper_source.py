"""
What a run reads: a local PDF, or a paper named by identifier (arXiv ID, DOI, ADS bibcode) and
read from arXiv. With RunConfig.prefer_arxiv a local PDF that names its arXiv ID or DOI is read
from arXiv's HTML full text instead (Mickey, 2026-10-24: an option, default off), falling back to
the PDF whenever arXiv has no HTML for it, can't be reached, or names a different paper.

The arXiv text has no pages, figures or equation crops (those need a PDF); its tables are exact.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from parameter_extractor.errors import PaperSourceError
from parameter_extractor.ingestion import arxiv_source as ax

PaperItem = Union[str, Path]     # a PDF path, or an identifier string


@dataclass
class ResolvedPaper:
    name: str                                   # run folder stem / paper_id
    pdf: Optional[Path] = None                  # the PDF to parse, when the text isn't from arXiv HTML
    text: str = ""                              # arXiv HTML full text
    record: Optional[ax.ArxivRecord] = None
    notes: List[str] = field(default_factory=list)   # what was tried, for the summary / a flag
    pdf_from_arxiv: bool = False                # `pdf` was downloaded from arXiv (no HTML for it)

    @property
    def read_arxiv(self) -> bool:
        """The values come from arXiv's version (its text, or its PDF) -> paper_arxiv_id."""
        return self.record is not None and (bool(self.text) or self.pdf_from_arxiv)

    @property
    def from_arxiv_text(self) -> bool:
        return bool(self.text)

    @property
    def label(self) -> str:
        if self.text and self.record:
            return f"{self.record.label} full text (arXiv HTML; a preprint)"
        if self.record and self.pdf:
            return f"{self.record.label} PDF (a preprint)"
        return f"PDF {self.pdf.name}" if self.pdf else self.name

    def summary(self) -> dict:
        return {"read_from": self.label, "arxiv": self.record.to_dict() if self.record else None,
                "pdf": str(self.pdf) if self.pdf else None, "notes": self.notes}


def is_identifier(item: PaperItem) -> bool:
    if isinstance(item, Path):
        return False
    text = str(item).strip()
    return not text.lower().endswith(".pdf") and ax.parse_identifier(text) is not None


def run_name(item: PaperItem) -> str:
    """Run-folder name: the PDF's stem, or the identifier made file-safe."""
    if not is_identifier(item):
        return Path(item).stem
    ident = ax.parse_identifier(str(item))
    prefix = {"arxiv": "arXiv_", "doi": "doi_", "bibcode": "ads_"}[ident.kind]
    return prefix + re.sub(r"[^A-Za-z0-9.\-]+", "_", ident.value).strip("_")


def _title_matches(title: str, first_pages: str) -> bool:
    """Is this arXiv record the paper in the PDF? Most of its title's words are on the first pages."""
    words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", title)]
    if not words:
        return False
    page = re.sub(r"\s+", " ", first_pages.lower())
    return sum(w in page for w in words) >= 0.8 * len(words)


def _first_pages_text(pdf: Path, pages: int = 2) -> str:
    """The first pages' text, plus the sideways characters on them: arXiv's own stamp
    ('arXiv:1811.01882v4 [astro-ph.EP] 20 Feb 2019') runs up the left margin."""
    import pdfplumber
    with pdfplumber.open(str(pdf)) as doc:
        parts = []
        for page in doc.pages[:pages]:
            parts.append(page.extract_text() or "")
            parts.append("".join(c["text"] for c in page.chars if not c.get("upright", True)))
        return "\n".join(parts)


def resolve_paper(item: PaperItem, run_dir: Path, prefer_arxiv: bool = False, ads_token: str = "",
                  note=lambda message: None, record: Optional[ax.ArxivRecord] = None,
                  cache: Optional[ax.LookupCache] = None) -> ResolvedPaper:
    """`note(message)` reports progress ('Looking for the paper on arXiv'). `record`: the identifier's
    arXiv record when it was already looked up (focused search: ax.resolve_many); `cache`: arXiv full
    texts read before aren't downloaded again."""
    name = run_name(item)
    if is_identifier(item):                    # named by identifier: arXiv is the only source
        if record is None:
            note(f"Looking up {ax.parse_identifier(str(item))} on arXiv")
            record = ax.resolve(item, ads_token)      # a PaperRef keeps its label's first author
        note(f"Downloading {record.label} from arXiv")
        text = ax.fetch_html_text(record, save_to=None if cache else run_dir / "arxiv.html", cache=cache)
        if text:
            return ResolvedPaper(name=name, text=text, record=record)
        pdf = ax.fetch_pdf(record, run_dir / f"{record.versioned_id.replace('/', '_')}.pdf")
        return ResolvedPaper(name=name, pdf=pdf, record=record, pdf_from_arxiv=True,
                             notes=[f"arXiv has no HTML full text for {record.label}: its PDF was read."])
    pdf = Path(item)
    if not pdf.is_file():
        from parameter_extractor.errors import PdfNotReadableError
        raise PdfNotReadableError(f"PDF not found: {pdf}")
    if not prefer_arxiv:
        return ResolvedPaper(name=name, pdf=pdf)
    try:
        first = _first_pages_text(pdf)
    except Exception:                          # an unreadable PDF fails properly in the PDF parser
        return ResolvedPaper(name=name, pdf=pdf)
    ident = ax.identifier_in_text(first)
    if ident is None:
        return ResolvedPaper(name=name, pdf=pdf, notes=["The PDF names no arXiv ID or DOI: the PDF was read."])
    try:
        note(f"Looking for {ident} on arXiv")
        record = ax.resolve(ident, ads_token)
        if not _title_matches(record.title, first):
            return ResolvedPaper(name=name, pdf=pdf, notes=[
                f"{ident} found on arXiv as '{record.title[:90]}', which doesn't look like this PDF: the PDF was read."])
        note(f"Downloading {record.label} from arXiv")
        text = ax.fetch_html_text(record, save_to=None if cache else run_dir / "arxiv.html", cache=cache)
    except PaperSourceError as e:
        return ResolvedPaper(name=name, pdf=pdf, notes=[f"arXiv text not used: {e} The PDF was read."])
    if not text:
        return ResolvedPaper(name=name, pdf=pdf, record=record,
                             notes=[f"arXiv has no HTML full text for {record.label}: the PDF was read."])
    return ResolvedPaper(name=name, text=text, record=record, notes=[f"{ident} printed in the PDF."])
