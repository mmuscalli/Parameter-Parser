"""Offline test of the --self-check diagnostics (no API key used, no cost).

Run with: python tests/test_diagnostics.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor.diagnostics import run_checks
from test_pipeline_offline import PDF


def test_self_check_passes_without_api_key():
    checks = run_checks(pdf=PDF if PDF.is_file() else None, api_key=None)
    failed = [c for c in checks if not c[1]]
    assert not failed, failed
    names = [c[0] for c in checks]
    assert "Bundled prompts & vocabulary" in names and "System keychain" in names
    assert any("skipped" in c[2] for c in checks if c[0].startswith("Anthropic API"))


def test_self_check_reports_a_bad_pdf():
    with __import__("tempfile").TemporaryDirectory() as tmp:
        bad = Path(tmp) / "broken.pdf"
        bad.write_text("not a pdf")
        checks = dict((n, ok) for n, ok, _ in run_checks(pdf=bad, api_key=None))
        assert checks["Parse & render broken.pdf"] is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All diagnostics tests passed.")
