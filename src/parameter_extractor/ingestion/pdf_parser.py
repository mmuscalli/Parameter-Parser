"""
PDF -> clean structured input, done ONCE per paper and cached, so every
downstream stage (structure/metadata/methodology/chemistry, optional triage) reuses the
same parsed text instead of re-parsing the PDF on every stage call.

Pure Python -- no external programs. Text comes from pdfplumber's
layout-preserving extraction (pdfminer.six underneath); page images are
rendered with pypdfium2. Both ship as pip wheels, so a packaged app needs
nothing else installed. (This replaced poppler's pdftotext/pdftoppm, which
users would have had to install themselves and which is GPL-licensed.
Checked on eder1994 before switching: same table pages and captions found,
~99.7% of words identical, and Table 2's rows came out better aligned.)

This intentionally does NOT attempt figure/scatter-plot digitization yet
(config.EXTRACT_FIGURE_DATA gates that) -- it inventories embedded raster
images so a future figure-reading stage has something to start from, but
extraction stages are only given the text layer and table text.

Table pages ARE rasterized, though (see rasterize_table_pages() below): the
eder1994 demo showed plain text extraction genuinely garbling which values
belong to which condition in a two-column table layout, so pages whose text
contains a "Table N" caption get rendered as images and handed to the
structure-planning and chemistry stages alongside the text, not instead of
it -- the model is told to trust the image over the extracted text when they
disagree (see prompts/structure_planner.md, prompts/chemistry.md).
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from parameter_extractor.errors import PdfNotReadableError

TABLE_CAPTION_RE = re.compile(r"(?m)^\s*Table\s+\d+\b")


@dataclass
class ParsedPaper:
    paper_id: str
    source_pdf: str
    page_count: int
    has_text_layer: bool
    text: str                      # full document, layout-preserved, pages separated by \f
    page_texts: List[str] = field(default_factory=list)
    embedded_image_count: int = 0
    table_pages: Dict[int, List[str]] = field(default_factory=dict)  # 1-indexed page -> captions found
    warnings: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _clean(page_text: str) -> str:
    """Layout extraction pads every line to the page width; strip that padding
    (it's only spaces, and it costs tokens on every stage call)."""
    return "\n".join(line.rstrip() for line in page_text.splitlines()).rstrip() + "\n"


def find_table_pages(page_texts: List[str]) -> Dict[int, List[str]]:
    """Cheap heuristic: a page whose text contains a line starting 'Table N'
    almost certainly has a table on it worth rasterizing. Catches the common
    case (caption on the same page as the table); doesn't try to handle a
    table that spans onto a following page with no caption of its own -- a
    human skimming the run's page_images/ will notice that gap quickly."""
    found: Dict[int, List[str]] = {}
    for i, text in enumerate(page_texts, start=1):
        captions = TABLE_CAPTION_RE.findall(text)
        if captions:
            # capture a bit more context than just "Table 1" for the audit trail
            lines = [l.strip() for l in text.splitlines() if TABLE_CAPTION_RE.match(l)]
            found[i] = lines
    return found


def rasterize_pages(pdf_path: str, page_numbers: List[int], out_dir: Path, dpi: int = 150) -> Dict[int, Path]:
    """Renders the given 1-indexed pages to JPEG and returns {page_number:
    image_path}. Only renders the pages asked for -- NOT the whole document
    -- to keep this cheap for long papers."""
    import pypdfium2 as pdfium

    out_dir.mkdir(parents=True, exist_ok=True)
    images: Dict[int, Path] = {}
    doc = pdfium.PdfDocument(pdf_path)
    try:
        for page_num in page_numbers:
            bitmap = doc[page_num - 1].render(scale=dpi / 72)
            path = out_dir / f"page-{page_num}.jpg"
            bitmap.to_pil().convert("RGB").save(path, "JPEG", quality=85)
            images[page_num] = path
    finally:
        doc.close()
    return images


def rasterize_table_pages(parsed: "ParsedPaper", out_dir: Path, dpi: int = 150) -> Dict[int, Path]:
    """Convenience wrapper: rasterizes exactly the pages parsed.table_pages
    flagged, nothing more. Returns {} if none were found (e.g. a paper that
    reports everything in running text with no tables)."""
    if not parsed.table_pages:
        return {}
    return rasterize_pages(parsed.source_pdf, sorted(parsed.table_pages.keys()), out_dir, dpi=dpi)


def parse_pdf(pdf_path: str, paper_id: Optional[str] = None) -> ParsedPaper:
    import pdfplumber

    path = Path(pdf_path)
    paper_id = paper_id or path.stem
    warnings: List[str] = []

    try:
        with pdfplumber.open(path) as doc:
            page_count = len(doc.pages)
            char_count = sum(len(p.chars) for p in doc.pages)
            img_count = sum(len(p.images) for p in doc.pages)
            page_texts = ([_clean(p.extract_text(layout=True) or "") for p in doc.pages]
                          if char_count else [])
    except Exception as e:  # pdfminer raises a zoo of types for corrupt/encrypted files
        raise PdfNotReadableError(f"Couldn't read '{path.name}' as a PDF ({type(e).__name__}: {e}).") from None

    if not char_count:
        warnings.append(
            "No text layer detected -- this looks like a scanned PDF. OCR is needed "
            "before any text-based stage can run. Not implemented in this prototype."
        )
        return ParsedPaper(
            paper_id=paper_id, source_pdf=str(path), page_count=page_count,
            has_text_layer=False, text="", page_texts=[], embedded_image_count=img_count,
            warnings=warnings,
        )

    table_pages = find_table_pages(page_texts)

    if img_count > 0:
        warnings.append(
            f"{img_count} embedded raster image(s) detected (figures/scatter plots likely "
            "among them). This pass does not extract figure data -- see "
            "config.EXTRACT_FIGURE_DATA."
        )
    if table_pages:
        warnings.append(
            f"Table caption(s) found on page(s) {sorted(table_pages.keys())} -- these will be "
            "rasterized and given to the structure-planning and chemistry stages as images "
            "alongside the text (see config.RASTERIZE_TABLE_PAGES)."
        )

    return ParsedPaper(
        paper_id=paper_id, source_pdf=str(path), page_count=page_count,
        has_text_layer=True, text="\f".join(page_texts), page_texts=page_texts,
        embedded_image_count=img_count, table_pages=table_pages, warnings=warnings,
    )


if __name__ == "__main__":
    import sys
    pp = parse_pdf(sys.argv[1])
    print(f"paper_id={pp.paper_id} pages={pp.page_count} has_text={pp.has_text_layer} "
          f"images={pp.embedded_image_count} chars={len(pp.text)} table_pages={pp.table_pages}")
    for w in pp.warnings:
        print("WARNING:", w)
