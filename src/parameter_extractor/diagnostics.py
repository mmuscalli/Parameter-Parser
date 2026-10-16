"""
Self-check: confirms an installation (or a packaged app) has everything a run
needs, WITHOUT running an extraction or spending API credit.

    parameter-extract --self-check [--pdf paper.pdf]
    "Parameter Extractor.app/Contents/MacOS/Parameter Extractor" --self-check [--pdf paper.pdf]

Checks: the bundled prompts and vocabulary are present; the PDF libraries
load (and, with --pdf, actually parse and render that file and look for
figures); the system
keychain is reachable; and, if an API key is available (ANTHROPIC_API_KEY or
config/.env), that the Anthropic API accepts it and the configured models
exist -- via the free models endpoint, not a billed request.
"""
from __future__ import annotations
import json
import platform
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from parameter_extractor import __version__

Check = Tuple[str, bool, str]   # (name, passed, detail)


def _run(name: str, fn: Callable[[], str]) -> Check:
    try:
        return name, True, fn()
    except Exception as e:
        return name, False, f"{type(e).__name__}: {e}"


def run_checks(pdf: Optional[Path] = None, api_key: Optional[str] = None) -> List[Check]:
    from parameter_extractor.config import settings

    checks: List[Check] = []

    def resources() -> str:
        prompts = sorted(p.stem for p in settings.PROMPTS_DIR.glob("*.md"))
        expected = {"chemistry", "figure_planner", "metadata", "methodology",
                    "structure_planner", "triage"}
        missing = expected - set(prompts)
        if missing:
            raise FileNotFoundError(f"missing prompts: {sorted(missing)} in {settings.PROMPTS_DIR}")
        vocab = json.loads((settings.SCHEMAS_DIR / "template_vocab.json").read_text())
        return f"{len(prompts)} prompts, {len(vocab['species_names'])} vocabulary species"
    checks.append(_run("Bundled prompts & vocabulary", resources))

    def pdf_libs() -> str:
        import pdfplumber, pypdfium2
        return f"pdfplumber {pdfplumber.__version__}, pypdfium2 {pypdfium2.version.PYPDFIUM_INFO}"
    checks.append(_run("PDF libraries", pdf_libs))

    def automation() -> str:
        import numpy as np
        from parameter_extractor.digitizing.auto_points import match_scores
        scores = match_scores(np.eye(12) * 255, np.eye(5) * 255)     # a tiny diagonal finds itself
        if abs(scores.max() - 1.0) > 1e-6:
            raise RuntimeError("marker matching gave a wrong result")
        return f"numpy {np.__version__}, marker matching OK"
    checks.append(_run("Digitizer automation", automation))

    if pdf is not None:
        def parse_and_render() -> str:
            from parameter_extractor.ingestion.figure_finder import find_figures
            from parameter_extractor.ingestion.pdf_parser import parse_pdf, rasterize_table_pages
            parsed = parse_pdf(str(pdf))
            with tempfile.TemporaryDirectory() as tmp:
                images = rasterize_table_pages(parsed, Path(tmp))
                sizes = [p.stat().st_size for p in images.values()]
                figures = find_figures(str(pdf), Path(tmp) / "figures")
            return (f"{parsed.page_count} pages, {len(parsed.text):,} chars of text, table pages "
                    f"{sorted(parsed.table_pages)}, rendered {len(sizes)} image(s), figures found: "
                    f"{', '.join(f.figure_id for f in figures) or 'none'}")
        checks.append(_run(f"Parse & render {pdf.name}", parse_and_render))

    def keychain() -> str:
        import keyring
        backend = keyring.get_keyring()
        name = type(backend).__module__ + "." + type(backend).__name__
        if "fail" in name.lower() or "null" in name.lower():
            raise RuntimeError(f"no usable keychain backend ({name})")
        return name
    checks.append(_run("System keychain", keychain))

    if api_key:
        def api() -> str:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            models = sorted(set(settings.MODELS.values()))
            for m in models:
                client.models.retrieve(m)   # free; raises on bad key / unknown model / no TLS
            return f"key accepted; models available: {', '.join(models)}"
        checks.append(_run("Anthropic API (no charge)", api))
    else:
        checks.append(("Anthropic API (no charge)", True, "skipped -- no API key available"))

    return checks


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="--self-check")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--pdf", type=Path, help="Also parse and render this PDF")
    args, _ = parser.parse_known_args(argv)

    from parameter_extractor.config import settings
    frozen = getattr(sys, "frozen", False)
    print(f"Parameter Extractor {__version__} -- {'packaged app' if frozen else 'Python install'}, "
          f"Python {platform.python_version()}, {platform.platform()}")
    checks = run_checks(args.pdf, settings.ANTHROPIC_API_KEY or None)
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    failed = [c for c in checks if not c[1]]
    print("All checks passed." if not failed else f"{len(failed)} check(s) failed.")
    return 1 if failed else 0
