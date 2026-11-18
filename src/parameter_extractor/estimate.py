"""
The cost and time of a run, estimated before it starts (W4, Mickey 2026-11-18): "about $0.15–0.40 and 4–8 minutes
for this paper", next to the Run button and on the command line. Local, free, no request.

What a run asks: the row plan and the paper details always; the pack's built-in steps; its configurable steps that
always run, and those whose trigger words the paper has (steps triggered only by what the row plan finds -- a kind of
set -- are 'maybe': they widen the range); a figure suggestion per figure when figures are digitized automatically;
everything that votes times the passes. Each request is priced with the model the run's profile gives that step
(pricing.py, the profile's own prices, batch half price) from the tokens such requests took in earlier runs
(estimate_data.json, built by scripts/build_estimate_data.py: uncached input, cache writes and reads, output at the
20th / 50th / 80th percentile). The paper is read for its text (keyword triggers) and its figure count when it is a
PDF on this computer; an arXiv ID or DOI counts as a typical paper.

Time: three waits at most -- the row plan, the steps (at once), the figure suggestions (at once) -- each the slowest
request's time in earlier runs (batch mode: the queue wait, about 2 minutes); papers of a queue run 12 at once in batch
mode, 3 otherwise. A local server: the recorded speeds don't apply; the estimate says so.

The range comes from the spread of earlier requests and was checked against the recorded runs
(scripts/check_estimates.py); it is an estimate, and says so.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

DATA = Path(__file__).with_name("estimate_data.json")
# the spread of whole papers beyond the spread of single requests (scripts/check_estimates.py, 2026-11-18)
LOW_FACTOR, HIGH_FACTOR = 1.0, 1.1
SETUP_SECONDS = (15, 60)            # reading the paper, its tables and figures; assembling the rows
FIGURE_CAPTION = re.compile(r"(?m)^\s*(?:Fig\.?|Figure|FIG\.?|FIGURE)\s*(S?\d+)")


@lru_cache(maxsize=1)
def _data() -> dict:
    try:
        return json.loads(DATA.read_text())
    except (OSError, ValueError):
        return {"steps": {}, "figures_per_paper": {"low": 1, "median": 4, "high": 6}}


@dataclass
class PaperInfo:
    text: Optional[str] = None      # None: not read (not a local PDF, or unreadable)
    figures: Optional[int] = None


def read_paper(item) -> PaperInfo:
    """A local PDF's text and figure count, quickly (pypdfium2's text, captions by their first words); anything
    else counts as a typical paper."""
    path = Path(str(item)).expanduser()
    if path.suffix.lower() != ".pdf" or not path.is_file():
        return PaperInfo()
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        try:
            text = "\n".join(page.get_textpage().get_text_range() for page in pdf)
        finally:
            pdf.close()
    except Exception:                                 # noqa: BLE001 -- an estimate never stops a run
        return PaperInfo()
    if len(text.strip()) < 500:                       # a scan: read by text recognition during the run
        return PaperInfo()
    return PaperInfo(text=text, figures=len(set(FIGURE_CAPTION.findall(text))))


def planned_steps(config, text: Optional[str]) -> Tuple[List[str], List[str]]:
    """(steps the run makes, steps it may make) for one paper -- the pipeline's own choices (extract_steps),
    decided before the row plan exists."""
    from parameter_extractor import packs
    from parameter_extractor.pipeline import _chemistry_on
    from parameter_extractor.stages.optional import load_specs
    pack = packs.current()
    sure, maybe = ["structure_planner", "metadata"], []
    if pack.uses("methodology"):
        sure.append("methodology")
    if _chemistry_on(pack, config):
        sure.append("chemistry")
    for name in ("fit_models", "analysis"):
        if pack.uses(name) and config.optional_stages.get(name, "auto") != "off":
            sure.append(name)
    if any(t.strip() for t in config.focus_terms):
        sure.append("term_search")
    for name, spec in load_specs().items():
        choice = config.optional_stages.get(name, "auto")
        if choice == "off" or not spec.parameters:
            continue
        t = spec.trigger
        if choice == "on" or t.always or (text is not None and t.keywords
                                          and spec.keyword_hits(text) >= max(1, t.min_hits)):
            sure.append(name)
        elif text is None or spec.could_trigger(text):
            maybe.append(name)
    return sure, maybe


ASKED_ONCE = {"structure_planner", "metadata", "methodology", "fit_models", "analysis", "term_search"}


def _asked(step: str, passes: int) -> int:
    """Requests a step makes: chemistry and the configurable steps are asked once per pass (a vote)."""
    return 1 if step in ASKED_ONCE else passes


def _row(step: str) -> dict:
    steps = _data()["steps"]
    return steps.get(step) or steps.get("_configurable") or {}


def step_cost(config, step: str, output: str = "output") -> Optional[float]:
    """One request of this step at its recorded tokens (output: 'output_low' / 'output' / 'output_high'), priced
    for the run's model and mode; None when the model's price isn't known."""
    from parameter_extractor.pricing import request_cost
    row = _row(step)
    if not row:
        return None
    if config.is_local and (config.local or {}).get("private"):
        return 0.0                                    # a server on this computer or network: no charges
    try:
        model = config.model_for(step)
    except Exception:                                 # noqa: BLE001 -- a profile without a model for it
        return None
    if config.is_local:
        return request_cost(model, row.get("input", 0) + row.get("cache_read", 0) + row.get("cache_write", 0),
                            row.get(output, 0), prices=config.prices) if config.prices else None
    return request_cost(model, row.get("input", 0), row.get(output, 0), cache_write_tokens=row.get("cache_write", 0),
                        cache_read_tokens=row.get("cache_read", 0), batch=config.batch_mode, prices=config.prices)


