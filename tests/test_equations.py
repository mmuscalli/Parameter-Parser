"""
Offline tests for finding the equations authors label ("(1)", "Eq. 2") and
the optional LaTeX step (with the API call replaced). Uses papers from the
dataset folder; each test skips if its paper isn't there. No API calls.

Run with: python tests/test_equations.py
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor.ingestion.equation_finder import find_equations
from parameter_extractor.schemas.equations import EquationLatex, EquationTranscription
from parameter_extractor.stages import equations as equations_stage

PAPERS = ROOT.parent / "Paper Files"


def _pdf(name):
    return next(iter(sorted(PAPERS.rglob(name))), None)


def _labels(name):
    pdf = _pdf(name)
    if pdf is None:
        print(f"SKIP: needs {name}"); return None
    with tempfile.TemporaryDirectory() as tmp:
        eqs = find_equations(str(pdf), Path(tmp))
        assert all(Path(e.image).is_file() for e in eqs)
        return [(e.label, e.page) for e in eqs]


def test_labelled_equations_are_found():
    expected = {
        "truman2024.pdf": [("1", 1), ("2", 2), ("3", 2)],       # two-column, stacked two-line reactions
        "Zamaraev1996.pdf": [("1", 4), ("2", 4)],               # single column, number at the far right
        "lemke2009.pdf": [("1", 1), ("2", 3), ("3", 3), ("4", 3)],   # math font without text ("(cid:5)")
        "kawamura2011.pdf": [("1", 6)],                         # a fraction
        # OCR'd scan: the number right behind the equation, not set apart (found by Mickey)
        "eder1994.pdf": [("1", 3)],
        "otake2011.pdf": [("3", 4), ("4", 4), ("1", 4), ("6", 9)],   # (1) also has its number close behind
    }
    for name, labels in expected.items():
        got = _labels(name)
        assert got is None or got == labels, (name, got)


def test_unlabelled_or_table_lookalikes_are_not():
    # kitadai2017: reactions in a table with reference numbers "(35)"; kim2019: none labelled
    for name in ("kitadai2017.pdf", "kim2019.pdf"):
        got = _labels(name)
        assert got is None or got == [], (name, got)


def test_crops_follow_the_crop_box():
    """Zamaraev1996's pages have a CropBox 57 pt in from the MediaBox: crops used to land
    on the wrong lines."""
    import pypdfium2 as pdfium
    from parameter_extractor.ingestion.pdf_parser import render_offset, to_render_box
    pdf = _pdf("Zamaraev1996.pdf")
    if pdf is None:
        print("SKIP: needs Zamaraev1996.pdf"); return
    doc = pdfium.PdfDocument(str(pdf))
    assert render_offset(doc[3]) == (57.0, 57.0)
    assert to_render_box([100, 200, 300, 220], (57.0, 57.0)) == [43, 143, 243, 163]
    doc.close()


def test_latex_cleanup_and_matching():
    clean = equations_stage.clean_latex
    assert clean("$X = 1$") == "X = 1"
    assert clean("\\[ a + b \\]") == "a + b"
    assert clean("S_{LGG} = Y/X \\qquad\\qquad (2)") == "S_{LGG} = Y/X"
    assert clean("K = k \\tag{3}") == "K = k"

    from parameter_extractor.schemas.equations import EquationCandidate
    eqs = [EquationCandidate(label="1", page=1, bbox=[0, 0, 1, 1], image="a.png"),
           EquationCandidate(label="2", page=1, bbox=[0, 0, 1, 1], image="b.png")]
    reply = EquationTranscription(equations=[EquationLatex(label="(2)", latex="b = 2 \\quad (2)"),
                                             EquationLatex(label="1", latex="a = 1", note="clear")])
    with patch.object(equations_stage, "call_structured", lambda *a, **k: reply):
        equations_stage.transcribe_equations(None, eqs)
    assert [(e.latex, e.latex_note) for e in eqs] == [("a = 1", "clear"), ("b = 2", "")]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All equation tests passed.")
