"""
The pipeline as a library: one call per paper, usable from the CLI (main.py)
or a GUI alike.

    result = run_pipeline(pdf_path, RunConfig(api_key=..., output_dir=...),
                          on_progress=callback, cancel_event=event)

or, with figure digitizing (what the GUI does):

    extraction = extract(pdf_path, config, on_figures=callback)   # steps 1-5
    plan = plan_figure(extraction, figure)            # optional suggestions, per figure
    result = finish(extraction, digitized_figures, skipped_figure_ids)   # step 6

`on_figures` is called (on the extracting thread) as soon as the PDF has been
read, with the partly filled Extraction, so a front end can let the user
review figures while steps 2-5 run. plan_figure() may be called from another
thread at that point: it waits until the experiment structure (step 2) exists.

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
from typing import Callable, Dict, List, Optional, Sequence

from parameter_extractor.config import settings
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import ApiKeyMissingError, PdfNotReadableError, PipelineError
from parameter_extractor.digitizing.annotate import save_digitized
from parameter_extractor.ingestion.figure_finder import find_figures
from parameter_extractor.ingestion.figure_rows import build_figure_rows
from parameter_extractor.ingestion.flatten_to_template import build_rows, write_csv
from parameter_extractor.ingestion.pdf_parser import ParsedPaper, parse_pdf, rasterize_table_pages
from parameter_extractor.run_context import ProgressCallback, RunContext, StageUsage
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.figures import DigitizedFigure, FigureCandidate, FigurePlan
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from parameter_extractor.schemas.row_schema import ExtractedRow
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.schemas.triage import TriageResult
from parameter_extractor.stages.chemistry_extractor import run_chemistry_extraction
from parameter_extractor.stages.figure_planner import run_figure_planner
from parameter_extractor.stages.metadata_extractor import run_metadata_extraction
from parameter_extractor.stages.methodology_extractor import run_methodology_extraction
from parameter_extractor.stages.structure_planner import run_structure_planner
from parameter_extractor.stages.triage import run_triage
from parameter_extractor.validation.plausibility_checks import Flag, check_extraction, check_row, flags_to_json


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
    figures: List[dict] = field(default_factory=list)   # [{figure_id, status, series, points}]

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


@dataclass
class Extraction:
    """Everything the automatic steps produced, before rows are assembled.
    Figures found in the PDF wait here for the user to digitize or skip them.

    Filled in progressively by extract(): `figures`/`parsed` first, then the
    stage outputs. `structure_ready` is set once `structure` exists -- or once
    the extraction has failed (`failure` says why), so nobody waits forever."""
    ctx: RunContext
    pdf_path: Path
    started: datetime
    parsed: ParsedPaper
    vocab: dict
    figures: List[FigureCandidate]
    structure: Optional[StructurePlan] = None
    metadata: Optional[PaperMetadata] = None
    methodology: Optional[Methodology] = None
    chemistry: Optional[ChemistryExtraction] = None
    structure_ready: threading.Event = field(default_factory=threading.Event)
    failure: Optional[str] = None

    @property
    def paper_id(self) -> str:
        return self.pdf_path.stem


def extract(
    pdf_path,
    config: RunConfig,
    on_progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    on_figures: Optional[Callable[["Extraction"], None]] = None,
) -> Extraction:
    """Steps 1-5: read the PDF (finding figures on the way) and run the automatic
    extraction stages. Call finish() afterwards to write the dataset."""
    started = datetime.now()
    pdf_path, ctx = _start(pdf_path, config, 6, on_progress, cancel_event)

    ctx.step("parse", "Reading the PDF")
    parsed = _parse(pdf_path, ctx.run_dir)
    table_images: List[Path] = []
    if config.rasterize_table_pages and parsed.table_pages:
        images_by_page = rasterize_table_pages(parsed, ctx.run_dir / "page_images",
                                               dpi=config.table_raster_dpi)
        table_images = [images_by_page[p] for p in sorted(images_by_page)]
    figures = find_figures(str(pdf_path), ctx.run_dir / "figures")
    (ctx.run_dir / "figures_found.json").write_text(
        json.dumps([f.model_dump() for f in figures], indent=2, ensure_ascii=False))
    vocab = json.loads((settings.SCHEMAS_DIR / "template_vocab.json").read_text())
    ex = Extraction(ctx=ctx, pdf_path=pdf_path, started=started, parsed=parsed, vocab=vocab,
                    figures=figures)
    if figures and on_figures:
        on_figures(ex)

    try:
        ctx.step("structure_planner", "Planning the experiment structure")
        ex.structure = run_structure_planner(ctx, parsed.text, table_images=table_images)
        ex.structure_ready.set()

        ctx.step("metadata", "Extracting bibliographic metadata")
        ex.metadata = run_metadata_extraction(ctx, parsed.page_texts[0])

        ctx.step("methodology", "Extracting experimental methodology")
        ex.methodology = run_methodology_extraction(ctx, parsed.text, ex.structure)

        ctx.step("chemistry", "Extracting solution chemistry")
        ex.chemistry = run_chemistry_extraction(ctx, parsed.text, ex.structure, vocab["species_names"],
                                                table_images=table_images)
    except BaseException as e:
        ex.failure = str(e) or type(e).__name__
        ex.structure_ready.set()     # release anyone waiting in plan_figure()
        raise
    return ex


def plan_figure(extraction: Extraction, figure: FigureCandidate) -> FigurePlan:
    """Suggestions for digitizing one figure (axis columns, series, conditions).
    One API call; safe to run on a background thread. If the experiment
    structure (step 2) isn't ready yet, waits for it."""
    extraction.structure_ready.wait()
    if extraction.structure is None:
        raise PipelineError("The paper's text extraction stopped before the experiment structure "
                            f"was ready ({extraction.failure or 'unknown reason'}), so no suggestions.")
    return run_figure_planner(extraction.ctx, figure, extraction.parsed.page_texts, extraction.structure,
                              extraction.vocab["species_names"], extraction.vocab["all_columns"])


