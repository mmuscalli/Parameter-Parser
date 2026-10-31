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
(gui/queue_window.py) and the command line (--queue) drive it.
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

    @property
    def figures(self) -> list:
        return list(getattr(self.extraction, "figures", []) or [])

    @property
    def ready_to_finish(self) -> bool:
        return self.status == "extracted" and (self.figures_reviewed or not self.figures)


class PaperQueue:
    def __init__(self, items: Sequence[PaperItem], config: RunConfig,
                 on_change: Optional[Callable[[QueuedPaper], None]] = None,
                 cancel_event: Optional[threading.Event] = None, parallel: int = 0):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.out_dir = Path(config.output_dir) / f"queue_{stamp}"
        n = 2
        while self.out_dir.exists():
            self.out_dir, n = Path(config.output_dir) / f"queue_{stamp}_{n}", n + 1
        self.out_dir.mkdir(parents=True)
        self.config = config
        # a paper's supplementary information is read with it, not queued on its own (supplements.py)
        from parameter_extractor.ingestion.supplements import drop_supplements
        items, self.folded_supplements = drop_supplements(list(dict.fromkeys(items))) \
            if config.include_supplements else (list(dict.fromkeys(items)), [])
        self.papers = [QueuedPaper(item=item, prefix=f"{i:03d}", label=getattr(item, "label", "") or run_name(item))
                       for i, item in enumerate(items, start=1)]
        self.on_change = on_change or (lambda paper: None)
        self.cancel_event = cancel_event or threading.Event()
        self.parallel = parallel or (BATCH_PARALLEL if config.batch_mode else DIRECT_PARALLEL)
        self._pool: Optional[ThreadPoolExecutor] = None
        self._reader: Optional[threading.Thread] = None
        self.reading_done = threading.Event()

    # ---- running --------------------------------------------------------------------------------
    def start(self) -> None:
        """Read the papers (in order, in the background) and extract each one as soon as it's read."""
        self._pool = ThreadPoolExecutor(max_workers=self.parallel, thread_name_prefix="queue")
        self._reader = threading.Thread(target=self._read_all, daemon=True, name="queue-reader")
        self._reader.start()

    def _config_for(self, paper: QueuedPaper) -> RunConfig:
        return dataclasses.replace(self.config, paper_prefix=paper.prefix, output_dir=self.out_dir)

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
                if not paper.figures:
                    paper.figures_reviewed = True
                self._set(paper, "extracting", "Waiting for its turn")
                self._pool.submit(self._extract, paper)
        finally:
            self.reading_done.set()
            self._pool.shutdown(wait=False)

    def _extract(self, paper: QueuedPaper) -> None:
        from parameter_extractor.pipeline import extract_steps
        try:
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
            write_csv(rows, out["csv"])
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
              parallel: int = 0) -> PaperQueue:
    """The whole queue without a person: figures skipped, no new-variable review (new variables stay
    out of the CSV, listed in each paper's new_variables.json). For the command line."""
    queue = PaperQueue(items, config, on_change=on_change, cancel_event=cancel_event, parallel=parallel)
    queue.start()
    queue.wait()
    for paper in queue.papers:
        if paper.status == "extracted":
            paper.skipped = [f.figure_id for f in paper.figures]
            paper.figures_reviewed = True
            queue.finish_paper(paper)
    queue.write_combined()
    return queue
