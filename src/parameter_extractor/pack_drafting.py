"""
Draft a research area from sample papers (Mickey, 2026-11-08): instead of starting a new data pack from the template
or a copy, the user gives a name, a short description and a few typical papers; the app

1. SURVEYS each paper (one cheap request per paper -- Claude Haiku 5.5 by default, the paper's text plus its table
   images): the variables its experiments report, with unit, kind, role, the level they vary at, whether
   uncertainties are given and one example -- a survey of what kinds of values exist, not an extraction;
2. MERGES the surveys in one request (Claude Sonnet 5.5): the words for a set / a row, 3-7 variable categories,
   1-4 extraction stages with their parameters (descriptions the extraction model will read, choices, uncertainty
   flags), and rules for planning the rows;
3. WRITES a new pack in the usual format (packs.create_pack from the template, then pack_editing.PackDraft): column
   names get the app's unit suffixes locally (`column_for`: '°C' -> _C, '%' -> _pct, K stored as °C, ...), duplicate
   columns across stages are dropped, the template's examples are removed, and pack_editing.check runs on the result.

No row planning, figure suggestions or values are extracted. The pack opens in the editor for fine-tuning; a report
(drafted_from.md in the pack folder) lists each parameter with the papers that reported it and example values. Costs
are a few cents a paper (survey) plus one Sonnet request; with a local model server (RunConfig.provider == "local")
both steps use the profile's extraction model.
"""
from __future__ import annotations
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from parameter_extractor import packs
from parameter_extractor.config import settings
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import PipelineError, RunCancelledError

PROMPTS = Path(__file__).parent / "prompts"
SURVEY_MODEL = "claude-haiku-5-5"          # cheap: a survey of variable kinds, not an extraction
SYNTHESIS_MODEL = "claude-sonnet-5-5"      # one request; the design decisions are made here
MAX_PAPER_CHARS = 200_000
SURVEY_BUDGET, SYNTHESIS_BUDGET = 8000, 16000
RESERVED_CATEGORIES = {"metadata", "methodology", "other"}       # the app's shared categories


# ---- answers -------------------------------------------------------------------------------------------------------

class SurveyVariable(BaseModel):
    name: str = Field(description="The variable as the paper calls it.")
    column: str = Field(description="Short snake_case column name WITHOUT a unit, e.g. 'reaction_temperature'.")
    unit: str = Field(description="Unit the values are given in ('°C', 'mM', 'h', '%'); '' for text or unitless.")
    kind: Literal["number", "integer", "text"]
    role: Literal["condition", "material", "composition", "result", "method", "other"]
    description: str = Field(description="What it is, at most 20 words.")
    level: Literal["row", "set", "paper"] = Field(description="Where values differ: between rows, between groups "
                                                              "of rows, or one value for the paper.")
    uncertainty: bool = Field(description="The paper gives uncertainties / error bars for it.")
    where: Literal["table", "text", "figure"]
    example: str = Field(description="One value as printed, with its unit.")


class PaperSurvey(BaseModel):
    field: str = Field(description="What the paper studies, at most 15 words.")
    row_unit: str = Field(description="What one row of results is, e.g. 'one time point of one reaction'.")
    set_unit: str = Field(description="What groups rows, e.g. 'one reaction condition'.")
    variables: List[SurveyVariable]
    notes: str = Field(description="Anything unusual about how the results are reported, at most 20 words; or ''.")


class ProposedCategory(BaseModel):
    id: str = Field(description="snake_case id, not 'metadata', 'methodology' or 'other'.")
    label: str
    description: str = Field(description="What belongs in it, one sentence.")
    value_type: Literal["number", "text", "any"]


class ProposedParameter(BaseModel):
    column: str = Field(description="snake_case WITHOUT a unit; the app adds the unit suffix.")
    unit: str = Field(description="The unit values are stored in; '' for text or unitless.")
    kind: Literal["number", "integer", "text"]
    description: str = Field(description="One sentence: exactly what belongs in the column (the extraction model "
                                         "reads it).")
    category: str = Field(description="One of the category ids.")
    choices: List[str] = Field(description="Allowed words for a text parameter with few values; else [].")
    uncertainties: bool
    papers: int = Field(description="How many of the sample papers report it.")


