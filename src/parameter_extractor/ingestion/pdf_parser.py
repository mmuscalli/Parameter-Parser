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
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from parameter_extractor.errors import PdfNotReadableError

# A caption starting a line ("Table 1", "TABLE 1"), or mid-line in two-column layouts where
# the left column's text comes first (kim2019: "...incubated at 85-125C in the Table 1.
# Formation of Cytidine..."): "Table N." followed by a capitalised title. In-text
# references like "(Table 1, Fig. 2)" match neither.
# 'Table S1' too: supplementary information numbers its tables S1, S2, ... (pulletikurti2022_SI)
TABLE_CAPTION_RE = re.compile(r"(?m)^\s*(?:Table|TABLE)\s+S?\d+\b|\b(?:Table|TABLE)\s+S?\d+\.\s+[A-Z][a-z]")
# Word-gap threshold (points) for text extraction. pdfplumber's default (3) runs words
# together in tightly set papers (kim2019: letter gaps ~0.1 pt, word gaps ~2-3 pt), so a
# page that comes out with many implausibly long "words" is re-extracted with this.
TIGHT_X_TOLERANCE = 1.5
MERGED_WORD_LENGTH = 18
MERGED_WORDS_THRESHOLD = 0.02


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
    # pages printed sideways (landscape tables, teng2023): 1-indexed page -> degrees the page was
    # turned to read it (90/270); their text and images are taken upright
    page_rotations: Dict[int, int] = field(default_factory=dict)
    # False for a text without pages (arXiv HTML full text): no page numbers are given for quotes
    paged: bool = True
    read_from: str = ""            # what was read, e.g. "arXiv:2308.05343v1 full text (arXiv HTML; a preprint)"
    # supplementary information read with the paper (ingestion/supplements.py): its pages follow the
    # paper's -- [{"file": path, "offset": pages before it, "pages": n}]; shown as S1, S2, ...
    supplements: List[dict] = field(default_factory=list)

    def page_label(self, page) -> object:
        """A page as shown to the user: the paper's own number, or 'S<n>' for a supplement's page."""
        for s in self.supplements:
            if isinstance(page, int) and s["offset"] < page <= s["offset"] + s["pages"]:
                return f"S{page - s['offset']}"
        return page

    def add_supplement(self, si: "ParsedPaper", path) -> None:
        """Append a supplement's pages after the paper's (text marked, table pages renumbered)."""
        offset = self.page_count
        header = (f"=== SUPPLEMENTARY INFORMATION ({Path(path).name}), pages S1-S{si.page_count}. Everything "
                  f"from here on is the paper's supplement: cite its tables and figures as 'SI Table N' / "
                  f"'SI Fig. N' (or by their own S-numbers) so they aren't mistaken for the paper's. ===\n")
        pages = list(si.page_texts) or [si.text]
        pages[0] = header + pages[0]
        self.page_texts += pages
        self.text += "\f" + "\f".join(pages)
        for page, captions in si.table_pages.items():
            self.table_pages[offset + int(page)] = captions
        for page, degrees in si.page_rotations.items():
            self.page_rotations[offset + int(page)] = degrees
        self.page_count += si.page_count
        self.warnings += [f"{Path(path).name}: {w}" for w in si.warnings]
        self.supplements.append({"file": str(path), "offset": offset, "pages": si.page_count})

    @property
    def pages_for_lookup(self) -> Optional[List[str]]:
        """page_texts where page numbers mean something, else None."""
        return self.page_texts if self.paged else None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _clean(page_text: str) -> str:
    """Layout extraction pads every line to the page width; strip that padding
    (it's only spaces, and it costs tokens on every stage call)."""
    return "\n".join(line.rstrip() for line in page_text.splitlines()).rstrip() + "\n"


# Symbol / "Pi" fonts draw Greek letters at Latin code points, so their text comes out as
# Latin: kim2019's "5 µL" (AdvPi1 font) extracts as "5 mL" -- a 1000x unit error. Standard
# Symbol fonts get the full Adobe Symbol mapping; vendor "Pi" fonts vary, so only the
# near-universal m -> µ (micro) is applied to them.
_SYMBOL_GREEK = dict(zip("abcdefghiklmnopqrstuwxyzDFGLPQSWY", "αβχδεφγηικλμνοπθρστυωξψζΔΦΓΛΠΘΣΩΨ"))
_SYMBOL_GREEK["m"] = "µ"
# Symbol's other glyphs by code (Adobe Symbol encoding), for fonts that use the private-use copy
# U+F000 + code: kim2017's "5 µL" came out as "5 L" and "β-nucleoside" as "-nucleoside" (the PUA
# characters were dropped later), a µL read as litres
_SYMBOL_CODES = {0xB0: "°", 0xB1: "±", 0xB4: "×", 0xA3: "≤", 0xB3: "≥", 0xB8: "÷", 0xB9: "≠", 0xBB: "≈",
                 0xAE: "→", 0xAC: "←", 0x2D: "−", 0xD7: "·", 0xA5: "∞", 0xB6: "∂", 0xC5: "⊕"}


