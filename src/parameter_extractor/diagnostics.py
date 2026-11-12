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
        from parameter_extractor import packs
        found = packs.available()
        pack = packs.activate(packs.DEFAULT_PACK)
        # the pack's own prompts, its modules' (the chemistry step's comes with the Solution chemistry module), the app's
        prompts = sorted({p.stem for p in settings.PROMPTS_DIR.glob("*.md")}
                         | {p.stem for p in (pack.folder / "prompts").glob("*.md")}
                         | {p.stem for m in pack.modules for p in (m.folder / "prompts").glob("*.md")})
        # the methodology step became the pack's experimental_conditions stage (2026-10-22): its
        # prompt is the shared optional_stage one
        expected = {"chemistry", "figure_planner", "metadata", "optional_stage", "structure_planner",
                    "triage", "focused_search"}
        missing = expected - set(prompts)
        if missing:
            raise FileNotFoundError(f"missing prompts: {sorted(missing)} (app and {pack.id} pack)")
        return (f"{len(prompts)} prompts, {len(found)} domain pack(s) ({', '.join(sorted(found))}); "
                f"{pack.label}: {len(pack.template_columns)} columns, {len(pack.species_names)} species")
    checks.append(_run("Bundled prompts & vocabulary", resources))

    def template() -> str:
        """The template new research areas are made from (packs/_template/): bundled and valid."""
        from parameter_extractor import packs
        from parameter_extractor.stages.optional import load_specs
        pack = packs.template_pack()
        specs = load_specs(pack)
        if not pack.manifest.is_template or not specs or not (pack.folder / "README.md").is_file():
            raise FileNotFoundError("the template pack is incomplete")
        return f"{len(pack.template_columns)} example columns, {len(specs)} example stage(s), guide included"
    checks.append(_run("Template for new research areas", template))

    def local_model_support() -> str:
        """Local model servers (local_models.py): settings round trip and the request format, no network."""
        import json
        from parameter_extractor import local_models
        from parameter_extractor.schemas.structure_plan import StructurePlan
        s = local_models.LocalSettings.from_dict({"models": {"m": {"context": 65536, "vision": True}},
                                                  "profiles": {"P": {"*": "m"}}})
        assert s.model("m").context == 65536 and local_models.model_for(s.to_dict(), "P", "chemistry") == "m"
        schema = local_models.answer_schema(StructurePlan)
        json.dumps(schema)
        return f"Ollama and OpenAI-compatible servers; schema of {len(json.dumps(schema)) // 1000}K characters"
    checks.append(_run("Local model support", local_model_support))

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

    def text_recognition():
        """macOS Vision on a rendered number: table images without a text layer (ingestion/table_ocr.py)."""
        import sys as _sys
        import tempfile
        from PIL import Image, ImageDraw, ImageFont
        from parameter_extractor.ingestion import table_ocr
        if _sys.platform != "darwin":
            return "not on macOS -- tables without a text layer aren't highlighted"
        if not table_ocr.available():
            raise RuntimeError("the Vision framework bindings aren't bundled")
        im = Image.new("RGB", (360, 80), "white")
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
        except OSError:
            font = ImageFont.load_default()
        ImageDraw.Draw(im).text((10, 15), "7.25 mM", fill="black", font=font)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ocr.png"
            im.save(path)
            found = " ".join(w.text for w in table_ocr.words(path))
        if "7.25" not in found:
            raise RuntimeError(f"read {found!r} instead of '7.25 mM'")
        return "macOS Vision reads table images"
    checks.append(_run("Text recognition", text_recognition))

    def arxiv_and_focused() -> str:
        """arXiv full text and the focused search are bundled and work (no network needed)."""
        import ssl
        from parameter_extractor.focused_search import passages
        from parameter_extractor.gui import multi_runs, paper_list, parameter_panel, settings_dialog  # noqa: F401
        from parameter_extractor import paper_queue  # noqa: F401 (bundled?)
        from parameter_extractor.ingestion.arxiv_source import parse_identifier
        from parameter_extractor.ingestion.html_text import html_to_text
        text = html_to_text('<div class="ltx_document"><span class="ltx_tr"><span class="ltx_td">75 Cet</span>'
                            '<span class="ltx_td"><math alttext="0.10_{-0.05}^{+0.08}"></math></span></span></div>')
        if text.strip() != "75 Cet | $0.10_{-0.05}^{+0.08}$" or parse_identifier("10.1093/pasj/psad056") is None:
            raise RuntimeError(f"arXiv text conversion gave {text!r}")
        if passages("a\nEXOFASTv2 fit\nb", ["exofast"])[1] != 1:
            raise RuntimeError("focused-search screening failed")
        ssl.create_default_context()
        return "arXiv text conversion, identifiers, focused-search screening OK"
    checks.append(_run("arXiv text & focused search", arxiv_and_focused))

    if pdf is not None:
        def parse_and_render() -> str:
            from parameter_extractor.ingestion.figure_finder import find_figures
            from parameter_extractor.ingestion.pdf_parser import parse_pdf, rasterize_table_pages
            parsed = parse_pdf(str(pdf))
            with tempfile.TemporaryDirectory() as tmp:
                images = rasterize_table_pages(parsed, Path(tmp))
                sizes = [p.stat().st_size for paths in images.values() for p in paths]
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

    def developer_features() -> str:
        """The developer-only handoff mode must be absent from public builds (dev_features.py)."""
        import sys
        from parameter_extractor import dev_features
        try:
            import parameter_extractor.handoff  # noqa: F401
            has_module = True
        except ImportError:
            has_module = False
        if getattr(sys, "frozen", False):
            base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
            marker = (base / "parameter_extractor" / dev_features.MARKER).is_file()
            if not marker:
                if has_module:
                    raise RuntimeError("public build contains the developer handoff module")
                return "not included (public build)"
            return "included (developer build -- not for distribution)"
        return "available (developer switch on)" if dev_features.enabled() else "off (running from source)"
    checks.append(_run("Developer handoff", developer_features))

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
