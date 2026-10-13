"""
The pipeline as a library: one call per paper, usable from the CLI (main.py)
or a GUI alike.

    result = run_pipeline(pdf_path, RunConfig(api_key=..., output_dir=...),
                          on_progress=callback, cancel_event=event)

Chains the extraction stages for ONE pre-selected paper. Each stage's output
is validated (Pydantic) and written to the run's own folder before the next
stage runs, so a failure partway through still leaves the earlier stages' work
inspectable. Every run gets a fresh timestamped folder -- nothing is
overwritten.

Nothing here prints; progress goes through `on_progress`, failures are raised
as errors.PipelineError subclasses with user-readable messages.

Paper selection is the user's job -- triage is NOT run here. See
run_triage_only() below for optional screening.
"""
from __future__ import annotations
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import settings
from config.run_config import RunConfig
from errors import ApiKeyMissingError, PdfNotReadableError
from ingestion.flatten_to_template import build_rows, write_csv
from ingestion.pdf_parser import ParsedPaper, parse_pdf, rasterize_table_pages
from run_context import ProgressCallback, RunContext, StageUsage
from schemas.row_schema import ExtractedRow
from schemas.triage import TriageResult
from stages.chemistry_extractor import run_chemistry_extraction
from stages.metadata_extractor import run_metadata_extraction
from stages.methodology_extractor import run_methodology_extraction
from stages.structure_planner import run_structure_planner
from stages.triage import run_triage
from validation.plausibility_checks import Flag, check_extraction, check_row, flags_to_json


@dataclass
class RunResult:
    paper_id: str
    run_dir: Path
    csv_path: Path
    rows: List[ExtractedRow]
    paper_flags: List[Flag]
    row_flags: Dict[str, List[Flag]]
    usage: List[StageUsage]
    flags_path: Optional[Path] = None   # None when nothing was flagged
    gold_standard_score: Optional[dict] = None

    @property
    def input_tokens(self) -> int:
        return sum(u.input_tokens for u in self.usage)

    @property
    def output_tokens(self) -> int:
        return sum(u.output_tokens for u in self.usage)


