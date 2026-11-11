"""
Full extraction for many papers (Mickey, 2026-10-27), built like the focused search (papers as PDFs
or arXiv IDs / DOIs / ADS bibcodes / reference links, from a list) but running the whole parser:

1. every paper is READ first (pipeline.read_paper: source, PDF parsed, table pages rendered, figures
   and equations found -- local, no API calls), one after another in a background thread (the PDF
   parser keeps one document open at a time), in list order;
2. each paper read goes straight on to its API extraction steps (pipeline.extract_steps), a few
   papers at a time -- so figure review can start with the first paper while the rest are read and
   extracted, and a paper's figure suggestions are ready once its structure has been planned;
3. when a paper's figures have been reviewed (or it has none) and its extraction is done, it can be
   FINISHED (pipeline.finish: rows, new-variable review, checks, files) -- the window does that at
   the end, one paper after another, so a variable the user accepts and remembers for one paper
   applies to the next;
4. a combined CSV of every paper's rows (full_ids made unique by giving each paper its own
   paper_prefix: 001..., 002..., ...), its observations and a papers.csv summary.

Each paper keeps its normal run folder, inside the queue's folder. No GUI code here: the window
(the main window, gui/multi_runs.py) and the command line (--queue) drive it.
"""
from __future__ import annotations
import csv
import dataclasses
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import PipelineError, RunCancelledError
from parameter_extractor.paper_source import PaperItem, run_name

DIRECT_PARALLEL, BATCH_PARALLEL = 3, 12      # papers extracted at once (direct calls / batch mode)


@dataclass
class QueuedPaper:
    item: PaperItem
    prefix: str                       # paper_prefix: full_ids '<prefix><set><sample>' unique across papers
    label: str = ""                   # what the list called it ('Tala Pinto et al. 2020'), else the run name
    status: str = "waiting"           # waiting, reading, extracting, extracted, finished, failed, cancelled
    step: str = ""                    # the latest progress message
    error: str = ""
    extraction: object = None         # pipeline.Extraction once read
    figures_reviewed: bool = False    # set by the window (or True when there are no figures)
    digitized: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    result: object = None             # pipeline.RunResult once finished
    extracted: threading.Event = field(default_factory=threading.Event)   # set when steps end (any way)
    resume_from: Optional[Path] = None   # its run folder in the queue being resumed (resume.py, W1)

    @property
    def figures(self) -> list:
        return list(getattr(self.extraction, "figures", []) or [])

    @property
    def ready_to_finish(self) -> bool:
        return self.status == "extracted" and (self.figures_reviewed or not self.figures)


WARMUP_MAX = 300          # s: the most the other papers wait for the first one's structure plan
_FIRST_LOCK = threading.Lock()


