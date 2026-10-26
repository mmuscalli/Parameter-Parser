"""
Offline tests for the full-extraction paper queue (paper_queue.py): papers read first (figures available
for review at once), extracted in parallel, finished one by one, a combined CSV with full_ids unique
across papers; a failing paper doesn't stop the others; cancelling. Replays recorded answers (eder1994,
truman2024); no API calls.

Run with: python tests/test_paper_queue.py
"""
import csv
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.paper_queue import PaperQueue, run_queue
from test_pipeline_offline import PDF as EDER, make_replay

TRUMAN = ROOT.parent / "Paper Files" / "Paper Lists" / "Initial Easy Papers" / "Truman2024" / "truman2024.pdf"
REPLAYS = {"eder1994": make_replay(ROOT / "runs" / "eder1994_auto"),
           "truman2024": make_replay(ROOT / "runs" / "truman2024_auto")}


def routed_send(ctx, **kw):
    """Each paper's recorded answers, by its run folder."""
    name = next(n for n in REPLAYS if Path(ctx.run_dir).name.startswith(n))
    return REPLAYS[name](ctx, **kw)


def test_queue_reads_extracts_and_combines():
    if not (EDER.is_file() and TRUMAN.is_file()):
        print("SKIP: needs eder1994.pdf and truman2024.pdf"); return
    events = []
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", routed_send):
        cfg = RunConfig.from_settings(api_key="x", output_dir=Path(tmp))
        queue = PaperQueue([EDER, Path(tmp) / "missing.pdf", TRUMAN], cfg,
                           on_change=lambda p: events.append((p.prefix, p.status)))
        queue.start()
        assert queue.wait(300)
        eder, missing, truman = queue.papers
        assert [p.prefix for p in queue.papers] == ["001", "002", "003"]
        assert missing.status == "failed" and "not found" in missing.error
        assert eder.status == truman.status == "extracted"
        assert ("001", "reading") in events and ("001", "extracting") in events
        assert len(eder.figures) == 5 and not eder.ready_to_finish          # figures await review
        eder.skipped, eder.figures_reviewed = [f.figure_id for f in eder.figures], True
        truman.figures_reviewed = True
        assert eder.ready_to_finish and truman.ready_to_finish
        for p in (eder, truman):
            queue.finish_paper(p)
        assert eder.status == truman.status == "finished"
        assert eder.result.run_dir.parent == queue.out_dir                    # run folders inside the queue's
        out = queue.write_combined()
        rows = list(csv.DictReader(open(out["csv"])))
        assert out["finished"] == 2 and len(rows) == len(eder.result.rows) + len(truman.result.rows)
        ids = [r["full_id"] for r in rows]
        assert len(set(ids)) == len(ids) and ids[0].startswith("001") and ids[-1].startswith("003")
        papers = list(csv.DictReader(open(out["papers_csv"])))
        assert [p["status"] for p in papers] == ["finished", "failed", "finished"]
        assert out["observations"].read_text().count("full_id,") == 1          # one header


def test_queue_without_a_person_and_cancelling():
    if not EDER.is_file():
        print("SKIP: needs eder1994.pdf"); return
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", routed_send):
        cfg = RunConfig.from_settings(api_key="x", output_dir=Path(tmp))
        queue = run_queue([EDER], cfg)                                       # command line: no reviews
        [paper] = queue.papers
        assert paper.status == "finished" and len(paper.result.rows) == 42
        assert len(paper.skipped) == 5                                       # figures skipped, not lost
        assert (queue.out_dir / "combined_extracted.csv").is_file()
        cancel = threading.Event()
        cancel.set()
        stopped = PaperQueue([EDER, EDER.with_name("x.pdf")], cfg, cancel_event=cancel)
        stopped.start()
        assert stopped.wait(60) and {p.status for p in stopped.papers} == {"cancelled"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All paper-queue tests passed.")