class ProposedStage(BaseModel):
    name: str = Field(description="snake_case, e.g. 'conditions'.")
    label: str
    description: str = Field(description="What the stage extracts, one sentence.")
    per: Literal["sample", "set"]
    keywords: List[str] = Field(description="[] when every paper needs the stage; else words that trigger it.")
    parameters: List[ProposedParameter]
    rules: List[str]
    other_hint: str


class PackProposal(BaseModel):
    description: str
    set_word: str
    sample_word: str
    categories: List[ProposedCategory]
    stages: List[ProposedStage]
    row_rules: List[str]
    notes: str


# ---- result --------------------------------------------------------------------------------------------------------

@dataclass
class SurveyedPaper:
    item: str
    name: str
    survey: Optional[PaperSurvey] = None
    error: str = ""
    cost_usd: float = 0.0


@dataclass
class DraftResult:
    pack: packs.Pack
    proposal: PackProposal
    papers: List[SurveyedPaper]
    problems: list                         # pack_editing.Problem
    work_dir: Path
    cost_usd: float = 0.0
    dropped: List[str] = field(default_factory=list)      # duplicate columns left out


# ---- column names --------------------------------------------------------------------------------------------------

def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_").lower()
    return ("v_" + s) if s[:1].isdigit() else (s or "value")


def _unit_token(unit: str) -> str:
    t = re.sub(r"([A-Za-zµμ°]+)\s*\^?[-−]1\b", r"per_\1", unit)          # 'h-1' -> 'per_h'
    t = t.replace("%", "pct").replace("µ", "u").replace("μ", "u").replace("°", "").replace("/", "_per_")
    return re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_")


def column_for(base: str, unit: str, kind: str = "number") -> tuple:
    """(column, stored unit): the app's unit suffix for the unit when it has one ('°C' -> 'temperature_C', K values
    stored as °C, '%' -> '_pct'), else the unit itself as a suffix ('energy_eV'); text: no unit."""
    from parameter_extractor.ingestion.observations import unit_for_column
    from parameter_extractor.units import canonical_unit
    from parameter_extractor.variable_categories import unit_suffix
    base = re.sub(r"(^|_)ph(?=_|$)", r"\1pH", _slug(base))       # the app reads 'pH' columns as pH values
    unit = (unit or "").strip()
    if kind == "text" or not unit or unit.lower() in ("none", "unitless", "dimensionless", "-"):
        return base, ""
    if unit.lower() == "ph":
        return (base if re.search(r"(^|_)pH($|_)", base) else base + "_pH"), ""
    canon = canonical_unit(unit)
    suffix = unit_suffix(canon) if canon else ""
    if not suffix:
        suffix = "_" + _unit_token(canon or unit) if _unit_token(canon or unit) else ""
    if suffix and base.lower().endswith(suffix.lower()):
        base = base[: -len(suffix)]                          # the model put the unit in the name anyway
    column = base + suffix
    named = unit_for_column(column)
    if not canon and named and named != unit:
        # a unit the app doesn't convert whose token ends like one it does ('% h-1' -> '..._per_h' reads as hours):
        # no suffix, the unit stays on the parameter
        return base, unit
    return column, (named or canon or unit)


# ---- the two steps -------------------------------------------------------------------------------------------------

def _prompt(name: str, **slots) -> str:
    text = (PROMPTS / f"{name}.md").read_text()
    for key, value in slots.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def _config(config: RunConfig) -> RunConfig:
    """The drafting steps' models: Haiku surveys, Sonnet merges (a local server: the profile's models)."""
    if config.is_local:
        return config
    models = {**config.models, "pack_survey": config.models.get("pack_survey", SURVEY_MODEL),
              "pack_synthesis": config.models.get("pack_synthesis", SYNTHESIS_MODEL)}
    return replace(config, models=models, model_profile="standard", batch_mode=False, passes=1)


