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

from parameter_extractor.calculators.mixing import derive_from_ratios, derive_mixture_concentrations
from parameter_extractor.config import settings
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import ApiKeyMissingError, PdfNotReadableError, PipelineError
from parameter_extractor.digitizing.annotate import save_digitized
from parameter_extractor.ingestion.duplicates import drop_repeated_amounts
from parameter_extractor.ingestion.figure_finder import find_figures
from parameter_extractor.ingestion.figure_rows import build_figure_rows
from parameter_extractor.ingestion.flatten_to_template import build_rows, write_template_csv
from parameter_extractor.ingestion.normalize import normalize_chemistry
from parameter_extractor.ingestion.observations import (
    observations_to_records, rows_to_observations, write_observations_csv)
from parameter_extractor.ingestion.new_variables import (
    VariableDecision, VariableGroup, apply_decisions, collect_new_variables, group_new_variables, row_index,
    split_known, write_values)
from parameter_extractor.registry import VariableRegistry
from parameter_extractor.ingestion.pdf_parser import ParsedPaper, parse_pdf, rasterize_table_pages
from parameter_extractor.run_context import ProgressCallback, RunContext, StageUsage, total_cost
from parameter_extractor.pricing import PRICES_CHECKED
from parameter_extractor.pubchem import PubChem
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.figures import DigitizedFigure, FigureCandidate, FigurePlan
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.paper_metadata import PaperMetadata
from parameter_extractor.schemas.row_schema import ExtractedRow
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.schemas.variables import NewVariable, TermSearch
from parameter_extractor.schemas.triage import TriageResult
from parameter_extractor.stages.chemistry_extractor import run_chemistry_extraction
from parameter_extractor.stages.figure_planner import run_figure_planner
from parameter_extractor.stages.metadata_extractor import run_metadata_extraction
from parameter_extractor.stages.methodology_extractor import run_methodology_extraction
from parameter_extractor.stages.structure_planner import run_structure_planner
from parameter_extractor.stages.term_search import run_term_search
from parameter_extractor.stages.wet_dry import has_cycling, run_wet_dry
from parameter_extractor.schemas.wet_dry import WetDryConditions
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
    figures: List[dict] = field(default_factory=list)   # [{figure_id, status, series, points}]
    new_variables: List[NewVariable] = field(default_factory=list)   # left out of the CSV (not accepted)
    accepted_variables: List[dict] = field(default_factory=list)     # [{name, kind, column, values, how}]
    unfound_terms: List[str] = field(default_factory=list)           # searched for, not stated in the paper

    @property
    def input_tokens(self) -> int:
        return sum(u.input_tokens for u in self.usage)

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
        "estimated_cost_usd": total_cost(ctx.usage),
        "prices_checked": PRICES_CHECKED,
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
    wet_dry: Optional[WetDryConditions] = None
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
    terms = [t.strip() for t in config.focus_terms if t.strip()]
    pdf_path, ctx = _start(pdf_path, config, 7 if terms else 6, on_progress, cancel_event)

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

        if terms:
            ctx.step("term_search", f"Searching for the {len(terms)} parameter(s) you asked for")
            columns = VariableRegistry(config.registry_path).known_columns()
            ex.term_search = run_term_search(ctx, terms, parsed.text, ex.structure, columns)

        if has_cycling(ex.structure):
            ctx.total_steps += 1        # only papers with wet-dry cycling get this step
            ctx.step("wet_dry", "Extracting wet-dry cycling conditions")
            ex.wet_dry = run_wet_dry(ctx, parsed.text, ex.structure)

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


# review(groups, unfound_terms, registry) -> decisions: shows the user the variables
# that have no column yet and returns what to do with each (GUI: the "Review new
# variables" window). Without one (CLI), nothing new is added to the CSV.
ReviewCallback = Callable[[List[VariableGroup], List[str], VariableRegistry], List[VariableDecision]]


