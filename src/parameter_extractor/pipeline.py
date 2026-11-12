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
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from parameter_extractor.calculators.peptide_totals import fill_total_peptide_yield
from parameter_extractor.calculators.amounts import VOLUME_COLUMN, apply_detection, derive_from_amounts, split_totals
from parameter_extractor.calculators.mixing import (
    derive_from_ratios, derive_mixture_concentrations, volumes_as_concentrations)
from parameter_extractor import packs
from parameter_extractor.paper_source import ResolvedPaper, resolve_paper, run_name
from parameter_extractor.calculators import exoplanets as exo
from parameter_extractor.validation import exoplanet_archive
from parameter_extractor.config import settings
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import (
    AnswersNeededError, ApiKeyMissingError, PdfNotReadableError, PipelineError, RunCancelledError)
from parameter_extractor.digitizing.annotate import save_digitized
from parameter_extractor.ingestion.duplicates import drop_recorded_software, drop_repeated_amounts, drop_repeated_values
from parameter_extractor.ingestion.equation_finder import find_equations
from parameter_extractor.ingestion.figure_finder import find_figures
from parameter_extractor.ingestion.table_finder import find_tables
from parameter_extractor.ingestion.figure_rows import build_figure_rows
from parameter_extractor.ingestion.flatten_to_template import build_rows, write_template_csv
from parameter_extractor.ingestion.normalize import normalize_chemistry
from parameter_extractor.ingestion.observations import (
    observations_to_records, rows_to_observations, write_observations_csv)
from parameter_extractor.ingestion.new_variables import (
    VariableDecision, VariableGroup, _rows_for, apply_decisions, collect_new_variables, group_new_variables, row_index,
    split_known, write_values)
from parameter_extractor.registry import VariableRegistry
from parameter_extractor.ingestion.pdf_parser import ParsedPaper, close_shared, parse_pdf, rasterize_table_pages
from parameter_extractor.ingestion.supplements import find_supplements
from parameter_extractor.run_context import ProgressCallback, RunContext, StageUsage, total_cost
from parameter_extractor.pricing import PRICES_CHECKED
from parameter_extractor.pubchem import PubChem
from parameter_extractor.validation.quotes import (check_flag_quotes, check_row_quotes, image_table_numbers,
                                                   table_page_numbers)
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.equations import EquationCandidate
from parameter_extractor.stages.equations import transcribe_equations
from parameter_extractor.schemas.figures import DigitizedFigure, FigureCandidate, FigurePlan
from parameter_extractor.schemas.methodology import Methodology, empty_methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from parameter_extractor.schemas.row_schema import CellSource, ExtractedRow
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.schemas.variables import NewVariable, TermSearch
from parameter_extractor.schemas.triage import TriageResult
from parameter_extractor.stages.chemistry_extractor import run_chemistry_extraction
from parameter_extractor.stages.figure_planner import run_figure_planner
from parameter_extractor.stages.metadata_extractor import run_metadata_extraction
from parameter_extractor.stages.methodology_extractor import run_methodology_extraction
from parameter_extractor.stages.structure_planner import run_structure_planner
from parameter_extractor.stages.term_search import run_term_search
from parameter_extractor.api_client import PaperContext
from parameter_extractor.stages.optional import (
    StageSpec, for_run, load_specs, run_optional_stage, triggered_specs)
from parameter_extractor.stages.fit_models import LABEL as FIT_MODELS_LABEL, run_fit_models
from parameter_extractor.schemas.fit_models import FitModels
from parameter_extractor.schemas.analysis import AnalysisResult
from parameter_extractor.stages.analysis import LABEL as ANALYSIS_LABEL, run_analysis
from parameter_extractor.calculators import exoplanet_fits
from parameter_extractor.calculators.water import normalize_water
from parameter_extractor.voting import MAX_PASSES, disagreement_flags, vote_chemistry, vote_stage
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
    observations_path: Optional[Path] = None   # long format: one value per line, with provenance
    gold_standard_score: Optional[dict] = None
    figures: List[dict] = field(default_factory=list)   # [{figure_id, status, series, points, image, ...}]
    equations: List[EquationCandidate] = field(default_factory=list)   # labelled equations found
    tables: List[dict] = field(default_factory=list)    # [{table_id, page, page_label, caption, image}]
    new_variables: List[NewVariable] = field(default_factory=list)   # left out of the CSV (not accepted)
    accepted_variables: List[dict] = field(default_factory=list)     # [{name, kind, column, values, how}]
    unfound_terms: List[str] = field(default_factory=list)           # searched for, not stated in the paper
    # set when the result was read back from its folder (run_folder.load_result, File > Open a results folder…)
    opened: bool = False
    pack: str = ""                                                   # the data pack the run used
    app_version: str = ""
    opened_notes: List[str] = field(default_factory=list)            # parts an older folder lacked

    @property
    def input_tokens(self) -> int:
        """All input tokens, cached or not (comparable across runs)."""
        return sum(u.prompt_tokens for u in self.usage)

    @property
    def cached_tokens(self) -> int:
        return sum(u.cache_read_tokens for u in self.usage)

    @property
    def output_tokens(self) -> int:
        return sum(u.output_tokens for u in self.usage)

    @property
    def cost_usd(self) -> Optional[float]:
        return total_cost(self.usage)


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


def _parse_text(source, run_dir: Path) -> ParsedPaper:
    """A paper read as text (arXiv HTML): no pages, figures or table images."""
    parsed = ParsedPaper(paper_id=source.name, source_pdf="", page_count=1, has_text_layer=True,
                         text=source.text, page_texts=[source.text], paged=False, read_from=source.label)
    (run_dir / "parsed_paper.json").write_text(parsed.to_json())
    return parsed


def _metadata_from_arxiv(record, paper_id: str) -> PaperMetadata:
    """Bibliographic metadata from the arXiv record (no API call): the journal from its journal
    reference ('A&A 623, A100 (2019)' -> 'A&A'), else 'arXiv preprint'."""
    journal = re.split(r"\s*[,(]|\s+\d", record.journal_ref or "")[0].strip() or "arXiv preprint"
    return PaperMetadata(paper_id=paper_id, paper_doi=record.doi or None,
                         doi_source="arxiv" if record.doi else "not_found", paper_title=record.title,
                         authors=list(record.authors), year_published=record.year or 0, journal_published=journal,
                         source=f"{record.label} (arXiv metadata)")


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
    if config.handoff_dir:
        from parameter_extractor import dev_features
        if not dev_features.enabled():
            raise PipelineError("Answering steps in Claude Code (handoff) is a developer-only option and isn't "
                                "available in this version of the app.")
    elif config.needs_api_key and not config.api_key and not config.rebuild:  # fail fast (a rebuild asks nothing), before creating a run folder or parsing anything
        raise ApiKeyMissingError()
    pdf_path = Path(pdf_path)
    # a PDF's stem; a paper named by identifier keeps its dots ('arXiv_2308.05343')
    run_dir = _new_run_dir(Path(config.output_dir),
                           pdf_path.stem if pdf_path.suffix.lower() == ".pdf" else pdf_path.name)
    ctx = RunContext(config=config, run_dir=run_dir, total_steps=total_steps,
                     on_progress=on_progress, cancel_event=cancel_event)
    if config.handoff_dir:                # one folder per paper, the same on every re-run
        from parameter_extractor.handoff import paper_dir
        ctx.handoff_paper_dir = paper_dir(config.handoff_dir,
                                          pdf_path.stem if pdf_path.suffix.lower() == ".pdf" else pdf_path.name)
    packs.activate(config.pack)           # template, vocabulary, prompts and stages of this domain
    from parameter_extractor import variable_categories   # the user's category edits (none without a registry)
    variable_categories.use_local(VariableRegistry(config.registry_path).local_categories
                                  if config.registry_path else {})
    return pdf_path, ctx