def survey_paper(item, config: RunConfig, work_dir: Path, area: str, description: str,
                 cancel_event: Optional[threading.Event] = None) -> SurveyedPaper:
    from parameter_extractor.api_client import call_structured
    from parameter_extractor.focused_search import _paper_text
    from parameter_extractor.paper_source import resolve_paper, run_name
    from parameter_extractor.run_context import RunContext, total_cost
    out = SurveyedPaper(item=str(item), name=run_name(item))
    run_dir = work_dir / "papers" / out.name
    run_dir.mkdir(parents=True, exist_ok=True)
    ctx = RunContext(config=config, run_dir=run_dir, total_steps=1, cancel_event=cancel_event)
    try:
        ctx.check_cancelled()
        source = resolve_paper(item, run_dir, prefer_arxiv=config.prefer_arxiv, ads_token=config.ads_token)
        text, images = _paper_text(source, run_dir, True, config.rasterize_table_pages, config.table_raster_dpi,
                                   config.include_supplements)
        prompt = _prompt("pack_survey", AREA=area, AREA_DESCRIPTION=description)
        out.survey = call_structured(
            ctx, stage="pack_survey", system_prompt="Survey which variables a research paper reports. Report only "
            "what the paper states.", user_content=f"{prompt}\n\nPAPER TEXT:\n\n{text[:MAX_PAPER_CHARS]}",
            response_model=PaperSurvey, image_paths=images or None, max_tokens=SURVEY_BUDGET)
    except RunCancelledError:
        raise
    except PipelineError as e:
        out.error = str(e)
    except Exception as e:                 # one unreadable paper doesn't stop the rest
        out.error = f"{type(e).__name__}: {e}"
    out.cost_usd = total_cost(ctx.usage) or 0.0
    return out


def _survey_digest(papers: List[SurveyedPaper]) -> str:
    """The surveys as compact JSON lines for the merge request."""
    lines = []
    for i, p in enumerate(papers, 1):
        s = p.survey
        lines.append(f"PAPER {i} ({p.name}): field: {s.field}; one row: {s.row_unit}; rows grouped by: {s.set_unit}"
                     + (f"; notes: {s.notes}" if s.notes else ""))
        for v in s.variables:
            lines.append("  " + json.dumps({"column": v.column, "name": v.name, "unit": v.unit, "kind": v.kind,
                                            "role": v.role, "level": v.level, "unc": v.uncertainty,
                                            "where": v.where, "example": v.example, "what": v.description},
                                           ensure_ascii=False))
    return "\n".join(lines)


def synthesize(papers: List[SurveyedPaper], config: RunConfig, work_dir: Path, area: str, description: str,
               cancel_event: Optional[threading.Event] = None) -> tuple:
    from parameter_extractor.api_client import call_structured
    from parameter_extractor.run_context import RunContext, total_cost
    ctx = RunContext(config=config, run_dir=work_dir, total_steps=1, cancel_event=cancel_event)
    prompt = _prompt("pack_synthesis", AREA=area, AREA_DESCRIPTION=description, N_PAPERS=len(papers))
    proposal = call_structured(ctx, stage="pack_synthesis", system_prompt="Design a dataset's extraction setup from "
                               "surveys of sample papers.", user_content=f"{prompt}\n\nSURVEYS:\n{_survey_digest(papers)}",
                               response_model=PackProposal, max_tokens=SYNTHESIS_BUDGET)
    return proposal, total_cost(ctx.usage) or 0.0


# ---- writing the pack ------------------------------------------------------------------------------------------------