MIXING_FLAG_KINDS = {"derived": "derived_value", "not_derived": "not_calculated", "mismatch": "conflicting_values"}


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
    normalization = normalize_chemistry(ex.chemistry, pubchem=pubchem, registry=registry)
    if pubchem:
        pubchem.save()
    set_labels = [s.set_label for s in ex.structure.experiment_sets]
    # stock -> mixture concentrations, then molar ratios -> missing concentrations; marked derived
    mixing = derive_mixture_concentrations(ex.chemistry, set_labels)
    mixing += derive_from_ratios(ex.chemistry, set_labels)
    rows = build_rows(ex.metadata, ex.structure, ex.methodology, ex.chemistry, config.paper_prefix,
                      drop_below=config.confidence_drop_below, registry=registry, wet_dry=ex.wet_dry)
    thresholds = dict(flag_below=config.confidence_flag_below,
                      drop_below=config.confidence_drop_below)
    paper_flags = check_extraction(ex.methodology, ex.chemistry, wet_dry=ex.wet_dry, **thresholds)
    paper_flags += _cited_data_flags(ex.structure)
    paper_flags += [Flag("unit_conversion", n.message, quote=n.quote or None, source=n.source or None)
                    for n in normalization if n.kind == "unit_corrected"]
    if pubchem and pubchem.unavailable_reason:
        paper_flags.append(Flag("lookup_unavailable", f"{pubchem.unavailable_reason}: species names were "
                                f"matched by the built-in rules only, so synonyms may show up as new variables."))
    paper_flags += [Flag(MIXING_FLAG_KINDS[n.kind], n.message,
                         quote=n.quote or None, source=n.source or None) for n in mixing]
    n_text_rows = len(rows)

    figure_summary, fig_new_vars = [], []
    if digitized:
        fig_rows, problems, fig_new_vars = build_figure_rows(
            list(digitized), ex.metadata, ex.methodology, config.paper_prefix,
            first_set_index=len(ex.structure.experiment_sets) + 1,
            first_entry_number=len(rows) + 1, registry=registry)
        rows += fig_rows
        paper_flags += [Flag("figure_problem", p) for p in problems]
        for fig in digitized:
            save_digitized(fig, ctx.run_dir / "figures")
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
            figure_summary.append({"figure_id": fig.figure_id, "status": "digitized",
                                   "series": len([s for s in fig.series if s.points]),
                                   "points": n_points})
    done = {f["figure_id"] for f in figure_summary}
    for fig in ex.figures:
        if fig.figure_id not in done:
            status = "skipped" if fig.figure_id in skipped_figures else "not digitized"
            figure_summary.append({"figure_id": fig.figure_id, "status": status,
                                   "series": 0, "points": 0})

    # ---- variables without a column: registry first, then the user's review ----
    index = row_index(ex.structure, rows, config.paper_prefix)
    # amounts the chemistry already records aren't offered a second time (one quantity, one variable)
    repeats = drop_repeated_amounts(ex.methodology, ex.chemistry)
    paper_flags += [Flag("duplicate_removed",
                         f"'{d.parameter.name}' ({d.parameter.value}) was left out: it repeats {d.matches}, "
                         f"already recorded with the solution chemistry. Keeping both could read as twice "
                         f"the amount.", quote=d.parameter.quote or None, source=d.parameter.source or None)
                    for d in repeats]
    new_vars = collect_new_variables(ex.methodology, ex.chemistry, registry, index, ex.term_search,
                                     wet_dry=ex.wet_dry, structure=ex.structure)
    new_vars += fig_new_vars
    known, pending = split_known(new_vars, registry)
    accepted = []
    conversion_problems = []
    for column, v in known:
        conversion_problems += write_values(rows, column, [v])[1]
        accepted.append({"name": v.name, "kind": v.kind, "column": column, "values": 1,
                         "how": "recognised from an earlier review"})
    groups = group_new_variables(pending)
    unfound = _unfound_terms(ex.term_search)
    decisions = review(groups, unfound, registry) if (review and (groups or unfound)) else []
    left_out = apply_decisions(rows, groups, decisions, registry)
    conversion_problems += apply_decisions.problems
    paper_flags += [Flag("unit_conversion", p) for p in conversion_problems]
    by_key = {(d.kind, d.alias_name): d for d in decisions}
    for g in groups:
        d = by_key.get((g.kind, g.alias_name))
        if g not in left_out and d:
            accepted.append({"name": g.name, "kind": g.kind, "column": d.column.strip(),
                             "values": len(g.values), "how": f"accepted in review ({d.action})"})
            if g.kind == "assumed_value":
                v = g.values[0]
                paper_flags.append(Flag(
                    "assumed_value",
                    f"{g.name} = {v.value:g} for set '{v.set_label}' is NOT stated in the paper (assumed); "
                    f"included because you chose to in the review.", quote=v.quote or None,
                    source=v.source or None))
    if decisions:
        registry.save()
    held_out = [v for g in left_out for v in g.values]
    paper_flags += _new_variable_flags(left_out)
    paper_flags += [Flag("term_not_found", f"You asked for '{t}': the paper doesn't state it "
                                           f"(targeted search found nothing).") for t in unfound]
    if new_vars:
        (ctx.run_dir / "new_variables.json").write_text(json.dumps(
            {"left_out": [v.model_dump(exclude_none=True) for v in held_out],
             "repeats_left_out": [dict(d.parameter.model_dump(), repeats=d.matches) for d in repeats],
             "accepted": accepted,
             "decisions": [d.__dict__ for d in decisions]}, indent=2, ensure_ascii=False))

    row_flags = {r.full_id: f for r in rows if (f := check_row(r, **thresholds))}
    flags_path = None
    if paper_flags or row_flags:
        flags_path = ctx.run_dir / "plausibility_flags.json"
        flags_path.write_text(json.dumps(flags_to_json(paper_flags, row_flags),
                                         indent=2, ensure_ascii=False))

    # the long-format record is canonical; the wide template CSV is generated from it
    observations = rows_to_observations(rows)
    observations_path = ctx.run_dir / f"{ex.paper_id}_observations.csv"
    write_observations_csv(observations, observations_path)
    csv_path = ctx.run_dir / f"{ex.paper_id}_extracted.csv"
    write_template_csv(observations_to_records(observations), csv_path)

    gold_score = None
    if settings.USE_GOLD_STANDARD:  # OFF until the curated subset exists
        from parameter_extractor.validation.gold_standard_eval import load_gold_standard, score_paper
        gold_score = score_paper([r.model_dump() for r in rows], load_gold_standard())

    _write_summary(ctx, ex.pdf_path, ex.started, rows=len(rows),
                   paper_flags=len(paper_flags), rows_flagged=len(row_flags),
                   new_variables_left_out=len(left_out),
                   new_variables_accepted=[a["name"] for a in accepted],
                   searched_terms=list(config.focus_terms), unfound_terms=unfound,
                   normalization=[{"kind": n.kind, "change": n.message} for n in normalization],
                   figures=sorted(figure_summary, key=lambda f: f["figure_id"]))

    return RunResult(paper_id=ex.paper_id, run_dir=ctx.run_dir, csv_path=csv_path, rows=rows,
                     paper_flags=paper_flags, row_flags=row_flags, usage=list(ctx.usage),
                     flags_path=flags_path, gold_standard_score=gold_score,
                     observations_path=observations_path,
                     figures=sorted(figure_summary, key=lambda f: f["figure_id"]),
                     new_variables=held_out, accepted_variables=accepted, unfound_terms=unfound)


