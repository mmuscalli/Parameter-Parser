"""
Scanned papers read by text recognition (Mickey, 2026-11-14: Flores1973, Inoue1993 and Rabinowitz1969 of the pack
study had no text layer and got no rows). ingestion/page_ocr.py: a page with (almost) no text over an image is read with
macOS Vision, its lines put back in reading order (two columns; pieces of one printed line joined; raised decimal
points). Image figures get their tick numbers the same way (figure_finder.recognized_ticks).

Run with: python tests/test_page_ocr.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def test_reading_order_columns_and_split_lines():
    from parameter_extractor.ingestion.page_ocr import clean, needs_ocr, reading_order
    lines = [("TITLE ACROSS THE PAGE", (0.1, 0.05, 0.9, 0.08)),
             ("left one", (0.08, 0.10, 0.45, 0.12)), ("right one", (0.55, 0.10, 0.92, 0.12)),
             ("left two ends here.", (0.08, 0.13, 0.30, 0.15)), ("And goes on", (0.31, 0.131, 0.45, 0.151)),
             ("right two", (0.55, 0.13, 0.92, 0.15)),
             ("Table 1. A caption across", (0.1, 0.20, 0.9, 0.22)),
             ("left after", (0.08, 0.25, 0.45, 0.27)), ("right after", (0.55, 0.25, 0.92, 0.27))]
    assert reading_order(lines) == ["TITLE ACROSS THE PAGE", "left one", "left two ends here. And goes on",
                                    "right one", "right two", "Table 1. A caption across", "left after",
                                    "right after"]
    assert clean("0•28 mm/s and 1·92") == "0.28 mm/s and 1.92" and clean("• a bullet") == "• a bullet"
    assert needs_ocr("", 1) and needs_ocr("NII-Electronic Library Service", 1)       # a watermark only
    assert not needs_ocr("", 0) and not needs_ocr("x" * 300, 1)


def _font(size):
    for name in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def test_a_scanned_two_column_pdf_is_read():
    from parameter_extractor.ingestion import page_ocr
    from parameter_extractor.ingestion.pdf_parser import parse_pdf
    if not page_ocr.available():
        assert sys.platform != "darwin", "macOS Vision should be available on macOS"
        return                                    # other systems: scans are refused as before
    page = Image.new("L", (1700, 2200), 255)
    d = ImageDraw.Draw(page)
    f, big = _font(34), _font(48)
    d.text((300, 120), "Peptide formation in hot water", font=big, fill=0)
    left = ["Glycine (0.1 M) was heated", "at 150 °C for 24 h in sealed", "glass tubes. The yield of"]
    right = ["diglycine was 0•28 %, and", "triglycine was not found", "in any of the samples."]
    for k, (a, b) in enumerate(zip(left, right)):
        d.text((120, 300 + 60 * k), a, font=f, fill=0)
        d.text((900, 300 + 60 * k), b, font=f, fill=0)
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "scan.pdf"
        page.save(pdf, "PDF", resolution=200)
        parsed = parse_pdf(str(pdf))
    assert parsed.has_text_layer and parsed.ocr_pages == [1], parsed.warnings
    text = " ".join(parsed.page_texts[0].split())
    assert text.index("Glycine") < text.index("glass tubes") < text.index("diglycine") < text.index("samples"), text
    assert "0.28" in text and "150" in text                     # the raised decimal point read as a point


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All page text recognition tests passed.")
