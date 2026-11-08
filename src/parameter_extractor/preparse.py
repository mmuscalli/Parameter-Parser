"""
Pre-parse (Mickey's question, 2026-11-08): before a full extraction, one cheap request per paper (Claude Haiku, text
only) says which of the research area's stage parameters the paper reports; the others are left out of the run
(RunConfig.parameters_off -- not in the steps' prompts or answer schemas; a step left with nothing to ask doesn't run).

EVALUATED, NOT WIRED INTO THE APP (eval/preparse_2026-11-08.md): on the reference papers it saved ~3% net and cost ~8
points of accuracy -- the savings came from values the run then missed. The pre-parse drops parameters a run fills by
rule or inference (sampled_temperature_C = the heating temperature, a summed solvent volume), and the parameters'
own share of a run is small (~2K of ~30K cached tokens; output only exists for values a paper has anyway). Kept as
an evaluation tool (`preparse()`); RunConfig.parameters_off stays as the plumbing for leaving parameters out.
"""
from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import PipelineError, RunCancelledError

MODEL = "claude-haiku-5-5"
MAX_PAPER_CHARS = 200_000
BUDGET = 3000


class ReportedParameter(BaseModel):
    column: str = Field(description="A column from the list, exactly as written.")
    evidence: str = Field(description="Where the paper gives it: a few words ('Table 1, T column', 'Methods: 25 °C').")


class PreparseAnswer(BaseModel):
    reported: List[ReportedParameter] = Field(description=(
        "Every listed parameter this paper gives a value for -- in its tables, methods or text, for the experiments "
        "whose results it reports (also a value stated once for all experiments). Leave out parameters it doesn't "
        "mention; when unsure, include it."))


@dataclass
class PaperRelevance:
    item: str
    name: str
    reported: List[str] = field(default_factory=list)
    evidence: Dict[str, str] = field(default_factory=dict)
    error: str = ""
    cost_usd: float = 0.0


@dataclass
class PreparseResult:
    papers: List[PaperRelevance]
    parameters: List[str]                    # every stage parameter of the area
    work_dir: Path
    cost_usd: float = 0.0

    @property
    def reported(self) -> List[str]:
        """Parameters at least one paper reports (a failed paper keeps everything)."""
        if any(p.error for p in self.papers):
            return list(self.parameters)
        seen = {c for p in self.papers for c in p.reported}
        return [c for c in self.parameters if c in seen]

    @property
    def unused(self) -> List[str]:
        keep = set(self.reported)
        return [c for c in self.parameters if c not in keep]


def stage_parameters(pack, optional_stages: Optional[Dict[str, str]] = None) -> List[tuple]:
    """(stage label, column, unit, description) of the area's spec stages that aren't switched off."""
    from parameter_extractor.stages.optional import load_specs
    out = []
    for name, spec in load_specs(pack).items():
        if (optional_stages or {}).get(name, "auto") == "off":
            continue
        for p in spec.parameters:
            out.append((spec.label, p.column, p.unit, p.description))
    return out


def _listing(params: List[tuple]) -> str:
    lines, stage = [], None
    for label, column, unit, description in params:
        if label != stage:
            lines.append(f"{label}:")
            stage = label
        lines.append(f"- {column}" + (f" [{unit}]" if unit else "") + f": {description[:140]}")
    return "\n".join(lines)


def check_paper(item, params: List[tuple], config: RunConfig, work_dir: Path,
                cancel_event: Optional[threading.Event] = None) -> PaperRelevance:
    from parameter_extractor.api_client import call_structured
    from parameter_extractor.focused_search import _paper_text
    from parameter_extractor.paper_source import resolve_paper, run_name
    from parameter_extractor.run_context import RunContext, total_cost
    out = PaperRelevance(item=str(item), name=run_name(item))
    run_dir = work_dir / out.name
    run_dir.mkdir(parents=True, exist_ok=True)
    ctx = RunContext(config=config, run_dir=run_dir, total_steps=1, cancel_event=cancel_event)
    columns = {c for _, c, _, _ in params}
    try:
        ctx.check_cancelled()
        source = resolve_paper(item, run_dir, prefer_arxiv=config.prefer_arxiv, ads_token=config.ads_token)
        text, _ = _paper_text(source, run_dir, False, False, config.table_raster_dpi, config.include_supplements)
        prompt = ("Below is a list of parameters a dataset records for each experiment, then a research paper. Say "
                  "which parameters the paper gives a value for (`reported`), with a few words of evidence each. "
                  "Use the column names exactly as listed.\n\nPARAMETERS:\n" + _listing(params))
        answer = call_structured(ctx, stage="preparse", system_prompt="Check which dataset parameters a research "
                                 "paper reports. Report only what the paper states.",
                                 user_content=f"{prompt}\n\nPAPER TEXT:\n\n{text[:MAX_PAPER_CHARS]}",
                                 response_model=PreparseAnswer, max_tokens=BUDGET)
        for r in answer.reported:
            column = r.column.strip().split()[0].rstrip(":") if r.column.strip() else ""   # a copied listing line
            if column in columns and column not in out.reported:
                out.reported.append(column)
                out.evidence[column] = r.evidence
    except RunCancelledError:
        raise
    except Exception as e:                       # a paper that can't be checked keeps every parameter
        out.error = str(e) or type(e).__name__
    out.cost_usd = total_cost(ctx.usage) or 0.0
    return out


def preparse(items: Sequence, config: RunConfig, on_progress: Optional[Callable[[int, int, str], None]] = None,
             cancel_event: Optional[threading.Event] = None, workers: int = 8) -> PreparseResult:
    """Check every paper against the active research area's stage parameters (cheap model, text only)."""
    from parameter_extractor import packs
    from parameter_extractor.errors import ApiKeyMissingError
    if config.needs_api_key and not config.api_key:
        raise ApiKeyMissingError()
    pack = packs.activate(config.pack)
    params = stage_parameters(pack, config.optional_stages)
    if not params:
        raise PipelineError("This research area's stages have no parameters to check.")
    items = list(dict.fromkeys(items))
    if not config.is_local:                      # the cheap model, whatever profile the run itself uses
        config = replace(config, models={**config.models, "preparse": config.models.get("preparse", MODEL)},
                         model_profile="standard", batch_mode=False, passes=1)
    work_dir = Path(config.output_dir) / f"preparse_{datetime.now():%Y%m%d-%H%M%S}"
    work_dir.mkdir(parents=True, exist_ok=True)
    report = on_progress or (lambda *a: None)
    report(0, len(items), f"Checking {len(items)} paper(s) for {len(params)} parameters")
    papers: List[PaperRelevance] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items))), thread_name_prefix="preparse") as pool:
        futures = [pool.submit(check_paper, item, params, config, work_dir, cancel_event) for item in items]
        for f in as_completed(futures):
            p = f.result()
            papers.append(p)
            report(len(papers), len(items), f"{p.name}: " + (f"{len(p.reported)} of {len(params)} parameters"
                                                             if not p.error else f"not checked ({p.error})"))
    order = {str(i): n for n, i in enumerate(items)}
    papers.sort(key=lambda p: order.get(p.item, 0))
    return PreparseResult(papers=papers, parameters=[c for _, c, _, _ in params], work_dir=work_dir,
                          cost_usd=round(sum(p.cost_usd for p in papers), 4))