def _write_summary(ctx: RunContext, pdf_path: Path, started: datetime, **extra) -> None:
    from parameter_extractor import __version__
    summary = {
        "app_version": __version__,
        "source_pdf": str(pdf_path),
        "started": started.isoformat(timespec="seconds"),
        "finished": datetime.now().isoformat(timespec="seconds"),
        "config": ctx.config.to_public_dict(),
        "usage": [asdict(u) for u in ctx.usage],
        "input_tokens": sum(u.prompt_tokens for u in ctx.usage),      # cached ones included
        "cache_read_tokens": sum(u.cache_read_tokens for u in ctx.usage),
        "cache_write_tokens": sum(u.cache_write_tokens for u in ctx.usage),
        "output_tokens": sum(u.output_tokens for u in ctx.usage),
        "estimated_cost_usd": total_cost(ctx.usage),
        "prices_checked": PRICES_CHECKED,
        "provider": ctx.config.provider,
        **({"resumed_from": str(ctx.config.resume_from), "rebuilt": bool(ctx.config.rebuild),
            "reused_steps": [u.stage for u in ctx.usage if getattr(u, "reused", False)]}
           if getattr(ctx.config, "resume_from", None) else {}),
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
    term_search: Optional[TermSearch] = None
    fit_models: Optional[FitModels] = None          # exoplanet pack: how the values were obtained
    analysis: Optional[AnalysisResult] = None       # analytical techniques and instrument settings (2026-11-07)
    # optional stages (the domain pack's stages/*.json) that ran: name -> (spec, result)
    optional: Dict[str, tuple] = field(default_factory=dict)
    equations: List[EquationCandidate] = field(default_factory=list)
    source: Optional["ResolvedPaper"] = None        # what was read (paper_source)
    table_images: List[Path] = field(default_factory=list)   # rendered table pages sent with the paper
    tables: List[dict] = field(default_factory=list)         # table crops for the Tables tab (table_finder.py)
    grids: list = field(default_factory=list)                # tables the app read itself (table_grid.Grid)
    grid_problems: List[str] = field(default_factory=list)   # mapped cells the app couldn't read (flagged)
    ambient_notes: List[str] = field(default_factory=list)   # ambient conditions filled in (calculators/ambient.py)
    abbreviations: Dict[str, str] = field(default_factory=dict)  # species: full name -> the paper's abbreviation
    skipped_kind: str = ""      # a review / perspective / theory paper / abstract: the extraction steps were skipped
    # no figures will be digitized in this run (run_pipeline without automatic digitizing): a paper whose row plan is
    # empty then gets nothing from the extraction steps -- they're skipped (organics test set, 2026-11-09: $0.14 each
    # for takeuchi2020 / burchell2020, results only in figures)
    no_figure_rows: bool = False
    auto_figure_notes: List[str] = field(default_factory=list)   # figures not digitized automatically, and why
    terms: List[str] = field(default_factory=list)           # parameters to look for (focus terms)
    always_on: set = field(default_factory=set)              # optional stages that always run
    structure_ready: threading.Event = field(default_factory=threading.Event)
    failure: Optional[str] = None

    @property
    def paper_id(self) -> str:
        return self.source.name if self.source is not None else self.pdf_path.stem

    @property
    def wet_dry(self):
        return self.optional.get("wet_dry", (None, None))[1]

    @property
    def optional_list(self) -> list:
        return list(self.optional.values())


def extract(
    pdf_path,
    config: RunConfig,
    on_progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    on_figures: Optional[Callable[["Extraction"], None]] = None,
) -> Extraction:
    """Steps 1-5: read the PDF (finding figures on the way) and run the automatic
    extraction stages. Call finish() afterwards to write the dataset."""
    ex = read_paper(pdf_path, config, on_progress, cancel_event)
    if ex.figures and on_figures:
        on_figures(ex)
    ex.no_figure_rows = not ex.figures            # nothing to digitize either
    return extract_steps(ex)


def _extract_unattended(pdf_path, config, on_progress=None, cancel_event=None) -> "Extraction":
    """extract() for a run that digitizes no figures by hand: without automatic digitizing, a paper with no rows
    skips its extraction steps (Extraction.no_figure_rows)."""
    ex = read_paper(pdf_path, config, on_progress, cancel_event)
    ex.no_figure_rows = not ex.figures or not config.auto_digitize_figures
    return extract_steps(ex)


def read_paper(
    pdf_path,
    config: RunConfig,
    on_progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Extraction:
    """Step 1 only, no API calls: the run folder, what is read (paper_source), the PDF parsed, its table
    pages rendered, figures and labelled equations found. A paper queue reads every paper first, so
    their figures can be reviewed before the extraction steps (extract_steps) are done."""
    started = datetime.now()
    terms = [t.strip() for t in config.focus_terms if t.strip()]
    item = pdf_path                             # a PDF, or an arXiv ID / DOI / ADS bibcode (paper_source)
    pdf_path, ctx = _start(Path(run_name(item)), config, 0, on_progress, cancel_event)
    # the paper and settings, written first: a run that stops part-way can be resumed from them (resume.py, W1)
    from parameter_extractor import __version__
    from parameter_extractor.resume import CONFIG_FILE
    (ctx.run_dir / CONFIG_FILE).write_text(json.dumps(
        {"item": str(item), "app_version": __version__, "config": config.to_public_dict()},
        indent=2, ensure_ascii=False))
    pack = packs.current()
    # parse, structure, metadata and assembly, plus the pack's built-in stages and the term search
    ctx.total_steps = 4 + pack.uses("methodology") + _chemistry_on(pack, config) + bool(terms)
    # stages that always run are counted now (the progress bar doesn't jump); triggered ones once known
    always_on = {name for name, spec in load_specs().items()
                 if spec.trigger.always and config.optional_stages.get(name, "auto") != "off"}
    ctx.total_steps += len(always_on)

    ctx.step("parse", "Reading the paper")
    from parameter_extractor.ingestion.arxiv_source import LookupCache
    source = resolve_paper(item, ctx.run_dir, prefer_arxiv=config.prefer_arxiv, ads_token=config.ads_token,
                           note=lambda m: ctx.note("parse", m),
                           cache=LookupCache(config.arxiv_cache_dir) if config.arxiv_cache_dir else None)
    (ctx.run_dir / "source.json").write_text(json.dumps(source.summary(), indent=2, ensure_ascii=False))
    table_images: List[Path] = []
    figures, equations, tables = [], [], []
    if source.from_arxiv_text:                  # exact text tables; no pages, figures or equation crops
        parsed = _parse_text(source, ctx.run_dir)
    else:
        pdf_path = source.pdf
        parsed = _parse(pdf_path, ctx.run_dir)
        parsed.read_from = source.label
        if config.include_supplements:     # '<paper>_SI.pdf' next to it: read with the paper (supplements.py)
            for si_path in find_supplements(pdf_path):
                si = parse_pdf(str(si_path))
                if si.has_text_layer and si.page_count:
                    parsed.add_supplement(si, si_path)
                    ctx.note("parse", f"Supplementary information read with the paper: {si_path.name} "
                                      f"({si.page_count} pages, S1-S{si.page_count})")
            if parsed.supplements:
                (ctx.run_dir / "parsed_paper.json").write_text(parsed.to_json())
        if config.rasterize_table_pages and parsed.table_pages:
            images_by_page = rasterize_table_pages(parsed, ctx.run_dir / "page_images",
                                                   dpi=config.table_raster_dpi)
            table_images = [path for p in sorted(images_by_page) for path in images_by_page[p]]
        figures = find_figures(str(pdf_path), ctx.run_dir / "figures")
        own = parsed.supplements[0]["offset"] if parsed.supplements else parsed.page_count
        try:
            if config.save_images:
                tables += _find_tables(ctx, str(pdf_path), [p for p in sorted(parsed.table_pages) if p <= own],
                                       {p: d for p, d in parsed.page_rotations.items() if p <= own}, parsed)
            equations = find_equations(str(pdf_path), ctx.run_dir / "equations")     # local, no API call
            for s in parsed.supplements:          # the supplement's figures (Fig. S1, ...) and tables too
                offset, end = s["offset"], s["offset"] + s["pages"]
                figures += find_figures(s["file"], ctx.run_dir / "figures", supplement=True, page_offset=offset)
                if config.save_images:
                    tables += _find_tables(ctx, s["file"], [p - offset for p in sorted(parsed.table_pages)
                                                            if offset < p <= end],
                                           {p - offset: d for p, d in parsed.page_rotations.items() if offset < p <= end},
                                           parsed, offset)
        finally:
            close_shared()               # the page layouts were shared by the steps above
    (ctx.run_dir / "figures_found.json").write_text(
        json.dumps([f.model_dump() for f in figures], indent=2, ensure_ascii=False))
    _write_equations(ctx, equations)
    vocab = packs.current().vocab
    # the columns figure suggestions and the digitizer offer: every known one -- the template's, the pack's
    # standard columns (vessel_sealed, positive_control, ...) and the user's accepted ones
    vocab = dict(vocab, all_columns=list(dict.fromkeys(
        vocab["all_columns"] + VariableRegistry(config.registry_path).known_columns())))
    if tables:
        (ctx.run_dir / "tables.json").write_text(json.dumps(tables, indent=2, ensure_ascii=False))
    grids = _table_grids(ctx, pdf_path, parsed, tables, source) if config.table_grids else []
    ex = Extraction(ctx=ctx, pdf_path=pdf_path, started=started, parsed=parsed, vocab=vocab,
                    figures=figures, equations=equations, source=source, table_images=table_images, tables=tables,
                    terms=terms, always_on=always_on, grids=grids)
    return ex


def _table_grids(ctx: RunContext, pdf_path, parsed, tables: List[dict], source) -> list:
    """The tables whose cells the app can read reliably (table_grid.py): from the PDF (main paper and supplement;
    tables found again into a temporary folder when images aren't saved) or from an arXiv text's ' | ' rows.
    Saved as table_grids.json; a failure only means the model reads the tables as before."""
    from parameter_extractor.ingestion import table_grid
    try:
        if not parsed.paged:
            grids = table_grid.text_grids(parsed.text)
        else:
            found = tables
            if not found and parsed.table_pages:
                import tempfile
                own = parsed.supplements[0]["offset"] if parsed.supplements else parsed.page_count
                with tempfile.TemporaryDirectory() as tmp:
                    found = find_tables(str(pdf_path), [p for p in sorted(parsed.table_pages) if p <= own],
                                        Path(tmp), rotations={p: d for p, d in parsed.page_rotations.items() if p <= own})
            own_tables = [t for t in found if not str(t.get("page_label", "")).startswith("S")]
            grids = table_grid.pdf_grids(str(pdf_path), own_tables)
            for s in parsed.supplements:
                si = [t for t in found if str(t.get("page_label", "")).startswith("S")]
                grids += table_grid.pdf_grids(s["file"], si, start=len(grids) + 1)
    except Exception as e:                       # never stops a run
        ctx.note("parse", f"Tables not read by the app ({type(e).__name__}: {e}); the model reads them")
        return []
    if grids:
        (ctx.run_dir / "table_grids.json").write_text(json.dumps(
            [{"grid": g.grid_id, "table": g.table_id, "page": g.page, "rows": g.rows} for g in grids],
            indent=2, ensure_ascii=False))
        ctx.note("parse", f"Tables read by the app: {', '.join(g.table_id for g in grids)}")
    return grids


def _range_flags(rows: List[ExtractedRow]) -> List[Flag]:
    """One flag per column holding values printed as ranges ('low:high', '<name>_range_<unit>')."""
    by_column: Dict[str, List[str]] = {}
    for r in rows:
        for column, value in r.extra.items():
            if "_range" in column and isinstance(value, str) and ":" in value:
                by_column.setdefault(column, []).append(f"{r.full_id} = {value}")
    return [Flag("value_range", f"{column}: {len(cells)} value(s) printed as a range, written as 'low:high' "
                                f"in the column's unit ({'; '.join(cells[:4])}{' ...' if len(cells) > 4 else ''}).")
            for column, cells in by_column.items()]


def _tidy_figure_images(ex: "Extraction", summary: List[dict]) -> None:
    """Figure images were rendered for the review; keep those of digitized figures (and, with
    save_all_figure_images, the others) -- or none when save_images is off (Mickey, 2026-10-31). The
    digitized points (fig-N.digitized.json) are data and always kept."""
    config = ex.ctx.config
    digitized = {f["figure_id"] for f in summary if f["status"] == "digitized"}
    keep = {c.figure_id for c in ex.figures
            if config.save_images and (c.figure_id in digitized or config.save_all_figure_images)}
    kept_pages = {c.page_image for c in ex.figures if c.figure_id in keep}
    for c in ex.figures:
        if c.figure_id not in keep:
            Path(c.crop_image).unlink(missing_ok=True)
        if c.page_image not in kept_pages:
            Path(c.page_image).unlink(missing_ok=True)
    for f in summary:
        if f["figure_id"] not in keep:
            f["image"] = ""
            if f.get("annotated_image"):
                Path(f["annotated_image"]).unlink(missing_ok=True)
                f["annotated_image"] = ""
            f["image_note"] = ("images not kept (Options: save table and figure images)" if not config.save_images
                               else "image not kept: only digitized figures' images are saved (Options)")


def _find_tables(ctx, pdf: str, pages: List[int], rotations: dict, parsed, offset: int = 0) -> List[dict]:
    """Table crops for the Tables tab (ingestion/table_finder.py); a failure there never stops a run."""
    if not pages:
        return []
    try:
        return find_tables(pdf, pages, ctx.run_dir / "tables", supplement=bool(offset), page_offset=offset,
                           rotations=rotations, captions=parsed.table_pages)
    except Exception as e:                        # an estimate for reference only
        ctx.note("parse", f"Table images couldn't be saved ({type(e).__name__}: {e})")
        return []


def extract_steps(ex: "Extraction") -> "Extraction":
    """Steps 2-5 for a paper read_paper() has read: the API extraction steps, in parallel after the
    structure planner. Call finish() afterwards to write the dataset."""
    ctx, config, parsed, source = ex.ctx, ex.ctx.config, ex.parsed, ex.source
    table_images, terms, always_on, equations = ex.table_images, ex.terms, ex.always_on, ex.equations
    pack = packs.current()
    vocab = ex.vocab

    # the text sent to the model: long runs of layout spaces collapsed if the pack asks
    text = compact_text(parsed.text) if packs.current().manifest.compact_text else parsed.text
    if ex.grids:                     # the tables the app read, numbered: steps answer with a mapping
        from parameter_extractor.ingestion.table_grid import inline, render_all
        # a text source's tables are replaced in place; a PDF's grids follow the text (its table text is garbled)
        text = inline(text, ex.grids) if not parsed.paged else text + render_all(ex.grids)
    # every paper-reading step gets the same paper first -- cached once, read at a fraction of the
    # price by the steps after the structure planner (api_client, RunConfig.prompt_caching)
    tools = _paper_tools(pack, config, terms, has_figures=bool(ex.figures), paper_text=ex.parsed.text)
    ctx.paper = PaperContext(text=text, images=list(table_images), tools=tools,
                             instructions=_step_instructions(pack, config, tools, vocab),
                             long_lived=bool(config.batch_mode))
    convert_equations = bool(config.equations_to_latex and equations)
    if convert_equations:
        ctx.total_steps += 1            # optional (RunConfig.equations_to_latex), one small call
    pool = ThreadPoolExecutor(max_workers=max(1, getattr(config, "max_parallel_stages", 0)
                                              or settings.MAX_PARALLEL_STAGES), thread_name_prefix="stage")
    try:
        # metadata needs only page 1: it runs while the experiment structure is planned
        if source.record is not None:          # read from arXiv: its record has the metadata
            arxiv_metadata = _metadata_from_arxiv(source.record, ex.paper_id)
            running = {"metadata": pool.submit(lambda: arxiv_metadata)}
        else:
            running = {"metadata": pool.submit(run_metadata_extraction, ctx, parsed.page_texts[0])}
        if convert_equations:
            running["equations"] = pool.submit(_convert_equations, ctx, equations)
        ctx.step("structure_planner", "Planning the experiment structure")
        try:
            ex.structure = run_structure_planner(ctx, text, table_images=table_images)
        except AnswersNeededError as e:       # handoff: the parallel requests are written out too
            raise _all_requests(running, e) from None
        from parameter_extractor.schemas.structure_plan import plan_ids
        ctx.plan_ids = plan_ids(ex.structure)
        ex.structure_ready.set()
        if ex.structure.experiment_sets:
            from parameter_extractor.api_client import warm_cache
            warm_cache(ctx)                   # Balanced: the steps' model caches the paper once, then they read it

        # a review, perspective, theory paper or abstract with no rows of its own: nothing for the extraction steps
        # (Mickey, 2026-11-03: they cost a full run); a search for the user's own terms still runs
        kind = getattr(ex.structure, "paper_kind", "experimental")
        skip = not ex.structure.experiment_sets and (kind != "experimental" or ex.no_figure_rows)
        if skip:
            ex.skipped_kind = kind if kind != "experimental" else "figures-only paper"
            ctx.total_steps -= pack.uses("methodology") + _chemistry_on(pack, config) + len(always_on)
            ctx.note("skipped", f"The paper is a {kind}, with no experiments of its own: extraction steps skipped"
                     if kind != "experimental" else "No rows from tables or text, and no figures are digitized in "
                     "this run: extraction steps skipped")

        # everything else depends only on the structure: run it all at once
        pack = packs.current()
        if pack.uses("methodology") and not skip:
            running["methodology"] = pool.submit(run_methodology_extraction, ctx, text, ex.structure)
        passes = 1 if config.handoff_dir else max(1, min(MAX_PASSES, config.passes or 1))
        if passes > 1:
            ctx.note("passes", f"{passes} passes of each extraction step, values kept by vote")
        if _chemistry_on(pack, config) and not skip:
            running["chemistry"] = pool.submit(
                _voted, ctx, "chemistry", passes, run_chemistry_extraction,
                (ctx, text, ex.structure, vocab["species_names"]), {"table_images": table_images, **({"grids": ex.grids} if ex.grids else {})},
                vote_chemistry)
        if pack.uses("fit_models") and config.optional_stages.get("fit_models", "auto") != "off" and not skip:
            ctx.total_steps += 1
            running["fit_models"] = pool.submit(run_fit_models, ctx, text, ex.structure, table_images)
        if pack.uses("analysis") and config.optional_stages.get("analysis", "auto") != "off" and not skip:
            ctx.total_steps += 1
            running["analysis"] = pool.submit(run_analysis, ctx, text, ex.structure, table_images)
        if terms:
            columns = VariableRegistry(config.registry_path).known_columns()
            running["term_search"] = pool.submit(run_term_search, ctx, terms, text, ex.structure, columns)
        # optional stages whose trigger matches this paper (decided locally, no API call)
        specs = [] if skip else triggered_specs(ex.structure, parsed.text, config.optional_stages,
                                                config.suggest_new_variables, set(running),
                                                set(config.parameters_off), config.table_grids)
        for spec in specs:
            if spec.name not in always_on:
                ctx.total_steps += 1
            running[spec.name] = pool.submit(
                _voted, ctx, spec.name, passes, run_optional_stage, (ctx, spec, text, ex.structure, table_images),
                {"grids": ex.grids} if ex.grids else {}, lambda results, spec=spec: vote_stage(spec, results))
        results = _collect(ctx, running)
        # a domain pack without these stages gets empty stand-ins, so the rest works unchanged
        ex.metadata = results["metadata"]
        ex.methodology = results.get("methodology") or empty_methodology(ex.paper_id)
        ex.chemistry = results.get("chemistry") or ChemistryExtraction(paper_id=ex.paper_id, solutes=[])
        ex.term_search = results.get("term_search")
        ex.fit_models = results.get("fit_models")
        ex.analysis = results.get("analysis")
        ex.optional = {spec.name: (spec, results[spec.name]) for spec in specs}
        ex.grid_problems = list(getattr(ex.chemistry, "grid_problems", []) or []) + [
            p for spec in specs for p in (getattr(results[spec.name], "_grid_problems", None) or [])]
        if pack.uses("ambient_conditions"):     # 'ambient temperature' -> 25 °C, 'ambient pressure' -> 1 bar
            from parameter_extractor.calculators.ambient import apply_ambient
            ex.ambient_notes = [m for spec, result in ex.optional_list for m in apply_ambient(spec, result)]
        from parameter_extractor.stages.optional import reroute_other
        for spec, result in ex.optional_list:     # e.g. a rate law listed among `other` -> kinetic_model
            reroute_other(spec, result)
        _collect_other_parameters(ex)
        ctx.sort_usage(stage_order())
    except BaseException as e:
        pool.shutdown(wait=False, cancel_futures=True)
        ex.failure = str(e) or type(e).__name__
        ex.structure_ready.set()     # release anyone waiting in plan_figure()
        raise
    pool.shutdown(wait=False)
    return ex


def _source_flags(source) -> List[Flag]:
    """A paper read from arXiv is a preprint: say which version, and what it was published as
    (over-flag: the user should know which text the values come from). Fallback notes too."""
    if source is None:
        return []
    flags = []
    if source.record is not None:
        r = source.record
        published = (f" It was published as {r.journal_ref}" + (f" (DOI {r.doi})" if r.doi else "") + "."
                     if r.journal_ref else " arXiv lists no journal reference for it.")
        flags.append(Flag("paper_source", f"Read from {source.label}, version {r.version or '?'} of "
                                          f"{r.updated or r.published}. A preprint can differ from the published "
                                          f"paper.{published}"))
    flags += [Flag("paper_source", n) for n in source.notes if "the PDF was read" in n]
    return flags


def _collect_other_parameters(ex: "Extraction") -> None:
    """Open-ended stages' `other` conditions (no column of their own) join the methodology's
    other_parameters: the duplicate check and the review take them from there."""
    from parameter_extractor.schemas.methodology import OtherParameter
    for spec, result in ex.optional_list:
        for o in getattr(result, "other", []) or []:
            ex.methodology.other_parameters.append(OtherParameter(
                name=o.name, value=o.value, set_label=o.set_label or None, quote=o.quote, source=o.source,
                confidence=o.confidence, sample_label=getattr(o, "sample_label", "") or "",
                category=getattr(o, "category", "") or ""))


def _paper_wide_values(ex: "Extraction") -> dict:
    """{column: (value, CellSource)}: every value the stages give for the whole paper (set and sample '')
    -- controls, solid material, volumes ... -- for digitized figure rows (Riggi2023's rows all come from
    figures). Assumed values stay in the review; the methodology fields come via _paper_wide_methodology."""
    from parameter_extractor.stages.optional import stage_values
    out = {}
    for spec, result in ex.optional_list:
        for item in result.parameters:
            if item.set_label or getattr(item, "sample_label", "") or item.basis == "assumed" \
                    or getattr(item, "method", "") or getattr(item, "mode", ""):
                continue
            for column, v in stage_values(spec, item)[0].items():
                out.setdefault(column, (v.value, CellSource(
                    origin=spec.origin_label + (", derived" if v.basis == "derived" else "") + " (whole paper)",
                    quote=v.quote, confidence=v.confidence, source=v.source + (f" [{v.note}]" if v.note else ""))))
    return out


def _paper_wide_methodology(ex: "Extraction"):
    """The methodology as digitized figure rows see it (ingestion/figure_rows.py): the stages'
    conditions that are the same in every set, as paper-wide values."""
    from parameter_extractor.ingestion.flatten_to_template import _METHOD_COLUMNS
    from parameter_extractor.schemas.common import Extracted
    from parameter_extractor.stages.optional import optional_values
    from parameter_extractor.stages.optional import stage_values
    fields = {**_METHOD_COLUMNS, "initial_pH": "initial_pH"}
    view = ex.methodology.model_copy(deep=True)
    sets = [s.set_label for s in ex.structure.experiment_sets]
    for spec, result in ex.optional_list:
        # values the answer gives for the whole paper (also when no table gave the paper any sets)
        paper_wide = {}
        for item in result.parameters:
            if not item.set_label and not getattr(item, "sample_label", "") and item.basis != "assumed" \
                    and not getattr(item, "method", "") and not getattr(item, "mode", ""):
                paper_wide.update(stage_values(spec, item)[0])
        values = optional_values(spec, result, ex.structure)
        for column, field in fields.items():
            if column not in spec.columns or getattr(view, field).status == "found":
                continue
            v = paper_wide.get(column)
            if v is None:                          # or the same value in every set
                per_set = [values.get((label, "", column)) for label in sets]
                if per_set and all(x is not None for x in per_set) and len({str(x.value) for x in per_set}) == 1:
                    v = per_set[0]
            if v is not None:
                setattr(view, field, Extracted(value=v.value, status="found", quote=v.quote, source=v.source,
                                               confidence=v.confidence))
    return view


def _chemistry_on(pack, config: RunConfig) -> bool:
    """The chemistry step runs: the pack has it and it isn't switched off (every compound unticked in the
    Parameters panel, 2026-11-08)."""
    return pack.uses("chemistry") and config.optional_stages.get("chemistry", "auto") != "off"


def _step_instructions(pack, config: RunConfig, tools: dict, vocab: dict) -> dict:
    """Every paper-reading step's static instructions (its prompt, with the structure plan's place marked), sent
    in the cached system prompt BEFORE the paper (2026-11-07): identical for every paper of a pack and settings, so
    in a queue (or any run within the cache's lifetime) they and the tool list are paid once and read at 10% by
    the following papers. Steps whose prompt has other per-paper parts (the user's search terms) aren't listed and
    send their prompt as before; nothing is listed without prompt caching or in developer handoff."""
    if not config.prompt_caching or config.handoff_dir or not config.shared_instructions:
        return {}
    from parameter_extractor.api_client import PAPER_ABOVE, PLAN_MARK
    from parameter_extractor.stages import analysis as analysis_stage, fit_models as fit_stage
    from parameter_extractor.stages import chemistry_extractor, structure_planner as planner_stage
    running = {name for name in ("analysis", "fit_models", "chemistry") if name in tools}
    specs = load_specs()
    out = {}
    for stage in tools:
        if stage == "structure_planner":
            out[stage] = planner_stage.prompt_text(PAPER_ABOVE)
        elif stage == "chemistry":
            out[stage] = chemistry_extractor.prompt_text(PAPER_ABOVE, PLAN_MARK, vocab["species_names"],
                                                         config.scopes.get("chemistry"), grids=config.table_grids)
        elif stage == "analysis":
            out[stage] = analysis_stage.prompt_text(PAPER_ABOVE, PLAN_MARK, config.scopes.get("analysis"))
        elif stage == "fit_models":
            out[stage] = fit_stage.prompt_text(PAPER_ABOVE, PLAN_MARK)
        elif stage in specs:
            out[stage] = for_run(specs[stage], config.suggest_new_variables, running,
                                 set(config.parameters_off), config.table_grids).prompt_text(PAPER_ABOVE, PLAN_MARK)
    return out


def _paper_tools(pack, config: RunConfig, terms, has_figures: bool = False, paper_text: Optional[str] = None) -> dict:
    """Every paper-reading step this run may make, with its answer schema -- sent as the same tool
    list in every request (api_client), so all of them share the cached paper. Fixed before the
    structure is planned: optional stages are included unless switched off, triggered or not."""
    from parameter_extractor.schemas.variables import TermSearch
    tools = {"structure_planner": StructurePlan}
    if pack.uses("methodology"):
        tools["methodology"] = Methodology
    if _chemistry_on(pack, config):
        tools["chemistry"] = ChemistryExtraction
    if terms:
        tools["term_search"] = TermSearch
    if pack.uses("fit_models") and config.optional_stages.get("fit_models", "auto") != "off":
        tools["fit_models"] = FitModels
    if pack.uses("analysis") and config.optional_stages.get("analysis", "auto") != "off":
        tools["analysis"] = AnalysisResult
    left_out = set(config.parameters_off)
    for name, spec in load_specs().items():
        choice = config.optional_stages.get(name, "auto")
        # a keyword-triggered stage the paper can't trigger: no tool to send -- unless papers share the cached tool
        # list (shared instructions, paper queues): there one list for all papers saves more
        per_paper = paper_text is not None and not config.shared_instructions
        if choice == "off" or (choice == "auto" and per_paper and not spec.could_trigger(paper_text)):
            continue
        spec = for_run(spec, config.suggest_new_variables, left_out=left_out, grids=config.table_grids)
        if spec.parameters:
            tools[name] = spec.models()[1]
    if has_figures and config.figure_suggestions_on_paper:
        # figure suggestions read the paper the extraction steps cached (stages/figure_planner.py): a
        # request shares the cache only with the same tool list
        tools["figure_planner"] = FigurePlan
    return tools


# the order stages are listed in (summary, usage table) whatever order they finish in;
# optional stages (specs) go before chemistry
def stage_order() -> List[str]:
    return (["structure_planner", "metadata", "cache_warmup", "methodology", "term_search"] + list(load_specs())
            + ["fit_models", "analysis", "chemistry", "equations", "figure_planner"])


def stage_label(name: str) -> str:
    spec = load_specs().get(name)
    return spec.label if spec else _STAGE_LABELS.get(name, name)


_STAGE_LABELS = {"metadata": "Bibliographic metadata", "methodology": "Experimental methodology",
                 "chemistry": "Solution chemistry", "term_search": "Parameter search",
                 "equations": "Equations to LaTeX", "fit_models": FIT_MODELS_LABEL, "analysis": ANALYSIS_LABEL}


def _collect(ctx: RunContext, running: dict) -> dict:
    """Wait for the parallel stages, reporting each as it finishes. The first error (or a
    cancellation) stops the run; calls already in flight finish in the background."""
    by_future = {f: name for name, f in running.items()}
    pending = set(running)
    ctx.note("parallel", f"Extracting in parallel: {_names(pending)}")
    results = {}
    for future in as_completed(by_future):
        name = by_future[future]
        try:
            results[name] = future.result()      # re-raises the stage's error here
        except AnswersNeededError as e:          # handoff: every step of this round writes its request
            raise _all_requests(running, e) from None
        pending.discard(name)
        ctx.step(name, f"{stage_label(name)} done"
                       + (f" -- still running: {_names(pending)}" if pending else ""))
    return results


def _voted(ctx: RunContext, stage: str, passes: int, fn, args: tuple, kwargs: dict, vote):
    """One extraction step, run `passes` times at once on the same structure and decided by vote
    (voting.py). Each pass's answer is kept as <stage>.passN.output.json; the voted one is saved as
    <stage>.output.json, so a replay of the run gives the voted result. A pass that fails is left out
    (noted) as long as one succeeds."""
    if passes <= 1:
        return fn(*args, **kwargs)
    from parameter_extractor import api_client

    def one(i):
        api_client._streamed.pass_suffix = f".pass{i}"
        try:
            return fn(*args, **kwargs)
        finally:
            api_client._streamed.pass_suffix = ""
    with ThreadPoolExecutor(max_workers=passes, thread_name_prefix=f"{stage}-pass") as inner:
        futures = [inner.submit(one, i) for i in range(1, passes + 1)]
        results, failed = [], []
        for i, f in enumerate(futures, start=1):
            try:
                results.append(f.result())
            except RunCancelledError:
                raise
            except PipelineError as e:
                failed.append((i, e))
    if not results:
        raise failed[0][1]
    for i, e in failed:
        ctx.note(stage, f"{stage_label(stage)}: pass {i} failed ({e}) -- voting on the other passes")
    voted, data, notes = vote(results)
    run_dir = Path(ctx.run_dir)
    (run_dir / f"{stage}.output.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    first = run_dir / f"{stage}.pass1.audit.json"
    audit = json.loads(first.read_text()) if first.is_file() else {"stage": stage, "input_tokens": 0, "output_tokens": 0}
    audit.update(raw_response=data, voted_from=len(results), passes_failed=[i for i, _ in failed])
    (run_dir / f"{stage}.audit.json").write_text(json.dumps(audit, indent=2))
    with ctx._lock:
        ctx.vote_notes += notes
    return voted


def _all_requests(running: dict, first: AnswersNeededError) -> AnswersNeededError:
    """Developer handoff: wait for the other steps of the round and gather every request they wrote."""
    for future in running.values():
        try:
            future.result()
        except AnswersNeededError as e:
            first.merge(e)
        except Exception:                        # noqa: BLE001 -- the round stops anyway
            pass
    return first


def _names(stages) -> str:
    order = stage_order()
    return ", ".join(stage_label(n).lower() for n in sorted(stages, key=lambda n: order.index(n) if n in order else 99))


def _convert_equations(ctx: RunContext, equations: List[EquationCandidate]) -> None:
    try:
        transcribe_equations(ctx, equations)
    except PipelineError as e:  # not worth failing the whole extraction over
        for eq in equations:
            eq.latex_note = f"LaTeX conversion failed: {e}"
    _write_equations(ctx, equations)


def _pack_postprocess(pack, rows, ex: "Extraction", config: RunConfig) -> List[Flag]:
    """The pack's row-level calculators (exoplanets: names, masses, references); returns
    flags from the optional stages: unconvertible units, parameters given twice."""
    from parameter_extractor.stages.optional import optional_values
    problems: List[str] = []
    conflicts = []
    modal = []
    for spec, result in ex.optional_list:
        if (result.notes or "").startswith("[The model reported a failure twice"):
            modal.append(Flag("low_confidence", f"{spec.label}: the model reported that its extraction failed, "
                                                f"twice -- the values from this step may be incomplete. Running the "
                                                f"paper again usually helps."))
        values = optional_values(spec, result, ex.structure, problems, conflicts)
        for (label, sample, column), v in values.items():
            param = next((p.column for p in spec.parameters if column == spec.modal_flag_col(p.column)), None)
            if param:
                modes = [f"{values[(label, sample, spec.mode_col(param, n, 'desc'))].value} = "
                         f"{values[(label, sample, spec.mode_col(param, n))].value:g}"
                         for n in range(1, 10) if (label, sample, spec.mode_col(param, n)) in values]
                modal.append(Flag("multimodal", f"{sample or label}: {param} has a bi-/multimodal posterior -- "
                                                f"{'; '.join(modes)} (in {spec.mode_col(param, 1)}..., "
                                                f"{spec.modal_flag_col(param)} = 1)",
                                  quote=v.quote or None, source=v.source or None))
                continue
            param = next((p for p in spec.parameters if column == spec.alt_col(p.column, 1, "method")), None)
            if param:
                suffixes = spec.suffixes_for(param) if param.uncertainties else []
                shown = lambda col: _estimate(values, label, sample, col, suffixes)
                others = [f"{shown(spec.alt_col(param.column, n))} by "
                          f"{values[(label, sample, spec.alt_col(param.column, n, 'method'))].value}"
                          for n in range(1, 10) if (label, sample, spec.alt_col(param.column, n)) in values]
                adopted = (f"adopted {shown(param.column)}; " if (label, sample, param.column) in values
                           else "no adopted value; ")
                modal.append(Flag("other_estimates", f"{sample or label}: {param.column} is estimated more than one "
                                                     f"way -- {adopted}other estimates: {'; '.join(others)} (in "
                                                     f"{spec.alt_col(param.column, 1)}...)",
                                  quote=v.quote or None, source=v.source or None))
    if pack.uses("row_labels"):
        exo.row_labels(rows, ex.structure, config.paper_prefix)
    if pack.uses("exoplanet_masses"):
        exo.exoplanet_masses(rows)
    if pack.uses("reference_names"):
        exo.reference_names(rows, ex.metadata)
    heavy = exo.companion_masses(rows) if pack.uses("exoplanet_masses") else []
    fit_flags: List[Flag] = []
    if pack.uses("fit_models") and ex.fit_models is not None:
        fit_flags = [Flag("fit_model", m) for m in
                     exoplanet_fits.apply_fit_models(rows, ex.fit_models, ex.structure, config.paper_prefix)]
        fit_flags += exoplanet_fits.model_flags(rows, ex.fit_models)
    return [Flag("unit_conversion", p) for p in problems] + [Flag("out_of_range", m) for m in heavy] + fit_flags + modal + \
           [Flag("conflicting_values", c.message, quote=c.quote or None, source=c.source or None) for c in conflicts]


def _archive_check(rows, ex: "Extraction", ctx: RunContext) -> dict:
    from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
    reference = exo.reference_name(list(ex.metadata.authors or []), ex.metadata.year_published)
    records = [row_to_template_dict(r) for r in rows]
    return {**exoplanet_archive.check(records, reference, ctx.run_dir), "reference": reference}


def archive_flags(archive: dict) -> List[Flag]:
    """One flag per planet: how its values compare with the archive's parameter set for this paper."""
    if archive.get("error"):
        return [Flag("lookup_unavailable", f"Archive check skipped: {archive['error']}.")]
    flags = []
    for e in archive["report"]:
        if e["status"] != "compared":
            refs = ", ".join(e.get("archive_references", [])) or "none"
            flags.append(Flag("archive_check", f"{e['pl_name']}"
                                               + (f" [{e['solution']}]" if e.get("solution") else "")
                                               + f": {e['status']} ('{archive['reference']}'); the "
                                               f"archive has: {refs}."))
            continue
        differs = "; ".join(f"{d['column']} {d['extracted']:.6g} vs {d['archive']:.6g}"
                            if isinstance(d["extracted"], (int, float)) and isinstance(d["archive"], (int, float))
                            else f"{d['column']} '{d['extracted']}' vs '{d['archive']}'" for d in e["differs"])
        name = (e["pl_name"] + (f" [{e['solution']}]" if e.get("solution") else "")
                + (f" (the archive's {e['archive_name']}"
                   + (", matched by orbital period" if e.get("matched_by") else "") + ")"
                   if e.get("archive_name") else ""))
        row = packs.row_word()
        other = (f" -- the archive's parameter set is this planet's [{e['archive_solution']}] {row}, so "
                 f"differences here are expected" if e.get("archive_solution") else "")
        flags.append(Flag(
            "archive_check" if e["differs"] else "archive_match",
            f"{name}: {len(e['matches'])} of {len(e['matches']) + len(e['differs'])} values match the NASA "
            f"Exoplanet Archive's '{archive['reference']}' parameter set{other}"
            + (f"; differ: {differs}" if differs else "")
            + (f"; minor differences, the paper's values kept: "
               + "; ".join(f"{m['column']} {m['extracted']} vs {m['archive']} ({m['why']})" for m in e["minor"])
               if e.get("minor") else "")
            + (f"; matched another recorded value: "
               + "; ".join(f"{c} ({how})" for c, how in e["matched_mode"].items())
               if e.get("matched_mode") else "")
            + "".join(f"; {len(cols)} more of the archive's values ({', '.join(cols[:6])}"
                      f"{'...' if len(cols) > 6 else ''}) are in this planet's [{solution}] {row}"
                      for solution, cols in e.get("in_other_solution", {}).items())
            + (f"; the archive's {row if e.get('archive_solution') else 'parameter set'} also has "
               f"{len(e['not_extracted'])} value(s) {f'this {row} does not give' if e.get('archive_solution') else 'not extracted'} "
               f"({', '.join(e['not_extracted'][:8])}{'...' if len(e['not_extracted']) > 8 else ''})"
               if e["not_extracted"] else "") + "."))
    return flags


def _estimate(values: dict, label: str, sample: str, column: str, suffixes=("err1", "err2", "lim")) -> str:
    """'22 +3/-3', '> 13' -- a value with its uncertainties or limit, for flag text. `suffixes`: the
    stage's (upper, lower[, limit]) column suffixes."""
    get = lambda suffix: None if suffix is None else getattr(values.get((label, sample, column + suffix)), "value", None)
    suffixes = list(suffixes) + [None] * (3 - len(suffixes))
    value, limit = get(""), get(suffixes[2])
    if limit in (1, -1):
        return f"{'<' if limit == 1 else '>'} {value:g}"
    plus, minus = get(suffixes[0]), get(suffixes[1])
    return f"{value:g}" + (f" +{plus:g}/{minus:g}" if plus is not None and minus is not None else "")


def _shown(v) -> str:
    """A review value for a message: a number, or a text value (assumed 'Transit')."""
    return f"{v.value:g}" if v.value is not None else f"'{v.value_text or ''}'"


def _where(v) -> str:
    if getattr(v, "sample_label", None):
        return f"'{v.sample_label}'"
    return f"set '{v.set_label}'" if v.set_label else "every row (paper-wide)"


def _not_a_compound_flags(chemistry) -> List[Flag]:
    """Species names that look like a class, an enzyme, a dye or a kit rather than one compound ('RNA oligomers',
    'phosphate buffer', 'DNase I') -- the same test Find compounds and Suggest additions use
    (compound_setup.is_compound_name). Flagged, never dropped (over-flag, don't lose data)."""
    from parameter_extractor.compound_setup import is_compound_name
    odd = sorted({s.name for s in chemistry.solutes if s.name and not is_compound_name(s.name)})
    if not odd:
        return []
    return [Flag("not_a_compound", "Recorded as compounds, but the names look like a class of molecules, an enzyme, a "
                                   "dye or a reagent mixture rather than one compound: " + ", ".join(odd[:12])
                 + (" ..." if len(odd) > 12 else "") + ". Check them (and their columns) in the review.")]


def _identity_flags(chemistry, page_texts=None) -> List[Flag]:
    """Values whose quote doesn't name the species (Chen2007: products drawn as structures in a
    table, a general procedure's 'the carboxylic acid (3 mmol)'): the number is supported, WHICH
    species it is was inferred. One flag per species, with how the model identified it."""
    from parameter_extractor.validation.quotes import unnamed_species
    groups: Dict[str, list] = {}
    for s in unnamed_species(chemistry.solutes, page_texts):
        groups.setdefault(s.variable, []).append(s)
    flags = []
    for name, entries in groups.items():
        where = "; ".join(dict.fromkeys(f"{e.sample_label or e.set_label or 'every set'}"
                                        + (f" ({e.identified_by})" if e.identified_by else "") for e in entries))
        flags.append(Flag("identity_not_quoted",
                          f"{name}: the quote{'s' if len(entries) > 1 else ''} for {len(entries)} value(s) "
                          f"{'don' if len(entries) > 1 else 'doesn'}'t name it -- the value is in the paper, but "
                          f"which species it belongs to was inferred: {where[:400]}. Check the paper.",
                          quote=entries[0].quote or None, source=entries[0].source or None))
    return flags


NO_RESULTS_MESSAGE = (
    "No results data were found to attach the extracted conditions and chemistry to: rows are only made "
    "for results in the paper's tables (read automatically) and figures (through the digitizer). If the "
    "results are in figures, run the paper again and digitize them in the figure review. What was "
    "extracted is kept in the run folder (experimental_conditions / chemistry .output.json files).")


_SAMPLING_CONDITIONS = ("sampled_temperature_C", "sampled_pressure_bar", "sampled_pH")   # conditions, not results


_PRODUCT_COLUMN = re.compile(r"^(?:total_(?:sampled|calculated)_|(?:sampled|calculated)_.+_(?:aq|gas|s)(?:_avg|_range)*_)")
_STARTING_COLUMN = re.compile(r"^(?:initial|stock)_.+_(?:aq|gas|s)(?:_avg|_range)*_")


def starting_composition_flags(rows) -> List[Flag]:
    """Rows reporting products (or yields) with no starting compound at all (Mickey, 2026-11-12: Cleaves2008's Fig. 2
    rows had peptide yields but no glycine concentration, though the series labels said '0.1 M'). One flag per data
    location, naming the rows and their product columns; nothing is filled in."""
    from parameter_extractor.ingestion.data_location import COLUMN as DATA_LOCATION
    groups: Dict[str, list] = {}
    for r in rows:
        values = {**{c: v for c, v in r.species_mM.items()}, **r.extra}
        products = [c for c, v in values.items() if v not in (None, "") and _PRODUCT_COLUMN.match(c)
                    and not c.endswith(("_err_plus", "_err_minus"))]
        if products and not any(v not in (None, "") and _STARTING_COLUMN.match(c) for c, v in values.items()):
            where = str(r.extra.get(DATA_LOCATION, "") or "this paper").replace(". ", " ")
            groups.setdefault(where, []).append((r.full_id, products))
    flags = []
    for where, items in groups.items():
        columns = list(dict.fromkeys(c for _fid, cs in items for c in cs))
        ids = [fid for fid, _cs in items]
        flags.append(Flag("no_starting_composition",
                          f"{where}: {len(ids)} row(s) report products or yields ({', '.join(columns[:5])}"
                          f"{', ...' if len(columns) > 5 else ''}) but no starting composition -- no starting "
                          f"compound concentration. The caption, a series label (e.g. '0.1 M') or the Methods may give "
                          f"it; enter it if so. Rows: {', '.join(ids)}."))
    return flags


def _has_results(rows, new_vars) -> bool:
    """Any measured result: a row with a sampled value (template column, or one waiting in the
    review as a 'sampled ...' variable)."""
    if not rows:
        return False
    from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
    for row in rows:
        if any(k.startswith(("sampled_", "total_sampled")) and v not in (None, "")
               for k, v in row_to_template_dict(row).items() if k not in _SAMPLING_CONDITIONS):
            return True
    return any(getattr(v, "role", None) == "sampled" for v in new_vars)


def compact_text(text: str) -> str:
    """Runs of 3+ spaces -> 3, of 3+ blank lines -> 2: ~20% fewer tokens for papers with wide
    tables (teng2023), columns still visibly apart."""
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{3,}", "   ", text))


def _write_equations(ctx: RunContext, equations: List[EquationCandidate]) -> None:
    if equations:
        (ctx.run_dir / "equations.json").write_text(
            json.dumps([e.model_dump() for e in equations], indent=2, ensure_ascii=False))


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


# review(groups, unfound_terms, registry) -> decisions: shows the user the variables
# that have no column yet and returns what to do with each (GUI: the "Review new
# variables" window). Without one (CLI), nothing new is added to the CSV.
ReviewCallback = Callable[[List[VariableGroup], List[str], VariableRegistry], List[VariableDecision]]


def _reaction_volumes(ex) -> dict:
    """{(set_label, sample_label): (mL, where from)} from the stages' solvent_volume_mL values
    (assumed values aren't among them -- they wait in the review)."""
    from parameter_extractor.stages.optional import optional_values
    out = {}
    for spec, result in ex.optional_list:
        for (label, sample, column), v in optional_values(spec, result, ex.structure).items():
            if column == VOLUME_COLUMN and isinstance(v.value, (int, float)) and v.value > 0:
                out[(label, sample)] = (float(v.value), v.source or spec.origin_label)
    return out


MIXING_FLAG_KINDS = {"derived": "derived_value", "not_derived": "not_calculated", "mismatch": "conflicting_values",
                     "repaired": "unit_conversion"}


def grouped_mixing_flags(notes) -> List[Flag]:
    """Mixture concentrations calculated from stocks: ONE flag per species (kim2017: 4 species x 8 sets
    were 32 flags), the first set's calculation in full and every set's value; other notes one each."""
    flags, by_species = [], {}
    for n in notes:
        if n.kind in ("derived", "repaired") and n.species:
            by_species.setdefault((n.kind, n.species), []).append(n)
        else:
            flags.append(Flag(MIXING_FLAG_KINDS[n.kind], n.message, quote=n.quote or None, source=n.source or None))
    for (kind, species), ns in by_species.items():
        if len(ns) == 1:
            message = ns[0].message
        elif kind == "derived" and species.startswith("total "):        # one stated total split by a ratio
            message = (f"{species[6:]}: split by the pipeline in {len(ns)} places -- " + "; ".join(n.short for n in ns)[:900]
                       + ". Each share is total x part / sum of parts.")
        elif kind == "derived":
            message = (f"{species}: mixture concentration calculated by the pipeline in {len(ns)} places -- "
                       + "; ".join(n.short for n in ns) + f". How (first): {ns[0].message}")
        else:
            message = (f"{species}: {len(ns)} values given as volumes, not concentrations, were recorded as the "
                       f"volumes of its stock solution added -- " + "; ".join(n.short for n in ns) + ".")
        flags.append(Flag(MIXING_FLAG_KINDS[kind], message, quote=ns[0].quote or None, source=ns[0].source or None))
    return flags


def finish(
    extraction: Extraction,
    digitized: Sequence[DigitizedFigure] = (),
    skipped_figures: Sequence[str] = (),
    review: Optional[ReviewCallback] = None,
) -> RunResult:
    """Step 6: rows from text/tables plus any digitized figures, new-variable
    review, checks, files."""
    ex, ctx, config = extraction, extraction.ctx, extraction.ctx.config
    ctx.step("assemble", "Assembling rows and running checks")
    registry = VariableRegistry(config.registry_path)
    pubchem = PubChem(config.pubchem_cache_path) if config.use_pubchem else None
    # names -> vocabulary (rules, then PubChem identity); mM re-checked
    pack = packs.current()
    # one name per species within the paper: the abbreviation it defines ("ImpA"), in the chemistry and on
    # digitized series alike
    from parameter_extractor.names import abbreviations_in
    ex.abbreviations = abbreviations_in(ex.parsed.text, [s.name for s in ex.chemistry.solutes]
                                        + [sp.name for f in digitized for s in f.series for sp in s.initial_species])
    normalization = (normalize_chemistry(ex.chemistry, pubchem=pubchem, registry=registry,
                                         abbreviations=ex.abbreviations)
                     if pack.uses("normalize_species") else [])
    if pubchem:
        pubchem.save()
    from parameter_extractor.scopes import filter_compounds
    left_out = filter_compounds(ex.chemistry, ex.ctx.config.scopes.get("chemistry"))
    scope_flags = [Flag("scope", f"This run extracted only the {len(ex.ctx.config.scopes['chemistry'])} compounds "
                                 f"chosen in the Parameters panel; {len(left_out)} other species returned were left "
                                 f"out: {', '.join(left_out[:15])}" + (" ..." if len(left_out) > 15 else ""))] \
        if left_out else []
    set_labels = [s.set_label for s in ex.structure.experiment_sets]
    # stock -> mixture concentrations, then molar ratios -> missing concentrations; marked derived
    mixing = []
    if pack.uses("amounts"):              # 'not detected' -> 0; amounts / reaction volume -> mM (derived)
        mixing += apply_detection(ex.chemistry)
        mixing += split_totals(ex.chemistry, set_labels)
        mixing += derive_from_amounts(ex.chemistry, _reaction_volumes(ex),
                                      {s.set_label: [x.sample_label for x in s.samples]
                                       for s in ex.structure.experiment_sets})
    if pack.uses("mixing"):
        samples_by_set = {s.set_label: [x.sample_label for x in s.samples] for s in ex.structure.experiment_sets}
        mixing += volumes_as_concentrations(ex.chemistry)
        mixing += derive_mixture_concentrations(ex.chemistry, set_labels, samples_by_set)
    mixing += derive_from_ratios(ex.chemistry, set_labels) if pack.uses("molar_ratios") else []
    rows = build_rows(ex.metadata, ex.structure, ex.methodology, ex.chemistry, config.paper_prefix,
                      drop_below=config.confidence_drop_below, registry=registry, optional=ex.optional_list)
    stage_flags = _pack_postprocess(pack, rows, ex, config)
    thresholds = dict(flag_below=config.confidence_flag_below,
                      drop_below=config.confidence_drop_below)
    paper_flags = check_extraction(ex.methodology, ex.chemistry, optional=ex.optional_list, **thresholds)
    paper_flags += _cited_data_flags(ex.structure)
    if config.is_local:                   # results from a model the app hasn't been validated with
        from parameter_extractor.local_models import flag_text
        paper_flags.append(Flag("local_model", flag_text(config)))
        paper_flags += [Flag("local_model", m) for m in getattr(ctx, "server_flags", None) or []]   # E3: CPU spill
    paper_flags += _reuse_flags(ctx)
    paper_flags += stage_flags
    paper_flags += [Flag("assumed_default", m) for m in ex.ambient_notes]
    paper_flags += _table_check_flags(ex, config)
    paper_flags += _identity_flags(ex.chemistry, ex.parsed.pages_for_lookup)
    paper_flags += _not_a_compound_flags(ex.chemistry)
    paper_flags += [Flag("unit_conversion", n.message, quote=n.quote or None, source=n.source or None)
                    for n in normalization if n.kind == "unit_corrected"]
    paper_flags += [Flag("ambiguous_name", n.message, quote=n.quote or None, source=n.source or None)
                    for n in normalization if n.kind == "ambiguous_name"]
    if pubchem and pubchem.unavailable_reason:
        paper_flags.append(Flag("lookup_unavailable", f"{pubchem.unavailable_reason}: species names were "
                                f"matched by the built-in rules only, so synonyms may show up as new variables."))
    paper_flags += grouped_mixing_flags(mixing)
    n_text_rows = len(rows)

    figure_summary, fig_new_vars = [], []
    if digitized:
        fig_rows, problems, fig_new_vars = build_figure_rows(
            list(digitized), ex.metadata, _paper_wide_methodology(ex), config.paper_prefix,
            first_set_index=len(ex.structure.experiment_sets) + 1,
            first_entry_number=len(rows) + 1, registry=registry, paper_wide=_paper_wide_values(ex),
            abbreviations=ex.abbreviations)
        rows += fig_rows
        paper_flags += [Flag("figure_problem", p) for p in problems]
        annotated = {}
        for fig in digitized:
            annotated[fig.figure_id] = str(save_digitized(fig, ctx.run_dir / "figures")[1])
            if getattr(fig, "auto_digitized", False):
                n_pts = sum(len(x.points) for x in fig.series)
                n_bars = sum(p.err_hi_py is not None or p.err_lo_py is not None for x in fig.series for p in x.points)
                paper_flags.append(Flag(
                    "auto_digitized",
                    f"{fig.figure_id} was digitized automatically from its suggestions: {n_pts} point(s) in "
                    f"{len([x for x in fig.series if x.points])} series" + (f", {n_bars} with error bars" if n_bars
                                                                            else "")
                    + ". Check the annotated image in the Figures tab against the figure. "
                    + (fig.auto_summary.replace("\n", " ") if fig.auto_summary else "")))
            if fig.data_source:
                paper_flags.append(Flag(
                    "cited_data",
                    f"{fig.figure_id} was digitized, but it reproduces another publication's data: "
                    f"{fig.data_source}. Its rows say so in original_data_reference; consider "
                    f"digitizing the original instead."))
            if fig.plan and fig.plan.duplicates_tabulated_data:
                paper_flags.append(Flag(
                    "possible_duplicate",
                    f"{fig.figure_id} was digitized, but it may plot the same data as a table "
                    f"({fig.plan.duplicate_note or 'see the figure plan'}). Check for duplicate rows."))
            n_points = sum(len(s.points) for s in fig.series)
            figure_summary.append({"figure_id": fig.figure_id,
                                   "status": "digitized automatically" if getattr(fig, "auto_digitized", False)
                                   else "digitized",
                                   "series": len([s for s in fig.series if s.points]),
                                   "points": n_points, "annotated_image": annotated[fig.figure_id]})
    paper_flags += [Flag("figure_problem", f"Not digitized automatically -- {note}") for note in ex.auto_figure_notes]
    done = {f["figure_id"] for f in figure_summary}
    for fig in ex.figures:
        if fig.figure_id not in done:
            status = "skipped" if fig.figure_id in skipped_figures else "not digitized"
            figure_summary.append({"figure_id": fig.figure_id, "status": status,
                                   "series": 0, "points": 0})
    found = {f.figure_id: f for f in ex.figures}           # for the Figures tab: image + caption
    for f in figure_summary:
        if f["figure_id"] in found:
            c = found[f["figure_id"]]
            f.update(image=c.crop_image, caption=c.caption, page=c.page_label or c.page)
    _tidy_figure_images(ex, figure_summary)

    if pack.uses("water_type"):                 # "water" -> which water (assumed distilled, flagged)
        paper_flags += [Flag("assumed_default", m) for m in normalize_water(rows)]
    if pack.uses("atmospheric_start"):          # sealed batch, no pressure stated -> 1 bar (one flag)
        from parameter_extractor.calculators.pressure import assume_atmospheric_start
        paper_wide = next((getattr(v, "text", "") or "" for _, result in ex.optional_list for v in result.parameters
                           if v.parameter == "vessel_sealed" and not v.set_label and not getattr(v, "sample_label", "")
                           and v.basis != "assumed"), "")
        paper_flags += [Flag("assumed_default", m) for m in assume_atmospheric_start(rows, paper_wide)]

    # ---- variables without a column: registry first, then the user's review ----
    index = row_index(ex.structure, rows, config.paper_prefix)
    # amounts the chemistry already records aren't offered a second time (one quantity, one variable)
    repeats = drop_repeated_amounts(ex.methodology, ex.chemistry)
    paper_flags += [Flag("duplicate_removed",
                         f"'{d.parameter.name}' ({d.parameter.value}) was left out: it repeats {d.matches}, "
                         f"already recorded with the solution chemistry. Keeping both could read as twice "
                         f"the amount.", quote=d.parameter.quote or None, source=d.parameter.source or None)
                    for d in repeats]
    software = drop_recorded_software(ex.methodology, ex.fit_models)
    paper_flags += [Flag("duplicate_removed",
                         f"'{d.parameter.name}' ({d.parameter.value}) was left out: {d.matches} is already "
                         f"recorded by the fitting-models step (the *_fitsoftware columns).",
                         quote=d.parameter.quote or None, source=d.parameter.source or None) for d in software]
    repeats += software
    values = drop_repeated_values(ex.methodology, rows, lambda s, smp: _rows_for(s, smp, index))
    paper_flags += [Flag("duplicate_removed",
                         f"'{d.parameter.name}' ({d.parameter.value}) was left out: its numbers are already in "
                         f"the dataset ({d.matches}).", quote=d.parameter.quote or None,
                         source=d.parameter.source or None) for d in values]
    repeats += values
    new_vars = collect_new_variables(ex.methodology, ex.chemistry, registry, index, ex.term_search,
                                     optional=ex.optional_list, structure=ex.structure)
    new_vars += fig_new_vars
    paper_flags += [Flag("value_not_read", m) for m in ex.grid_problems]      # mapped table cells not read
    paper_flags += scope_flags
    if pack.uses("analysis") and ex.analysis is not None:     # instrument settings -> analysis_* columns
        from parameter_extractor.analysis_vocab import vocabulary as analysis_vocabulary
        from parameter_extractor.calculators.analysis_columns import apply_analysis
        from parameter_extractor.scopes import filter_analysis
        outside = filter_analysis(ex.analysis, config.scopes.get("analysis"), analysis_vocabulary())
        if outside:
            paper_flags.append(Flag("scope", f"This run recorded only the instrument families chosen in the "
                                             f"Parameters panel; left out: {', '.join(outside)}."))
        analysis_vars, analysis_flags = apply_analysis(rows, ex.analysis, registry,
                                                       lambda s, smp: _rows_for(s, smp, index))
        new_vars += analysis_vars
        paper_flags += [Flag(kind, message) for kind, message in analysis_flags]
    if ex.skipped_kind == "figures-only paper":
        paper_flags.append(Flag("no_results", "No results in the paper's tables or text (they're only in figures), and "
                                              "this run digitizes no figures, so the extraction steps were skipped (no "
                                              "cost beyond planning the rows). Open the paper in the app to digitize "
                                              "its figures."))
    elif ex.skipped_kind:
        paper_flags.append(Flag("no_results", f"The paper was planned as a {ex.skipped_kind}, with no experiments of "
                                              f"its own, so the extraction steps were skipped (no cost beyond planning "
                                              f"the rows). If it does report experiments, run it again."))
    elif pack.uses("results_check") and not _has_results(rows, new_vars):
        paper_flags.append(Flag("no_results", NO_RESULTS_MESSAGE))
    known, pending = split_known(new_vars, registry)
    accepted = []
    conversion_problems = []
    from parameter_extractor.value_types import column_type
    for column, v in known:
        conversion_problems += write_values(rows, column, [v], column_type(column, registry))[1]
        accepted.append({"name": v.name, "kind": v.kind, "column": column, "values": 1,
                         "how": "recognised from an earlier review", "category": v.category})
    groups = group_new_variables(pending)
    unfound = _unfound_terms(ex.term_search)
    # suggestions off: only what the user asked about (search terms) and assumed values are reviewed
    unsuggested = [] if config.suggest_new_variables else [g for g in groups if not _always_reviewed(g)]
    shown = [g for g in groups if g not in unsuggested]
    decisions = review(shown, unfound, registry) if (review and (shown or unfound)) else []
    left_out = apply_decisions(rows, groups, decisions, registry)
    conversion_problems += apply_decisions.problems
    paper_flags += [Flag("unit_conversion", p) for p in conversion_problems]
    by_key = {(d.kind, d.alias_name): d for d in decisions}
    for g in groups:
        d = by_key.get((g.kind, g.alias_name))
        if g not in left_out and d:
            accepted.append({"name": g.name, "kind": g.kind, "column": d.column.strip(),
                             "values": sum(v.include for v in g.values), "how": f"accepted in review ({d.action})",
                             "category": g.category})
            if g.kind == "assumed_value":
                v = g.values[0]
                paper_flags.append(Flag(
                    "assumed_value",
                    f"{g.name} = {_shown(v)} for {_where(v)} is NOT stated in the paper (assumed); "
                    f"included because you chose to in the review.", quote=v.quote or None,
                    source=v.source or None))
    if decisions:
        registry.save()
    # built-in columns whose data type the user changed (Remembered variables > Built-in)
    from parameter_extractor.value_types import apply_column_types
    paper_flags += [Flag("unit_conversion", p) for p in apply_column_types(rows, registry.builtin_types())]
    held_out = [v for g in left_out for v in g.values]
    paper_flags += [Flag("pass_disagreement", m) for m in disagreement_flags(ctx.vote_notes)]
    # what the user decided in the review ("Don't add", or values unticked) was just checked there: not flagged
    # again (Mickey, 2026-11-11; the values stay in new_variables.json). Variables nobody decided on -- runs
    # without a review (CLI, unattended queues) -- are still flagged.
    seen = set(by_key)
    paper_flags += _new_variable_flags([g for g in left_out if g not in unsuggested
                                        and (g.kind, g.alias_name) not in seen])
    if unsuggested:
        paper_flags.append(_unsuggested_flag(unsuggested))
    paper_flags += [Flag("term_not_found", f"You asked for '{t}': the paper doesn't state it "
                                           f"(targeted search found nothing).") for t in unfound]
    if new_vars:
        (ctx.run_dir / "new_variables.json").write_text(json.dumps(
            {"left_out": [v.model_dump(exclude_none=True) for v in held_out],
             "repeats_left_out": [dict(d.parameter.model_dump(), repeats=d.matches) for d in repeats],
             "accepted": accepted,
             "decisions": [d.__dict__ for d in decisions]}, indent=2, ensure_ascii=False))

    # after the review, so accepted peptide columns count too
    totals, differing = fill_total_peptide_yield(rows) if pack.uses("peptide_totals") else ([], [])
    for full_id, stated, total, listed in differing:
        paper_flags.append(Flag(
            "conflicting_values", f"Row {full_id}: the paper's total peptide yield is {stated:g}%, but the peptide "
            f"yields extracted for that row add up to {total:g}% ({listed}). Rounding in the paper, or lengths "
            f"it doesn't list individually? The stated total was kept."))
    if totals:
        paper_flags.append(Flag(
            "derived_value", f"total_sampled_peptides_yield calculated for {len(totals)} row(s) as the sum of the "
            f"peptide % yields reported for each (linear and cyclic); rows where the paper "
            f"states the total keep the stated value. Hover a value to see what was added."))
    if pack.uses("oligomer_totals"):            # nucleic-acid oligomers: total yield, longest oligomer (calculated)
        from parameter_extractor.calculators.oligomer_totals import fill_oligomer_totals
        o_totals, o_lengths, o_differing = fill_oligomer_totals(rows)
        for full_id, stated, total, listed in o_differing:
            paper_flags.append(Flag(
                "conflicting_values", f"Row {full_id}: the paper's total oligomer yield is {stated:g}%, but the oligomer "
                f"yields extracted for that row add up to {total:g}% ({listed}). The stated total was kept."))
        if o_totals or o_lengths:
            paper_flags.append(Flag(
                "derived_value", "Calculated from the row's oligomers ('<n>mer' columns): "
                + "; ".join(x for x in (
                    f"total_sampled_oligomers_yield for {len(o_totals)} row(s) as the sum of the 2-mer and longer "
                    f"% yields" if o_totals else "",
                    f"max_oligomer_length_nt for {len(o_lengths)} row(s) as the longest oligomer with a value"
                    if o_lengths else "") if x)
                + ". Rows where the paper states them keep the stated values; hover a value to see what was used."))
    if pack.uses("result_basis"):                # measured or calculated, per row (calculators/result_basis.py)
        from parameter_extractor.calculators.result_basis import apply_result_basis
        from parameter_extractor.ingestion.data_location import location
        captions = {location(t.get("table_id", "")): t.get("caption", "") for t in (ex.tables or [])}
        paper_flags += apply_result_basis(rows, [s.set_label for s in ex.structure.experiment_sets], captions)
    if config.fill_shared_values and pack.manifest.shared_columns:   # methods every experiment shares (2026-11-12)
        from parameter_extractor.calculators.shared_values import fill_shared
        from parameter_extractor.column_order import ColumnOrder
        paper_flags += fill_shared(rows, pack.manifest.shared_columns, ColumnOrder(pack))
    if pack.manifest.formulas:                   # the research area's own calculations (formulas.py), after the review
        from parameter_extractor.formulas import apply_formulas, formula_flags
        paper_flags += formula_flags(apply_formulas(rows, pack.manifest.formulas))
    archive = None
    if pack.uses("archive_validation") and config.online_checks:
        archive = _archive_check(rows, ex, ctx)
        paper_flags += archive_flags(archive)
    row_flags = {r.full_id: f for r in rows if (f := check_row(r, **thresholds))}
    paper_flags += _range_flags(rows)
    paper_flags += starting_composition_flags(rows)          # products but no starting compounds (2026-11-12)
    image_tables = image_table_numbers(ex.parsed.table_pages) if config.rasterize_table_pages else set()
    table_pages = table_page_numbers(ex.parsed.table_pages)
    paper_flags += _source_flags(ex.source)
    for si in ex.parsed.supplements:
        paper_flags.append(Flag("paper_source", f"Supplementary information read with the paper: "
                                                f"{Path(si['file']).name} ({si['pages']} pages). Its pages are "
                                                f"shown as S1-S{si['pages']}; its values are reported under this "
                                                f"paper."))
    if ex.source is not None and ex.source.read_arxiv:          # common column: which arXiv version
        from parameter_extractor.ingestion.flatten_to_template import set_row_value
        from parameter_extractor.schemas.row_schema import CellSource
        arxiv_src = CellSource(origin="arXiv record", source=ex.source.label)
        for r in rows:
            set_row_value(r, "paper_arxiv_id", ex.source.record.versioned_id, arxiv_src)
    check_flag_quotes([*paper_flags, *(f for fs in row_flags.values() for f in fs)], ex.parsed.text, image_tables,
                      ex.parsed.pages_for_lookup, table_pages)
    check_row_quotes(rows, ex.parsed.text, image_tables, ex.parsed.pages_for_lookup, table_pages)
    if ex.parsed.supplements:          # pages of the supplementary information are shown as S1, S2, ...
        for f in [*paper_flags, *(f for fs in row_flags.values() for f in fs)]:
            f.page = ex.parsed.page_label(f.page)
        for row in rows:
            for src in row.provenance.values():
                src.page = ex.parsed.page_label(src.page)
    # the long-format record is canonical; the wide template CSV is generated from it
    from parameter_extractor.column_order import ColumnOrder, write_column_list
    chosen = {a["column"]: a.get("category", "") for a in accepted}
    order = ColumnOrder(chosen=chosen, registry=registry)
    observations = rows_to_observations(rows)
    observations_path = ctx.run_dir / f"{ex.paper_id}_observations.csv"
    from parameter_extractor.compound_names import renames_for
    write_observations_csv(observations, observations_path, order,
                           renames=renames_for({o.column for o in observations}, registry))
    csv_path = ctx.run_dir / f"{ex.paper_id}_extracted.csv"
    write_template_csv(observations_to_records(observations), csv_path, column_categories=chosen, registry=registry)
    # every column of the dataset with its category (the dataset CSV keeps one header row)
    write_column_list(write_template_csv.header, order, ctx.run_dir / f"{ex.paper_id}_columns.csv")

    # flags about exactly the same values become one entry (Mickey, 2026-11-11: BaCl2 of eder1994 flagged twice --
    # identity inferred, and medium confidence): the strongest reason leads, the others listed under it (flag_targets)
    from parameter_extractor.validation.quotes import unrelated_quotes
    paper_flags += unrelated_quotes(observations, ex.parsed.page_texts or [ex.parsed.text])   # quote misses its value
    from parameter_extractor import flag_targets
    paper_flags, row_flags = flag_targets.consolidate(
        paper_flags, row_flags, flag_targets.Index(({"full_id": o.full_id, "column": o.column, "value": o.value,
                                                     "source": o.source, "quote": o.quote, "set_id": o.set_id}
                                                    for o in observations),
                                                   set_labels=[s.set_label for s in ex.structure.experiment_sets]))
    flags_path = None
    if paper_flags or row_flags:
        flags_path = ctx.run_dir / "plausibility_flags.json"
        flags_path.write_text(json.dumps(flags_to_json(paper_flags, row_flags),
                                         indent=2, ensure_ascii=False))

    carried = []
    if getattr(config, "resume_from", None):        # W2: the earlier run's corrections and checked marks come along
        from parameter_extractor import corrections as corr
        carried = corr.carry_over(Path(config.resume_from), ctx.run_dir)
        if carried:
            ctx.note("assemble", f"{len(carried)} correction(s) of the earlier run applied again")

    gold_score = None
    if settings.USE_GOLD_STANDARD:  # OFF until the curated subset exists
        from parameter_extractor.validation.gold_standard_eval import load_gold_standard, score_paper
        gold_score = score_paper([r.model_dump() for r in rows], load_gold_standard())

    _write_summary(ctx, ex.pdf_path, ex.started, rows=len(rows),
                   read_from=ex.source.label if ex.source else str(ex.pdf_path),
                   paper_flags=len(paper_flags), rows_flagged=len(row_flags),
                   new_variables_left_out=len(left_out),
                   new_variables_accepted=[a["name"] for a in accepted],
                   searched_terms=list(config.focus_terms), unfound_terms=unfound,
                   normalization=[{"kind": n.kind, "change": n.message} for n in normalization],
                   figures=sorted(figure_summary, key=lambda f: f["figure_id"]),
                   tables=ex.tables,
                   equations=[{"label": e.label, "page": e.page, "latex": e.latex} for e in ex.equations],
                   **({"corrections_carried_over": len(carried)} if carried else {}))

    return RunResult(paper_id=ex.paper_id, run_dir=ctx.run_dir, csv_path=csv_path, rows=rows,
                     paper_flags=paper_flags, row_flags=row_flags, usage=list(ctx.usage),
                     flags_path=flags_path, gold_standard_score=gold_score,
                     observations_path=observations_path,
                     figures=sorted(figure_summary, key=lambda f: f["figure_id"]), tables=list(ex.tables),
                     new_variables=held_out, accepted_variables=accepted, unfound_terms=unfound,
                     equations=list(ex.equations))


def _table_check_flags(ex: "Extraction", config: RunConfig) -> List[Flag]:
    """F3: table values compared with a second reading of the tables (ingestion/table_check.py); never stops a run."""
    if not getattr(config, "table_check", True):
        return []
    try:
        from parameter_extractor.ingestion import table_check as tc
        values = tc.values_from(ex.optional_list, ex.chemistry)
        if not values:
            return []
        grids, reading, reliable = tc.second_reading(ex, config)
        if not grids:
            return []
        findings = tc.cross_check(values, grids, reliable)
        ex.ctx.note("assemble", f"Second reading of the tables ({reading}): {len(values)} table values, "
                                f"{len(findings)} to check")
        return [Flag(kind, message) for kind, message in tc.flag_messages(findings, reading)]
    except Exception as e:                             # a cross-check is a convenience
        ex.ctx.note("assemble", f"The second reading of the tables failed: {e}")
        return []


def _reuse_flags(ctx: RunContext) -> List[Flag]:
    """A resumed / rebuilt run (resume.py, W1): which answers came from the earlier folder, and -- for a rebuild --
    which of them were made for a request that has changed since (the data pack's prompts or settings)."""
    old = getattr(ctx.config, "resume_from", None)
    if not old:
        return []
    reused = [u.stage for u in ctx.usage if getattr(u, "reused", False)]
    asked = sorted({u.stage for u in ctx.usage if not getattr(u, "reused", False)})
    what = "Rebuilt" if ctx.config.rebuild else "Resumed"
    flags = [Flag("reused_answer", f"{what} from the earlier run {Path(old).name}: {len(reused)} answer(s) reused "
                                   f"({', '.join(sorted(set(reused))) or 'none'})"
                                   + (f"; asked again: {', '.join(asked)}" if asked else "; nothing was asked again")
                                   + ". Digitized figures and review decisions of that run were used again.")]
    changed = sorted(set(getattr(ctx, "reused_changed", [])))
    if changed:
        flags.append(Flag("reused_answer", f"Rebuilt with saved answers whose request has changed since they were "
                                           f"made: {', '.join(changed)}. The data pack's instructions or settings for "
                                           f"these steps differ now, so their answers may not match what this data "
                                           f"pack would extract. Resume (instead of Rebuild) asks the model again for "
                                           f"them."))
    return flags


def _cited_data_flags(structure: StructurePlan) -> List[Flag]:
    """One flag per publication the paper reproduces data from (its sets listed)."""
    by_source: Dict[str, list] = {}
    for s in structure.experiment_sets:
        if s.data_source:
            by_source.setdefault(s.data_source, []).append(s)
    flags = []
    for source, sets in by_source.items():
        n = sum(len(s.samples) for s in sets)
        named = (f"Set '{sets[0].set_label}'" if len(sets) == 1
                 else "Sets " + ", ".join(f"'{s.set_label}'" for s in sets))
        flags.append(Flag("cited_data",
                          f"{named} ({n} rows) {'is' if len(sets) == 1 else 'are'} reproduced from another "
                          f"publication, not measured in this paper: {source}. Its rows say so in "
                          f"original_data_reference; consider extracting this data from the original paper instead.",
                          source=sets[0].source_table_or_section))
    return flags


def _unfound_terms(term_search: Optional[TermSearch]) -> List[str]:
    if not term_search:
        return []
    found = {f.term.strip().lower() for f in term_search.findings if f.found}
    out = []
    for f in term_search.findings:
        if not f.found and f.term.strip().lower() not in found and f.term not in out:
            out.append(f.term)
    return out


def _always_reviewed(g: VariableGroup) -> bool:
    """Reviewed even with suggestions off: assumed values and findings for the user's own terms."""
    return g.kind == "assumed_value" or any(v.origin.startswith("search: ") for v in g.values)


def _unsuggested_flag(groups: List[VariableGroup]) -> Flag:
    """With suggestions off: one flag listing what was left out, by category (nothing dropped
    silently -- the values are in new_variables.json)."""
    from parameter_extractor.variable_categories import by_id
    by_category: Dict[str, List[str]] = {}
    for g in groups:
        category = by_id(g.category)
        by_category.setdefault(category.label if category else "Other", []).append(g.name)
    listing = "; ".join(f"{label}: {', '.join(names)}" for label, names in by_category.items())
    return Flag("new_variable",
                f"New-variable suggestions are off: {len(groups)} variable(s) with no column were left out "
                f"of the CSV without review ({listing}). Their values are in new_variables.json; turn "
                f"suggestions on to review them.")


def _new_variable_flags(groups: List[VariableGroup]) -> List[Flag]:
    """One flag per variable left out of the CSV, with an example quote."""
    from parameter_extractor.variable_categories import by_id
    flags = []
    # the same assumption in several places (pulletikurti2022: 'r.t.' as 25 C in 8 sets) -> one flag
    assumed: Dict[tuple, list] = {}
    for g in groups:
        if g.kind == "assumed_value":
            assumed.setdefault((g.name, _shown(g.values[0])), []).append(g.values[0])
    for (name, shown), vs in assumed.items():
        where = "; ".join(_where(v) for v in vs[:6]) + (f"; ... ({len(vs) - 6} more)" if len(vs) > 6 else "")
        flags.append(Flag(
            "assumed_value",
            f"{name} = {shown} for {where} is not stated in the paper (the model marked it assumed), so it was NOT "
            f"written. Enter it by hand if you agree.", quote=vs[0].quote or None, source=vs[0].source or vs[0].origin))
    for g in groups:
        if g.kind == "assumed_value":
            continue
        what = {"species": "species", "parameter": "experimental parameter",
                "figure_axis": "figure axis column"}[g.kind]
        first = g.values[0]
        role = f", {first.role}" if first.role else ""
        category = by_id(g.category)
        role += f" ({category.label})" if category else ""
        example = next((v for v in g.values if v.quote), first)
        flags.append(Flag(
            "new_variable",
            f"New {what} '{g.name}'{role}: no column for it, so its {len(g.values)} value(s) were "
            f"left out of the CSV (not accepted in review)"
            + (f"; it would become '{g.proposed_column}'" if g.proposed_column else "") + "."
            + "".join(sorted({f" Format: {v.format_note}." for v in g.values if v.format_note})),
            quote=example.quote, source=example.source or first.origin))
    return flags


def auto_digitize_figures(ex: "Extraction") -> Tuple[List[DigitizedFigure], List[str]]:
    """Unattended runs with RunConfig.auto_digitize_figures (Mickey, 2026-11-03): suggestions for every figure of
    the paper itself (not the supplement's), kept when they parse cleanly (digitizing/auto_figure.py). Returns
    (digitized, skipped figure ids); why the others weren't is in ex.auto_figure_notes."""
    from parameter_extractor.digitizing.auto_figure import auto_digitize, figure_for
    digitized, skipped = [], []
    for fig in ex.figures:
        if fig.supplement:
            skipped.append(fig.figure_id)
            continue
        try:
            result = auto_digitize(figure_for(fig), plan_figure(ex, fig))
        except Exception as e:                       # one figure never stops the paper
            ex.auto_figure_notes.append(f"{fig.figure_id}: automatic digitizing failed ({e})")
            skipped.append(fig.figure_id)
            continue
        if result.easy:
            digitized.append(result.figure)
        else:
            ex.auto_figure_notes.append(f"{fig.figure_id}: " + "; ".join(result.reasons))
            skipped.append(fig.figure_id)
    return digitized, skipped


def run_pipeline(
    pdf_path,
    config: RunConfig,
    on_progress: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> RunResult:
    """Fully automatic: extract and finish, with no figures digitized (figures
    found are listed as "not digitized" in run_summary.json) -- unless auto_digitize_figures is on: then the easy
    ones are digitized from their suggestions."""
    ex = _extract_unattended(pdf_path, config, on_progress, cancel_event)
    if config.auto_digitize_figures and ex.figures:
        digitized, skipped = auto_digitize_figures(ex)
        return finish(ex, digitized, skipped)
    return finish(ex)


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
