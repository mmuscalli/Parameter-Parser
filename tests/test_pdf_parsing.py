"""
Offline tests for PDF text extraction issues found on kim2019 (Astrobiology):
words run together by tight typesetting, a table caption mid-line in a
two-column layout, and a µ drawn in a symbol ("Pi") font that came out as
"m" ("5 µL" -> "5 mL", a 1000x unit error). Also checks the reference papers
still parse exactly as before. No API calls.

Run with: python tests/test_pdf_parsing.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor.ingestion.pdf_parser import _merged_word_ratio, find_table_pages, parse_pdf

PAPERS = ROOT.parent / "Paper Files" / "Paper Lists"
KIM = PAPERS / "Kim2019" / "kim2019.pdf"


def test_kim2019_text_tables_and_micro():
    if not KIM.is_file():
        print(f"SKIP: needs {KIM}"); return
    p = parse_pdf(str(KIM))
    assert _merged_word_ratio(p.text) < 0.01, _merged_word_ratio(p.text)
    assert "model for the origin of life" in re.sub(r"\s+", " ", p.text)
    assert list(p.table_pages) == [3]
    flat = re.sub(r"\s+", " ", p.text)
    assert "(5 µL, 15 mM)" in flat and "(8 µL,15 mM)" in flat and "(5 mL" not in flat
    assert any("ran together" in w for w in p.warnings)


def test_table_caption_patterns():
    pages = ["text text   Table 1. Formation of Cytidine 2'-Phosphate 5\nmore",   # mid-line caption
             "TABLE 2\nValues",                                                    # uppercase
             "as shown (Table 1, Fig. 2) and in Table 3 we",                       # references only
             "Table 4 Peptide formation"]                                          # line start
    assert sorted(find_table_pages(pages)) == [1, 2, 4]


def test_reference_papers_parse_unchanged():
    for folder, run in (("Initial Easy Papers/Truman2024/truman2024.pdf", "truman2024_auto"),
                        ("Initial Easy Papers/Eder1994/eder1994.pdf", "eder1994_auto")):
        pdf = PAPERS / folder
        if not pdf.is_file():
            print(f"SKIP: needs {pdf}"); continue
        saved = json.loads((ROOT / "runs" / run / "parsed_paper.json").read_text())
        p = parse_pdf(str(pdf))
        assert sorted(p.table_pages) == sorted(int(k) for k in saved["table_pages"])
        if run == "truman2024_auto":
            assert p.text == saved["text"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All PDF parsing tests passed.")