def write_pack(proposal: PackProposal, pack_id: str, label: str, description: str = "",
               base: Optional[Path] = None) -> tuple:
    """A new pack from the proposal (packs.create_pack from the template, examples replaced); (pack, dropped
    duplicate columns, {column: proposed parameter})."""
    from parameter_extractor.pack_editing import PackDraft, items_to_rules
    pack = packs.create_pack(pack_id, label, description or proposal.description, base=base,
                             units={"set": proposal.set_word, "sample": proposal.sample_word})
    draft = PackDraft.load(pack.folder)
    for file in list(draft.stages):                       # the template's example stage
        draft.remove_stage(file)
    m = draft.manifest
    m["formulas"] = []
    categories, renamed = [], {}
    for i, c in enumerate(proposal.categories):
        cid = _slug(c.id)
        if cid in RESERVED_CATEGORIES:
            renamed[c.id] = cid = f"{cid}_area"
        renamed.setdefault(c.id, cid)
        categories.append({"id": cid, "table_order": 30 + 10 * i, "label": c.label, "value_type": c.value_type,
                           "model_assigns": True, "description": c.description})
    m["variable_categories"] = categories
    category_columns: Dict[str, Dict[str, List[str]]] = {"methodology": {"columns": ["set_type"]}}
    first = categories[0]["id"] if categories else "methodology"
    category_columns.setdefault(first, {"columns": []})["columns"].append("duration_hr")
    columns, seen, dropped, by_column = ["set_type", "duration_hr"], set(), [], {}
    for st in proposal.stages:
        name = _slug(st.name)
        try:
            file = draft.new_stage(name, st.label)
        except ValueError:
            file = draft.new_stage(f"{name}_{len(draft.stages) + 1}", st.label)
        spec = draft.stages[file]
        spec.update(description=st.description, per=st.per,
                    trigger={"keywords": [k for k in st.keywords if k.strip()]} if any(k.strip() for k in st.keywords)
                    else {"always": True},
                    rules=[r for r in st.rules if r.strip()], open_ended=True,
                    open_ended_hint=st.other_hint or "other values of the experiments that have no column. Not the "
                                                     "values of the parameters above.")
        params = []
        for p in st.parameters:
            column, unit = column_for(p.column, p.unit, p.kind)
            if column in seen or column in ("set_type", "duration_hr"):
                dropped.append(f"{column} (stage {name})")
                continue
            seen.add(column)
            entry = {"column": column, "description": p.description}
            if unit:
                entry["unit"] = unit
            if p.kind == "text":
                entry["kind"] = "text"
            if p.kind == "integer":
                entry["integer"] = True
            if p.choices and p.kind == "text":
                entry["choices"] = [c for c in p.choices if c.strip()]
            if p.uncertainties and p.kind != "text":
                entry["uncertainties"] = True
            params.append(entry)
            columns.append(column)
            by_column[column] = p
            cat = renamed.get(p.category, _slug(p.category))
            if cat not in {c["id"] for c in categories}:
                cat = first
            category_columns.setdefault(cat, {"columns": []})["columns"].append(column)
        spec["parameters"] = params
    m["category_columns"] = category_columns
    draft.columns = columns
    draft.species = []
    draft.rules["structure_planner"] = items_to_rules([r for r in proposal.row_rules if r.strip()])
    draft.save()
    return packs.Pack(pack.folder), dropped, by_column


def _examples(papers: List[SurveyedPaper]) -> Dict[str, List[tuple]]:
    """survey column base -> [(paper, example)] (matched to the proposal's columns by base name)."""
    out: Dict[str, List[tuple]] = {}
    for p in papers:
        for v in (p.survey.variables if p.survey else []):
            out.setdefault(_slug(v.column), []).append((p.name, v.example))
    return out


def write_report(result: DraftResult, by_column: Dict[str, ProposedParameter], area: str) -> str:
    examples = _examples(result.papers)
    lines = [f"# {area}: drafted from sample papers", "",
             f"Drafted {datetime.now():%Y-%m-%d %H:%M} from {sum(1 for p in result.papers if p.survey)} paper(s); "
             f"cost ${result.cost_usd:.3f}. Everything below is a starting point to edit (Data Packs > Edit "
             f"research area).", "", "## Papers", ""]
    for p in result.papers:
        lines.append(f"- {p.name}: " + (f"{len(p.survey.variables)} variables; one row = {p.survey.row_unit}"
                                         if p.survey else f"not surveyed ({p.error})"))
    lines += ["", "## Stages and parameters", ""]
    for st in result.proposal.stages:
        lines.append(f"### {st.label}" + (f" (runs for papers mentioning: {', '.join(st.keywords)})"
                                         if st.keywords else ""))
        for p in st.parameters:
            column, unit = column_for(p.column, p.unit, p.kind)
            seen = examples.get(_slug(p.column), [])
            ex = "; ".join(f"{e} ({name})" for name, e in seen[:3])
            lines.append(f"- `{column}`" + (f" [{unit}]" if unit else "") + f" -- {p.description} "
                         f"(in {p.papers} paper(s)" + (f"; e.g. {ex}" if ex else "") + ")")
        lines.append("")
    if result.dropped:
        lines += ["## Left out (a column already used by an earlier stage)", ""] + [f"- {d}" for d in result.dropped] \
            + [""]
    if result.proposal.notes:
        lines += ["## Notes", "", result.proposal.notes, ""]
    return "\n".join(lines)