def _new_run_dir(output_dir: Path, paper_id: str) -> Path:
    """<output_dir>/<paper_id>_<YYYYmmdd-HHMMSS>, never reusing an existing folder."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = output_dir / f"{paper_id}_{stamp}"
    n = 2
    while run_dir.exists():
        run_dir = output_dir / f"{paper_id}_{stamp}_{n}"
        n += 1
    run_dir.mkdir(parents=True)
    return run_dir


def _parse(pdf_path: Path, run_dir: Path) -> ParsedPaper:
    if not pdf_path.is_file():
        raise PdfNotReadableError(f"PDF not found: {pdf_path}")
    parsed = parse_pdf(str(pdf_path))
    (run_dir / "parsed_paper.json").write_text(parsed.to_json())
    if parsed.page_count == 0:
        raise PdfNotReadableError(f"Couldn't read '{pdf_path.name}' as a PDF.")
    if not parsed.has_text_layer:
        raise PdfNotReadableError(
            f"'{pdf_path.name}' has no text layer -- it looks like a scanned image. Text "
            f"recognition (OCR) isn't supported yet.")
    return parsed


def _start(pdf_path, config: RunConfig, total_steps: int,
           on_progress: Optional[ProgressCallback],
           cancel_event: Optional[threading.Event]) -> tuple[Path, RunContext]:
    if not config.api_key:  # fail fast, before creating a run folder or parsing anything
        raise ApiKeyMissingError()
    pdf_path = Path(pdf_path)
    run_dir = _new_run_dir(Path(config.output_dir), pdf_path.stem)
    ctx = RunContext(config=config, run_dir=run_dir, total_steps=total_steps,
                     on_progress=on_progress, cancel_event=cancel_event)
    return pdf_path, ctx


def _write_summary(ctx: RunContext, pdf_path: Path, started: datetime, **extra) -> None:
    summary = {
        "source_pdf": str(pdf_path),
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now().isoformat(timespec="seconds"),
        "config": ctx.config.to_public_dict(),
        "usage": [asdict(u) for u in ctx.usage],
        "input_tokens": sum(u.input_tokens for u in ctx.usage),
        "output_tokens": sum(u.output_tokens for u in ctx.usage),
        **extra,
    }
    (ctx.run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2))


def run_pipeline(
    pdf_path,
    config: RunConfig,
    on_progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> RunResult:
    started = datetime.now()
    pdf_path, ctx = _start(pdf_path, config, 6, on_progress, cancel_event)
    paper_id = pdf_path.stem

    ctx.step("parse", "Reading the PDF")
    parsed = _parse(pdf_path, ctx.run_dir)
    table_images: List[Path] = []
    if config.rasterize_table_pages and parsed.table_pages:
        images_by_page = rasterize_table_pages(parsed, ctx.run_dir / "page_images",
                                               dpi=config.table_raster_dpi)
        table_images = [images_by_page[p] for p in sorted(images_by_page)]

    ctx.step("structure_planner", "Planning the experiment structure")
    structure = run_structure_planner(ctx, parsed.text, table_images=table_images)

    ctx.step("metadata", "Extracting bibliographic metadata")
    metadata = run_metadata_extraction(ctx, parsed.page_texts[0])

    ctx.step("methodology", "Extracting experimental methodology")
    methodology = run_methodology_extraction(ctx, parsed.text, structure)

    ctx.step("chemistry", "Extracting solution chemistry")
    vocab = json.loads((settings.SCHEMAS_DIR / "template_vocab.json").read_text())
    chemistry = run_chemistry_extraction(ctx, parsed.text, structure, vocab["species_names"],
                                         table_images=table_images)

    ctx.step("assemble", "Assembling rows and running checks")
    rows = build_rows(metadata, structure, methodology, chemistry, config.paper_prefix,
                      drop_below=config.confidence_drop_below)
    thresholds = dict(flag_below=config.confidence_flag_below,
                      drop_below=config.confidence_drop_below)
    paper_flags = check_extraction(methodology, chemistry, **thresholds)
    row_flags = {r.full_id: f for r in rows if (f := check_row(r, **thresholds))}

    flags_path = None
    if paper_flags or row_flags:
        flags_path = ctx.run_dir / "plausibility_flags.json"
        flags_path.write_text(json.dumps(flags_to_json(paper_flags, row_flags),
                                         indent=2, ensure_ascii=False))

    csv_path = ctx.run_dir / f"{paper_id}_extracted.csv"
    write_csv(rows, csv_path)

    gold_score = None
    if settings.USE_GOLD_STANDARD:  # OFF until the curated subset exists
        from validation.gold_standard_eval import load_gold_standard, score_paper
        gold_score = score_paper([r.model_dump() for r in rows], load_gold_standard())

    _write_summary(ctx, pdf_path, started, rows=len(rows),
                   paper_flags=len(paper_flags), rows_flagged=len(row_flags))

    return RunResult(paper_id=paper_id, run_dir=ctx.run_dir, csv_path=csv_path, rows=rows,
                     paper_flags=paper_flags, row_flags=row_flags, usage=list(ctx.usage),
                     flags_path=flags_path, gold_standard_score=gold_score)


def run_triage_only(
    pdf_path,
    config: RunConfig,
    on_progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> TriageResult:
    """Optional screening: parse the PDF and run ONLY the triage stage, then
    stop. Meant for filtering a pile of candidate papers before extraction --
    the criteria in prompts/triage.md are one curator's own dataset scope, not
    a general requirement, so the extraction pipeline never gates on them."""
    started = datetime.now()
    pdf_path, ctx = _start(pdf_path, config, 2, on_progress, cancel_event)

    ctx.step("parse", "Reading the PDF")
    parsed = _parse(pdf_path, ctx.run_dir)

    ctx.step("triage", "Screening against the triage criteria")
    triage = run_triage(ctx, parsed.text)

    _write_summary(ctx, pdf_path, started, triage_recommendation=triage.recommendation)
    return triage