def _symbol_private_use(text: str):
    """What a Symbol-font character in the private-use area U+F020-U+F0FF shows, else None."""
    if len(text) != 1 or not 0xF020 <= ord(text) <= 0xF0FF:
        return None
    code = ord(text) - 0xF000
    char = chr(code)
    return _SYMBOL_GREEK.get(char) or _SYMBOL_CODES.get(code) or (char if 0x20 < code < 0x7F else None)


def _fix_symbol_font_chars(page) -> int:
    """Map Latin letters drawn in Symbol/Pi fonts to what they display. Returns the count."""
    n = 0
    for c in page.chars:
        font = (c.get("fontname") or "").lower()
        if _symbol_private_use(c["text"] or ""):
            mapped = _symbol_private_use(c["text"])
        elif "symbol" in font:
            mapped = _SYMBOL_GREEK.get(c["text"])
        elif "pi" in font.split("+")[-1][:8] and c["text"] == "m":     # e.g. MKMFED+AdvPi1, MathematicalPi
            mapped = "µ"
        else:
            mapped = None
        if mapped:
            c["text"] = mapped
            n += 1
    return n


def _merged_word_ratio(text: str) -> float:
    words = re.findall(r"[A-Za-z]{3,}", text)
    return sum(len(w) > MERGED_WORD_LENGTH for w in words) / max(len(words), 1)


def _page_text(page) -> tuple:
    """(layout text, True if the tighter word-gap setting was needed)."""
    _fix_symbol_font_chars(page)
    text = page.extract_text(layout=True) or ""
    if _merged_word_ratio(text) > MERGED_WORDS_THRESHOLD:
        tight = page.extract_text(layout=True, x_tolerance=TIGHT_X_TOLERANCE) or ""
        if _merged_word_ratio(tight) < _merged_word_ratio(text):
            return tight, True
    return text, False


def find_table_pages(page_texts: List[str]) -> Dict[int, List[str]]:
    """Cheap heuristic: a page whose text contains a line starting 'Table N'
    almost certainly has a table on it worth rasterizing. Catches the common
    case (caption on the same page as the table); doesn't try to handle a
    table that spans onto a following page with no caption of its own -- a
    human skimming the run's page_images/ will notice that gap quickly."""
    found: Dict[int, List[str]] = {}
    for i, text in enumerate(page_texts, start=1):
        # capture a bit more context than just "Table 1" for the audit trail; a contents page's
        # entries ("Table 3. ... ..... 86", pulletikurti2022_SI pp. 2-3) aren't tables
        if sum(bool(_CONTENTS_ENTRY.search(l)) for l in text.splitlines()) >= 3:
            continue                      # a contents page lists tables, it doesn't hold them
        lines = [l.strip() for l in text.splitlines() if TABLE_CAPTION_RE.search(l) and not _CONTENTS_ENTRY.search(l)]
        if lines:
            found[i] = lines
    return found


_CONTENTS_ENTRY = re.compile(r"(?:\.\s*){4,}\s*S?\d+\s*$")


def render_offset(pdfium_page) -> tuple:
    """pdfplumber measures positions on the full page (MediaBox); pypdfium2 renders only
    the CropBox. Subtract this (dx, dtop) from a pdfplumber position to get its place on
    the rendered image (Zamaraev1996: crop box 57 pt in from the left and top)."""
    mx0, _, _, my1 = pdfium_page.get_mediabox()
    cx0, _, _, cy1 = pdfium_page.get_cropbox()
    return cx0 - mx0, my1 - cy1


def to_render_box(box, offset) -> list:
    """A pdfplumber (x0, top, x1, bottom) in rendered-page points."""
    dx, dtop = offset
    return [box[0] - dx, box[1] - dtop, box[2] - dx, box[3] - dtop]


ROTATED_FRACTION = 0.5      # a page whose characters are mostly sideways is read turned


def _rotation(page) -> int:
    """0, or the turn (90 / 270) that makes a sideways page upright: most of its characters
    aren't upright, and their text matrix says which way they run."""
    chars = page.chars
    sideways = [c for c in chars if not c.get("upright", True)]
    if not chars or len(sideways) / len(chars) <= ROTATED_FRACTION:
        return 0
    upward = sum(1 for c in sideways if c["matrix"][1] > 0)       # b > 0: text runs bottom to top
    return 90 if upward >= len(sideways) / 2 else 270


def _turned_page_text(pdf_path: Path, index: int, angle: int) -> tuple:
    """_page_text of one page after turning it by `angle` (a copy, in memory)."""
    import io
    import pdfplumber
    import pypdfium2 as pdfium
    src = pdfium.PdfDocument(str(pdf_path))
    out = pdfium.PdfDocument.new()
    try:
        out.import_pages(src, [index])
        out[0].set_rotation((out[0].get_rotation() + angle) % 360)
        buf = io.BytesIO()
        out.save(buf)
    finally:
        out.close()
        src.close()
    buf.seek(0)
    with pdfplumber.open(buf) as doc:
        return _page_text(doc.pages[0])


