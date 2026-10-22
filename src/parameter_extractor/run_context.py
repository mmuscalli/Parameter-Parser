"""
Per-run state handed to every stage: the config, the run's output folder,
progress reporting, cancellation, and a log of API usage.

Progress and cancellation are what a GUI needs from a run that takes a couple
of minutes: the pipeline calls `ctx.step(...)` before each stage, which
reports progress through the `on_progress` callback and raises
RunCancelledError if the user has pressed cancel. Cancellation takes effect
between stages -- an API call already in flight finishes first.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import ApiKeyMissingError, RunCancelledError


@dataclass
class ProgressEvent:
    step: int          # 1-based index of the current step
    total_steps: int
    stage: str         # machine name, e.g. "chemistry"
    message: str       # human-readable, e.g. "Extracting solution chemistry"


@dataclass
class StageUsage:
    stage: str
    model: str
    input_tokens: int
    output_tokens: int
    elapsed_sec: float
    cost_usd: Optional[float] = None      # estimate from pricing.py; None = model price unknown
    # prompt caching (api_client): the paper's text and table images, written once per run and
    # read by the later steps; `input_tokens` counts only the rest
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        """All input tokens of the request, cached or not."""
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens


def total_cost(usage) -> Optional[float]:
    """Sum of the estimated costs, or None if any request's price is unknown."""
    costs = [u.cost_usd for u in usage]
    return None if any(c is None for c in costs) else sum(costs)


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class RunContext:
    config: RunConfig
    run_dir: Path
    total_steps: int
    on_progress: Optional[ProgressCallback] = None
    cancel_event: Optional[threading.Event] = None
    usage: List[StageUsage] = field(default_factory=list)
    # the paper as every paper-reading step sees it (text + table images), sent first and cached
    paper: Optional["PaperContext"] = None
    _step: int = 0
    _client: object = None
    # stages run in parallel (pipeline.extract): progress, usage and the client are shared
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def step(self, stage: str, message: str) -> None:
        """Mark the start (or, for parallel stages, the end) of the next step: check for
        cancellation, then report it."""
        self.check_cancelled()
        with self._lock:
            self._step += 1
            event = ProgressEvent(self._step, self.total_steps, stage, message)
        if self.on_progress:
            self.on_progress(event)

    def note(self, stage: str, message: str) -> None:
        """Report what's happening without advancing the step count."""
        if self.on_progress:
            self.on_progress(ProgressEvent(self._step, self.total_steps, stage, message))

    def record_usage(self, usage: StageUsage) -> None:
        with self._lock:
            self.usage.append(usage)

    def sort_usage(self, order: List[str]) -> None:
        """Usage in a fixed stage order (parallel stages finish in any order)."""
        rank = {s: i for i, s in enumerate(order)}
        with self._lock:
            self.usage.sort(key=lambda u: rank.get(u.stage, len(order)))

    def check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RunCancelledError()

    @property
    def client(self):
        """One Anthropic client per run, built from the run's own key."""
        with self._lock:
            if self._client is None:
                if not self.config.api_key:
                    raise ApiKeyMissingError()
                import anthropic  # lazy: parsing/flattening work without the SDK installed
                # parallel stages can briefly exceed a key's per-minute token limit: the SDK
                # waits and retries a rate-limited request (honouring retry-after)
                self._client = anthropic.Anthropic(api_key=self.config.api_key, max_retries=5)
            return self._client
