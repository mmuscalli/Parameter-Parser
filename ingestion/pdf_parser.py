"""
PDF -> clean structured input, done ONCE per paper and cached, so every
downstream stage (triage/structure/metadata/methodology/chemistry) reuses the
same parsed text instead of re-parsing the PDF on every stage call.

This intentionally does NOT attempt figure/scatter-plot digitization yet
(config.EXTRACT_FIGURE_DATA gates that) -- it inventories embedded raster
images so a future figure-reading stage has something to start from, but
extraction stages are only given the text layer and table text.

Table pages ARE rasterized, though (see rasterize_table_pages() below): the
eder1994 demo showed plain pdftotext output genuinely garbling which values
belong to which condition in a two-column table layout, so pages whose text
contains a "Table N" caption get rendered as images and handed to the
structure-planning and chemistry stages alongside the text, not instead of
it -- the model is told to trust the image over the OCR'd text when they
disagree (see prompts/structure_planner.md, prompts/chemistry.md).
"""
from __future__ import annotations
import json
import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

TABLE_CAPTION_RE = re.compile(r"(?m)^\s*Table\s+\d+\b")


@dataclass
class ParsedPaper:
    paper_id: str
    source_pdf: str
    page_count: int
    has_text_layer: bool
    text: str                      # full document, layout-preserved
    page_texts: List[str] = field(default_factory=list)
    embedded_image_count: int = 0
    table_pages: Dict[int, List[str]] = field(default_factory=dict)  # 1-indexed page -> captions found
    warnings: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout


def _page_count(pdf_path: Path) -> int:
    out = _run(["pdfinfo", str(pdf_path)])
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":")[1].strip())
    return 0


def _has_text_layer(pdf_path: Path) -> bool:
    out = _run(["pdffonts", str(pdf_path)])
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("-") and not l.startswith("name")]
    return len(lines) > 0


def _embedded_image_count(pdf_path: Path) -> int:
    out = _run(["pdfimages", "-list", str(pdf_path)])
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("-") and not l.startswith("page")]
    return len(lines)


def find_table_pages(page_texts: List[str]) -> Dict[int, List[str]]:
    """Cheap heuristic: a page whose text contains a line starting 'Table N'
    almost certainly has a table on it worth rasterizing. Catches the common
    case (caption on the same page as the table); doesn't try to handle a
    table that spans onto a following page with no caption of its own -- a
    human skimming runs/<paper>/page_images/ will notice that gap quickly."""
    found: Dict[int, List[str]] = {}
    for i, text in enumerate(page_texts, start=1):
        captions = TABLE_CAPTION_RE.findall(text)
        if captions:
            # capture a bit more context than just "Table 1" for the audit trail
            lines = [l.strip() for l in text.splitlines() if TABLE_CAPTION_RE.match(l)]
            found[i] = lines
    return found


def rasterize_pages(pdf_path: str, page_numbers: List[int], out_dir: Path, dpi: int = 150) -> Dict[int, Path]:
    """Renders the given 1-indexed pages to JPEG via pdftoppm and returns
    {page_number: image_path}. Only rasterizes the pages asked for -- NOT the
    whole document -- to keep this cheap for long papers."""
    out_dir.mkdir(parents=True, exist_ok=True)
    images: Dict[int, Path] = {}
    for page_num in page_numbers:
        prefix = out_dir / f"page"
        subprocess.run(
            ["pdftoppm", "-jpeg", "-r", str(dpi), "-f", str(page_num), "-l", str(page_num),
             str(pdf_path), str(prefix)],
            capture_output=True,
        )
        # pdftoppm zero-pads the page number based on total page count -- don't guess the name
        candidates = [p for p in out_dir.glob("page-*.jpg")
                      if int(p.stem.split("-")[-1]) == page_num]
        if candidates:
            images[page_num] = candidates[0]
    return images


def rasterize_table_pages(parsed: "ParsedPaper", out_dir: Path, dpi: int = 150) -> Dict[int, Path]:
    """Convenience wrapper: rasterizes exactly the pages parsed.table_pages
    flagged, nothing more. Returns {} if none were found (e.g. a paper that
    reports everything in running text with no tables)."""
    if not parsed.table_pages:
        return {}
    return rasterize_pages(parsed.source_pdf, sorted(parsed.table_pages.keys()), out_dir, dpi=dpi)


def parse_pdf(pdf_path: str, paper_id: Optional[str] = None) -> ParsedPaper:
    path = Path(pdf_path)
    paper_id = paper_id or path.stem
    warnings: List[str] = []

    page_count = _page_count(path)
    has_text = _has_text_layer(path)
    img_count = _embedded_image_count(path)

    if not has_text:
        warnings.append(
            "No embedded font/text layer detected -- this looks like a scanned PDF. "
            "pdftotext will return nothing; OCR (pytesseract) is needed before any "
            "text-based stage can run. Not implemented in this prototype."
        )
        return ParsedPaper(
            paper_id=paper_id, source_pdf=str(path), page_count=page_count,
            has_text_layer=False, text="", page_texts=[], embedded_image_count=img_count,
            warnings=warnings,
        )

    full_text = _run(["pdftotext", "-layout", str(path), "-"])

    page_texts = []
    for i in range(1, page_count + 1):
        page_texts.append(_run(["pdftotext", "-layout", "-f", str(i), "-l", str(i), str(path), "-"]))

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
        has_text_layer=True, text=full_text, page_texts=page_texts,
        embedded_image_count=img_count, table_pages=table_pages, warnings=warnings,
    )


if __name__ == "__main__":
    import sys
    pp = parse_pdf(sys.argv[1])
    print(f"paper_id={pp.paper_id} pages={pp.page_count} has_text={pp.has_text_layer} "
          f"images={pp.embedded_image_count} chars={len(pp.text)} table_pages={pp.table_pages}")
    for w in pp.warnings:
        print("WARNING:", w)