class PaperQueue:
    def __init__(self, items: Sequence[PaperItem], config: RunConfig,
                 on_change: Optional[Callable[[QueuedPaper], None]] = None,
                 cancel_event: Optional[threading.Event] = None, parallel: int = 0, digitize_by_hand: bool = True,
                 resume_from: Optional[Path] = None, rebuild: bool = False):
        """`resume_from`: an earlier queue's folder (resume / rebuild, W1): the papers are its papers (`items` is
        ignored), each reusing the answers saved in its old run folder; this queue still gets a new folder."""
        old_papers = []
        if resume_from is not None:
            from parameter_extractor.resume import queue_papers
            old_papers = queue_papers(Path(resume_from))
            items = [p["item"] for p in old_papers]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.out_dir = Path(config.output_dir) / f"queue_{stamp}"
        n = 2
        while self.out_dir.exists():
            self.out_dir, n = Path(config.output_dir) / f"queue_{stamp}_{n}", n + 1
        self.out_dir.mkdir(parents=True)
        self.config = config
        self.digitize_by_hand = digitize_by_hand    # False (run_queue): a paper with no rows skips its steps
        # a paper's supplementary information is read with it, not queued on its own (supplements.py)
        from parameter_extractor.ingestion.supplements import drop_supplements
        items, self.folded_supplements = drop_supplements(list(dict.fromkeys(items))) \
            if config.include_supplements else (list(dict.fromkeys(items)), [])
        self.papers = [QueuedPaper(item=item, prefix=f"{i:03d}", label=getattr(item, "label", "") or run_name(item))
                       for i, item in enumerate(items, start=1)]
        self.resume_from, self.rebuild = (Path(resume_from) if resume_from else None), rebuild
        for paper, old in zip(self.papers, old_papers):        # the same papers in the same order: same prefixes
            paper.prefix, paper.label, paper.resume_from = old["prefix"], old["label"] or paper.label, old["run_dir"]
        # the paper list, written first: a queue that stops part-way can be resumed from it
        (self.out_dir / "queue.json").write_text(json.dumps(
            {"papers": [{"prefix": p.prefix, "item": str(p.item), "label": p.label} for p in self.papers],
             "resumed_from": str(self.resume_from) if self.resume_from else None, "rebuild": rebuild},
            indent=2, ensure_ascii=False))
        self.on_change = on_change or (lambda paper: None)
        self.cancel_event = cancel_event or threading.Event()
        self.parallel = parallel or (BATCH_PARALLEL if config.batch_mode else DIRECT_PARALLEL)
        self._pool: Optional[ThreadPoolExecutor] = None
        self._reader: Optional[threading.Thread] = None
        self.reading_done = threading.Event()
        # the shared, cached prefix (tool list + every step's instructions, api_client.PaperContext) is written by
        # the first request that sends it; papers started together would each write it (measured 2026-11-07: 3 of
        # 5 did). So the first paper's extraction goes alone until its structure plan is back, then the rest
        # follow and read the prefix at 10%. Not in batch mode (requests wait in Anthropic's queue anyway).
        if config.shared_instructions is None:     # automatic: on for a queue (several papers share the prefix)
            config = dataclasses.replace(config, shared_instructions=True)
            self.config = config
        self._warm = (config.prompt_caching and config.shared_instructions and not config.batch_mode
                      and not config.handoff_dir)
        self._warmed = threading.Event()
        self._first: Optional[QueuedPaper] = None

    # ---- running --------------------------------------------------------------------------------
    def start(self) -> None:
        """Read the papers (in order, in the background) and extract each one as soon as it's read."""
        self._pool = ThreadPoolExecutor(max_workers=self.parallel, thread_name_prefix="queue")
        self._reader = threading.Thread(target=self._read_all, daemon=True, name="queue-reader")
        self._reader.start()

    def _config_for(self, paper: QueuedPaper) -> RunConfig:
        config = dataclasses.replace(self.config, paper_prefix=paper.prefix, output_dir=self.out_dir)
        if paper.resume_from is not None:           # that paper's own earlier settings, reusing its answers
            from parameter_extractor.resume import config_for
            config = config_for(paper.resume_from, config, self.rebuild)
            config.paper_prefix, config.output_dir = paper.prefix, self.out_dir
        return config

    def _set(self, paper: QueuedPaper, status: str = "", step: str = "", error: str = "") -> None:
        if status:
            paper.status = status
        if step:
            paper.step = step
        if error:
            paper.error = error
        self.on_change(paper)

    def _read_all(self) -> None:
        from parameter_extractor.pipeline import read_paper
        try:
            for paper in self.papers:
                if self.cancel_event.is_set():
                    self._set(paper, "cancelled")
                    paper.extracted.set()
                    continue
                self._set(paper, "reading", "Reading the paper")
                try:
                    paper.extraction = read_paper(paper.item, self._config_for(paper), cancel_event=self.cancel_event,
                                                  on_progress=lambda e, p=paper: self._set(p, step=e.message))
                except RunCancelledError:
                    self._set(paper, "cancelled")
                    paper.extracted.set()
                    continue
                except PipelineError as e:
                    self._set(paper, "failed", error=str(e))
                    paper.extracted.set()
                    continue
                except Exception as e:                   # one bad paper doesn't stop the others
                    self._set(paper, "failed", error=f"{type(e).__name__}: {e}")
                    paper.extracted.set()
                    continue
                if paper.resume_from is not None:     # figures digitized in the earlier run: not offered again
                    from parameter_extractor.resume import saved_figures
                    paper.digitized, paper.skipped = saved_figures(
                        paper.resume_from, paper.extraction.ctx.run_dir, [f.figure_id for f in paper.figures])
                    paper.figures_reviewed = paper.figures_reviewed or bool(paper.digitized) or self.rebuild
                if not paper.figures:
                    paper.figures_reviewed = True
                # no figure will become rows: a paper with no rows from tables or text skips its extraction steps
                paper.extraction.no_figure_rows = not paper.digitized and (not paper.figures or (
                    not self.digitize_by_hand and not self.config.auto_digitize_figures))
                self._set(paper, "extracting", "Waiting for its turn")
                self._pool.submit(self._extract, paper)
        finally:
            self.reading_done.set()
            self._pool.shutdown(wait=False)

    def _extract(self, paper: QueuedPaper) -> None:
        from parameter_extractor.pipeline import extract_steps
        first = False
        try:
            if self.cancel_event.is_set():
                raise RunCancelledError()
            if self._warm:
                with _FIRST_LOCK:
                    first = self._first is None
                    if first:
                        self._first = paper
                if first:                    # its structure plan back = the shared prefix is in the cache
                    ex = paper.extraction
                    threading.Thread(target=lambda: (ex.structure_ready.wait(WARMUP_MAX), self._warmed.set()),
                                     daemon=True).start()
                else:
                    self._set(paper, step="Waiting for the first paper's cached instructions")
                    while not self._warmed.wait(1.0):
                        if self.cancel_event.is_set():
                            raise RunCancelledError()
            paper.extraction.ctx.on_progress = lambda e, p=paper: self._set(p, step=e.message)
            extract_steps(paper.extraction)
            self._set(paper, "extracted", "Extracted -- waiting to be assembled")
        except RunCancelledError:
            self._set(paper, "cancelled")
        except PipelineError as e:
            self._set(paper, "failed", error=str(e))
        except Exception as e:
            self._set(paper, "failed", error=f"{type(e).__name__}: {e}")
        finally:
            if first:
                self._warmed.set()          # failed or done: never keep the others waiting
            paper.extracted.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Until every paper has been read and its extraction has ended (any way)."""
        if not self.reading_done.wait(timeout):
            return False
        return all(p.extracted.wait(timeout) for p in self.papers)

    @property
    def all_extracted(self) -> bool:
        return self.reading_done.is_set() and all(p.extracted.is_set() for p in self.papers)

    def cancel(self) -> None:
        self.cancel_event.set()

    # ---- finishing ------------------------------------------------------------------------------
    def finish_paper(self, paper: QueuedPaper, review=None):
        """Rows, review (review(groups, unfound_terms, registry) -> decisions, or None: nothing new is
        added) and files for one extracted paper. Its digitized figures become rows too."""
        from parameter_extractor.pipeline import finish
        if paper.resume_from is not None:               # variables decided in the earlier review: decided again
            from parameter_extractor.resume import review_with_saved
            review = review_with_saved(paper.resume_from, review)
        try:
            paper.result = finish(paper.extraction, paper.digitized, paper.skipped, review=review)
            self._set(paper, "finished", f"{len(paper.result.rows)} rows")
        except PipelineError as e:
            self._set(paper, "failed", error=str(e))
        return paper.result

    def write_combined(self) -> dict:
        """combined_extracted.csv (every finished paper's rows), combined_observations.csv and
        papers.csv in the queue's folder; returns their paths and counts."""
        from parameter_extractor.ingestion.flatten_to_template import write_csv
        from parameter_extractor.run_context import total_cost
        finished = [p for p in self.papers if p.result is not None]
        rows = [r for p in finished for r in p.result.rows]
        out = {"folder": self.out_dir, "papers": len(self.papers), "finished": len(finished), "rows": len(rows)}
        if rows:
            out["csv"] = self.out_dir / "combined_extracted.csv"
            # each paper's accepted columns keep the category they were accepted under
            chosen = {a["column"]: a.get("category", "") for p in finished for a in p.result.accepted_variables}
            from parameter_extractor.registry import VariableRegistry
            registry = VariableRegistry(self.config.registry_path, self.config.pack) \
                if self.config.registry_path else None          # compounds' active names, as in each paper's CSV
            write_csv(rows, out["csv"], column_categories=chosen, registry=registry)
            observations = [p.result.observations_path for p in finished if p.result.observations_path]
            if observations:
                out["observations"] = self.out_dir / "combined_observations.csv"
                with open(out["observations"], "w", encoding="utf-8") as f:
                    for i, path in enumerate(observations):
                        lines = Path(path).read_text(encoding="utf-8").splitlines(keepends=True)
                        f.writelines(lines if i == 0 else lines[1:])
        out["papers_csv"] = self.out_dir / "papers.csv"
        with open(out["papers_csv"], "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["prefix", "item", "label", "status", "rows", "flags", "figures_digitized", "cost_usd",
                        "run_folder", "error"])
            for p in self.papers:
                r = p.result
                w.writerow([p.prefix, str(p.item), p.label, p.status, len(r.rows) if r else "",
                            (len(r.paper_flags) + sum(len(x) for x in r.row_flags.values())) if r else "",
                            len(p.digitized), round(total_cost(r.usage) or 0, 4) if r else "",
                            str(r.run_dir) if r else (str(p.extraction.ctx.run_dir) if p.extraction else ""),
                            p.error])
        out["cost_usd"] = sum((total_cost(p.result.usage) or 0) for p in finished)
        (self.out_dir / "queue_summary.json").write_text(json.dumps(
            {k: str(v) if isinstance(v, Path) else v for k, v in out.items()}
            | {"config": self.config.to_public_dict()}, indent=2))
        return out


def run_queue(items: Sequence[PaperItem], config: RunConfig, on_change=None, cancel_event=None,
              parallel: int = 0, resume_from: Optional[Path] = None, rebuild: bool = False) -> PaperQueue:
    """The whole queue without a person: figures skipped, no new-variable review (new variables stay
    out of the CSV, listed in each paper's new_variables.json). For the command line."""
    queue = PaperQueue(items, config, on_change=on_change, cancel_event=cancel_event, parallel=parallel,
                       digitize_by_hand=False, resume_from=resume_from, rebuild=rebuild)
    queue.start()
    queue.wait()
    for paper in queue.papers:
        if paper.status == "extracted":
            if paper.digitized:                                         # from the run being resumed
                pass
            elif config.auto_digitize_figures and paper.figures:      # the easy figures, from their suggestions
                from parameter_extractor.pipeline import auto_digitize_figures
                paper.digitized, paper.skipped = auto_digitize_figures(paper.extraction)
            else:
                paper.skipped = [f.figure_id for f in paper.figures]
            paper.figures_reviewed = True
            queue.finish_paper(paper)
    queue.write_combined()
    return queue