def rasterize_pages(pdf_path: str, page_numbers: List[int], out_dir: Path, dpi: int = 220,
                    rotations: Optional[Dict[int, int]] = None) -> Dict[int, List[Path]]:
    """Renders the given 1-indexed pages to JPEG and returns {page_number:
    [image paths]}: the page cropped to its content, cut into pieces when it's
    larger than the API reads without scaling (ingestion/table_tiles.py) --
    page-9.jpg, or page-9-1of2.jpg, page-9-2of2.jpg. Only renders the pages
    asked for -- NOT the whole document -- to keep this cheap for long papers."""
    import pypdfium2 as pdfium
    from parameter_extractor.ingestion.table_tiles import tile

    out_dir.mkdir(parents=True, exist_ok=True)
    images: Dict[int, List[Path]] = {}
    doc = pdfium.PdfDocument(pdf_path)
    try:
        for page_num in page_numbers:
            bitmap = doc[page_num - 1].render(scale=dpi / 72, rotation=(rotations or {}).get(page_num, 0))
            pieces = tile(bitmap.to_pil().convert("RGB"))
            images[page_num] = []
            for k, piece in enumerate(pieces, start=1):
                name = f"page-{page_num}.jpg" if len(pieces) == 1 else f"page-{page_num}-{k}of{len(pieces)}.jpg"
                piece.save(out_dir / name, "JPEG", quality=85)
                images[page_num].append(out_dir / name)
    finally:
        doc.close()
    return images


def rasterize_table_pages(parsed: "ParsedPaper", out_dir: Path, dpi: int = 220) -> Dict[int, List[Path]]:
    """Convenience wrapper: rasterizes exactly the pages parsed.table_pages
    flagged, nothing more. Returns {} if none were found (e.g. a paper that
    reports everything in running text with no tables)."""
    if not parsed.table_pages:
        return {}
    own = parsed.supplements[0]["offset"] if parsed.supplements else parsed.page_count
    out = rasterize_pages(parsed.source_pdf, sorted(p for p in parsed.table_pages if p <= own), out_dir, dpi=dpi,
                          rotations=parsed.page_rotations)
    for s in parsed.supplements:          # a supplement's pages from its own PDF, in out_dir/SI (labelled SI)
        pages = [p - s["offset"] for p in sorted(parsed.table_pages) if s["offset"] < p <= s["offset"] + s["pages"]]
        if pages:
            si = rasterize_pages(s["file"], pages, out_dir / ("SI" if len(parsed.supplements) == 1 else
                                                               f"SI{parsed.supplements.index(s) + 1}"), dpi=dpi,
                                 rotations={p - s["offset"]: d for p, d in parsed.page_rotations.items()
                                            if s["offset"] < p <= s["offset"] + s["pages"]})
            out.update({s["offset"] + p: paths for p, paths in si.items()})
    return out


_shared_lock = threading.RLock()
_shared: Dict[str, object] = {}        # {"key": (path, mtime, size), "doc": pdfplumber.PDF}


@contextmanager
def open_plumber(pdf_path):
    """The PDF as one pdfplumber document shared by the parser, the figure finder and the
    equation finder, so each page's layout is parsed once (teng2023: 42 pages with heavy
    vector graphics, ~3.5 s each, were parsed three times -- 2.5 min). Only the most
    recent PDF is kept open; the lock keeps pdfminer's file reads to one thread."""
    import pdfplumber
    path = Path(pdf_path).resolve()
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _shared_lock:
        if _shared.get("key") != key:
            close_shared()
            _shared["doc"] = pdfplumber.open(path)
            _shared["key"] = key
        yield _shared["doc"]


def close_shared() -> None:
    with _shared_lock:
        doc = _shared.pop("doc", None)
        _shared.pop("key", None)
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def parse_pdf(pdf_path: str, paper_id: Optional[str] = None) -> ParsedPaper:

    path = Path(pdf_path)
    paper_id = paper_id or path.stem
    warnings: List[str] = []

    try:
        with open_plumber(path) as doc:
            page_count = len(doc.pages)
            char_count = sum(len(p.chars) for p in doc.pages)
            img_count = sum(len(p.images) for p in doc.pages)
            extracted, rotations = [], {}
            for i, p in enumerate(doc.pages if char_count else []):
                angle = _rotation(p)
                if angle:
                    rotations[i + 1] = angle
                    extracted.append(_turned_page_text(path, i, angle))
                else:
                    extracted.append(_page_text(p))
            page_texts = [_clean(t) for t, _ in extracted]
            tightened = [i for i, (_, tight) in enumerate(extracted, start=1) if tight]
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
    if rotations:
        warnings.append(f"Page(s) {sorted(rotations)} are printed sideways (landscape); read turned upright.")
    if tightened:
        warnings.append(f"Words ran together on page(s) {tightened} with the default spacing setting; "
                        f"re-extracted with a tighter word-gap threshold.")

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
        page_rotations=rotations,
    )


if __name__ == "__main__":
    import sys
    pp = parse_pdf(sys.argv[1])
    print(f"paper_id={pp.paper_id} pages={pp.page_count} has_text={pp.has_text_layer} "
          f"images={pp.embedded_image_count} chars={len(pp.text)} table_pages={pp.table_pages}")
    for w in pp.warnings:
        print("WARNING:", w)