def _cited_data_flags(structure: StructurePlan) -> List[Flag]:
    return [Flag("cited_data",
                 f"Set '{s.set_label}' ({len(s.samples)} rows) is reproduced from another publication, not "
                 f"measured in this paper: {s.data_source}. Its rows say so in original_data_reference; "
                 f"consider extracting this data from the original paper instead.",
                 source=s.source_table_or_section)
            for s in structure.experiment_sets if s.data_source]


def _unfound_terms(term_search: Optional[TermSearch]) -> List[str]:
    if not term_search:
        return []
    found = {f.term.strip().lower() for f in term_search.findings if f.found}
    out = []
    for f in term_search.findings:
        if not f.found and f.term.strip().lower() not in found and f.term not in out:
            out.append(f.term)
    return out


def _new_variable_flags(groups: List[VariableGroup]) -> List[Flag]:
    """One flag per variable left out of the CSV, with an example quote."""
    flags = []
    for g in groups:
        if g.kind == "assumed_value":
            v = g.values[0]
            flags.append(Flag(
                "assumed_value",
                f"{g.name} = {v.value:g} for set '{v.set_label}' is not stated in the paper (the model "
                f"marked it assumed), so it was NOT written. Enter it by hand if you agree.",
                quote=v.quote or None, source=v.source or v.origin))
            continue
        what = {"species": "species", "parameter": "experimental parameter",
                "figure_axis": "figure axis column"}[g.kind]
        first = g.values[0]
        role = f", {first.role}" if first.role else ""
        example = next((v for v in g.values if v.quote), first)
        flags.append(Flag(
            "new_variable",
            f"New {what} '{g.name}'{role}: no column for it, so its {len(g.values)} value(s) were "
            f"left out of the CSV (not accepted in review)"
            + (f"; it would become '{g.proposed_column}'" if g.proposed_column else "") + ".",
            quote=example.quote, source=example.source or first.origin))
    return flags


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