def finish(
    extraction: Extraction,
    digitized: Sequence[DigitizedFigure] = (),
    skipped_figures: Sequence[str] = (),
) -> RunResult:
    """Step 6: rows from text/tables plus any digitized figures, checks, files."""
    ex, ctx, config = extraction, extraction.ctx, extraction.ctx.config
    ctx.step("assemble", "Assembling rows and running checks")
    rows = build_rows(ex.metadata, ex.structure, ex.methodology, ex.chemistry, config.paper_prefix,
                      drop_below=config.confidence_drop_below)
    thresholds = dict(flag_below=config.confidence_flag_below,
                      drop_below=config.confidence_drop_below)
    paper_flags = check_extraction(ex.methodology, ex.chemistry, **thresholds)

    figure_summary = []
    if digitized:
        fig_rows, problems = build_figure_rows(
            list(digitized), ex.metadata, ex.methodology, config.paper_prefix,
            first_set_index=len(ex.structure.experiment_sets) + 1,
            first_entry_number=len(rows) + 1)
        rows += fig_rows
        paper_flags += [Flag("figure_problem", p) for p in problems]
        for fig in digitized:
            save_digitized(fig, ctx.run_dir / "figures")
            if fig.plan and fig.plan.duplicates_tabulated_data:
                paper_flags.append(Flag(
                    "possible_duplicate",
                    f"{fig.figure_id} was digitized, but it may plot the same data as a table "
                    f"({fig.plan.duplicate_note or 'see the figure plan'}). Check for duplicate rows."))
            n_points = sum(len(s.points) for s in fig.series)
            figure_summary.append({"figure_id": fig.figure_id, "status": "digitized",
                                   "series": len([s for s in fig.series if s.points]),
                                   "points": n_points})
    done = {f["figure_id"] for f in figure_summary}
    for fig in ex.figures:
        if fig.figure_id not in done:
            status = "skipped" if fig.figure_id in skipped_figures else "not digitized"
            figure_summary.append({"figure_id": fig.figure_id, "status": status,
                                   "series": 0, "points": 0})

    row_flags = {r.full_id: f for r in rows if (f := check_row(r, **thresholds))}
    flags_path = None
    if paper_flags or row_flags:
        flags_path = ctx.run_dir / "plausibility_flags.json"
        flags_path.write_text(json.dumps(flags_to_json(paper_flags, row_flags),
                                         indent=2, ensure_ascii=False))

    csv_path = ctx.run_dir / f"{ex.paper_id}_extracted.csv"
    write_csv(rows, csv_path)

    gold_score = None
    if settings.USE_GOLD_STANDARD:  # OFF until the curated subset exists
        from parameter_extractor.validation.gold_standard_eval import load_gold_standard, score_paper
        gold_score = score_paper([r.model_dump() for r in rows], load_gold_standard())

    _write_summary(ctx, ex.pdf_path, ex.started, rows=len(rows),
                   paper_flags=len(paper_flags), rows_flagged=len(row_flags),
                   figures=sorted(figure_summary, key=lambda f: f["figure_id"]))

    return RunResult(paper_id=ex.paper_id, run_dir=ctx.run_dir, csv_path=csv_path, rows=rows,
                     paper_flags=paper_flags, row_flags=row_flags, usage=list(ctx.usage),
                     flags_path=flags_path, gold_standard_score=gold_score,
                     figures=sorted(figure_summary, key=lambda f: f["figure_id"]))


def run_pipeline(
    pdf_path,
    config: RunConfig,
    on_progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> RunResult:
    """Fully automatic: extract and finish, with no figures digitized (figures
    found are listed as "not digitized" in run_summary.json)."""
    return finish(extract(pdf_path, config, on_progress, cancel_event))


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