def check_new_id(pack_id: str, label: str) -> None:
    """The checks packs.create_pack makes, without creating anything (ValueError)."""
    if not packs.PACK_ID.fullmatch(pack_id or ""):
        raise ValueError(f"'{pack_id}' isn't a usable id: lower-case letters, digits and '_', starting with a letter "
                         f"(2-41 characters).")
    if pack_id in packs.available(include_template=True) or (packs.user_packs_dir() / pack_id).exists():
        raise ValueError(f"A research area with the id '{pack_id}' already exists.")
    if not (label or "").strip():
        raise ValueError("Give the research area a name.")


# ---- the whole thing ---------------------------------------------------------------------------------------------------

def draft_pack(items: Sequence, pack_id: str, label: str, description: str, config: RunConfig,
               on_progress: Optional[Callable[[int, int, str], None]] = None,
               cancel_event: Optional[threading.Event] = None, workers: int = 4,
               base: Optional[Path] = None) -> DraftResult:
    """Survey the papers, merge, write the pack. Raises PipelineError when no paper could be surveyed."""
    from parameter_extractor.errors import ApiKeyMissingError
    from parameter_extractor.pack_editing import check, PackDraft
    if config.needs_api_key and not config.api_key:
        raise ApiKeyMissingError()
    check_new_id(pack_id, label)                           # before paying for anything
    items = list(dict.fromkeys(items))
    if not items:
        raise PipelineError("Add at least one sample paper.")
    config = _config(config)
    report = on_progress or (lambda *a: None)
    work_dir = Path(config.output_dir) / f"pack_draft_{pack_id}_{datetime.now():%Y%m%d-%H%M%S}"
    work_dir.mkdir(parents=True, exist_ok=True)
    area = label.strip()
    total = len(items) + 2
    report(0, total, f"Surveying {len(items)} paper(s) for their variables")
    papers: List[SurveyedPaper] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items))), thread_name_prefix="survey") as pool:
        futures = {pool.submit(survey_paper, item, config, work_dir, area, description, cancel_event): item
                   for item in items}
        for f in as_completed(futures):
            p = f.result()
            papers.append(p)
            report(len(papers), total, f"{p.name}: " + (f"{len(p.survey.variables)} variables" if p.survey
                                                        else f"not surveyed ({p.error})"))
    order = {str(i): n for n, i in enumerate(items)}
    papers.sort(key=lambda p: order.get(p.item, 0))
    good = [p for p in papers if p.survey and p.survey.variables]
    if not good:
        raise PipelineError("None of the papers could be surveyed: " + "; ".join(f"{p.name}: {p.error or 'no variables'}"
                                                                              for p in papers))
    if cancel_event is not None and cancel_event.is_set():
        raise RunCancelledError()
    report(len(items), total, "Designing the research area from the surveys")
    proposal, merge_cost = synthesize(good, config, work_dir, area, description, cancel_event)
    report(len(items) + 1, total, "Writing the research area")
    pack, dropped, by_column = write_pack(proposal, pack_id, label, description, base=base)
    result = DraftResult(pack=pack, proposal=proposal, papers=papers, problems=check(PackDraft.load(pack.folder)),
                         work_dir=work_dir, cost_usd=round(sum(p.cost_usd for p in papers) + merge_cost, 4),
                         dropped=dropped)
    text = write_report(result, by_column, area)
    (pack.folder / "drafted_from.md").write_text(text)
    (work_dir / "drafted_from.md").write_text(text)
    (work_dir / "surveys.json").write_text(json.dumps(
        [{"paper": p.name, "item": p.item, "error": p.error, "survey": p.survey.model_dump() if p.survey else None}
         for p in papers], indent=2, ensure_ascii=False))
    report(total, total, f"Drafted '{label}': {sum(len(s.parameters) for s in proposal.stages)} parameters in "
                         f"{len(proposal.stages)} stage(s); ${result.cost_usd:.3f}")
    return result