def _seconds(config, step: str, high: bool) -> float:
    row = _row(step)
    if config.batch_mode and not config.is_local:
        return row.get("batch_seconds_high" if high else "batch_seconds", 130)
    return row.get("seconds_high" if high else "seconds", 30)


@dataclass
class Estimate:
    papers: int = 0
    cost_low: Optional[float] = None
    cost_high: Optional[float] = None
    minutes_low: float = 0.0
    minutes_high: float = 0.0
    notes: List[str] = field(default_factory=list)

    @property
    def cost_known(self) -> bool:
        return self.cost_low is not None

    def text(self) -> str:
        """'About $0.15–0.40 and 4–8 minutes for this paper (estimate)'."""
        what = "this paper" if self.papers == 1 else f"these {self.papers} papers"
        if not self.cost_known:
            cost = "an unknown cost (no prices for this model)"
        elif self.cost_high == 0:
            cost = "no charge"
        else:
            cost = _money_range(self.cost_low, self.cost_high)
        return f"About {cost} and {_minutes_range(self.minutes_low, self.minutes_high)} for {what} (estimate)"


def _money_range(low: float, high: float) -> str:
    def fmt(v):
        return f"{v:.2f}" if v < 10 else f"{v:.0f}"
    if high < 0.01:
        return "less than $0.01"
    return f"${fmt(low)}–{fmt(high)}"


def _minutes_range(low: float, high: float) -> str:
    lo, hi = max(1, math.floor(low)), max(1, math.ceil(high))
    if hi >= 120:
        return f"{lo / 60:.1f}–{hi / 60:.1f} hours".replace(".0", "")
    return f"{lo} minute" if lo == hi == 1 else f"{lo}–{hi} minutes" if lo != hi else f"about {lo} minutes"


def estimate(config, items: Sequence, figure_suggestions: Optional[bool] = None,
             papers: Optional[List[PaperInfo]] = None) -> Estimate:
    """The estimate for running `items` (PDFs, arXiv IDs, DOIs) with `config` and the active data pack.
    `figure_suggestions`: a suggestion is asked for every figure (default: RunConfig.auto_digitize_figures).
    `papers`: their PaperInfo when already read (read_paper otherwise)."""
    from parameter_extractor import packs
    items = list(items)
    est = Estimate(papers=len(items))
    if not items:
        return est
    packs.activate(config.pack)                       # the run's pack decides its steps (as pipeline._start does)
    if figure_suggestions is None:
        figure_suggestions = bool(config.auto_digitize_figures)
    papers = papers if papers is not None else [read_paper(i) for i in items]
    passes = 1 if config.handoff_dir else max(1, min(3, config.passes or 1))
    typical = _data()["figures_per_paper"]
    low = high = 0.0
    known = True
    slow = fast = 0.0                                 # one paper's minutes (the slowest of its waits)
    for info in papers:
        sure, maybe = planned_steps(config, info.text)
        if figure_suggestions:
            n_low = info.figures if info.figures is not None else typical["low"]
            n_high = info.figures if info.figures is not None else typical["high"]
        else:
            n_low = n_high = 0
        for s in sure + maybe:                        # a 'maybe' step counts only towards the high end
            c_lo, c_hi = step_cost(config, s, "output_low"), step_cost(config, s, "output_high")
            if c_lo is None or c_hi is None:
                known = False
                continue
            if s in sure:
                low += c_lo * _asked(s, passes)
            high += c_hi * _asked(s, passes)
        f_lo, f_hi = step_cost(config, "figure_planner", "output_low"), step_cost(config, "figure_planner",
                                                                                  "output_high")
        if n_high:
            if f_lo is None or f_hi is None:
                known = False
            else:
                low += f_lo * n_low
                high += f_hi * n_high
        # time: the row plan, then every step at once, then the figure suggestions at once
        parallel = max(1, config.max_parallel_stages or 6)
        steps = [s for s in sure + maybe if s not in ("structure_planner", "metadata")]
        waits_fast = [_seconds(config, "structure_planner", False),
                      max([_seconds(config, s, False) for s in steps] or [0])]
        waits_slow = [_seconds(config, "structure_planner", True),
                      max([_seconds(config, s, True) for s in steps] or [0])]
        if n_high:
            rounds = 1 if config.batch_mode else math.ceil(n_high / parallel)
            waits_fast.append(_seconds(config, "figure_planner", False) * (1 if config.batch_mode else
                                                                            math.ceil(max(n_low, 1) / parallel)))
            waits_slow.append(_seconds(config, "figure_planner", True) * rounds)
        fast = max(fast, (sum(waits_fast) + SETUP_SECONDS[0]) / 60)
        slow = max(slow, (sum(waits_slow) + SETUP_SECONDS[1]) / 60)
    if known:
        est.cost_low, est.cost_high = low * LOW_FACTOR, high * HIGH_FACTOR
    at_once = 12 if config.batch_mode and not config.is_local else 3
    rounds = math.ceil(len(items) / at_once)
    est.minutes_low, est.minutes_high = fast * rounds, slow * rounds
    unread = sum(1 for p in papers if p.text is None)
    if unread:
        est.notes.append(f"{unread} paper(s) not read beforehand (not a PDF on this computer, or a scan): counted as "
                         f"a typical paper")
    if not figure_suggestions:
        f = step_cost(config, "figure_planner")
        if f is not None and f > 0:
            est.notes.append(f"figure suggestions you ask for while digitizing: about ${f:.2f} each")
    if config.is_local:
        est.notes.append("a local server's speed isn't known from earlier runs: the time is a rough guess; local runs "
                         "often take 10–30 minutes a paper")
        est.minutes_high = max(est.minutes_high, 30.0 * len(items) / at_once)
    return est
