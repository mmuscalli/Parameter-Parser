"""
Turn a finished live run into a reference run (runs/reference/<name>/) that tests/test_reference_runs.py
replays for free after every change: the model's recorded answers (<step>.output.json / .audit.json),
what was read (reference.json; for a paper read from arXiv, a cache seed with its arXiv record and text,
so the replay needs no network), the archive rows for exoplanet runs, and the expected outputs --
written by replaying the answers through the current code (without the local variable registry, so the
reference doesn't depend on this computer's accepted variables).

    python scripts/record_reference.py RUN_DIR NAME --pdf "Paper Lists/.../x.pdf"      (relative to Paper Files)
    python scripts/record_reference.py RUN_DIR NAME --arxiv 2601.10450 --pack exoplanets

Check the run's values against the paper BEFORE recording it: a reference freezes what it says.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
PAPERS = ROOT.parent / "Paper Files"
REFERENCES = ROOT / "runs" / "reference"


def record(run_dir: Path, name: str, pdf: str = "", arxiv: str = "", pack: str = "prebiotic_chemistry") -> Path:
    from test_reference_runs import replay_reference
    run_dir, ref = Path(run_dir), REFERENCES / name
    if ref.exists():
        shutil.rmtree(ref)
    ref.mkdir(parents=True)
    for f in run_dir.glob("*.json"):
        if f.name.endswith((".output.json", ".audit.json")) or f.name in ("archive_rows.json", "source.json"):
            shutil.copy(f, ref / f.name)
    summary = json.loads((run_dir / "run_summary.json").read_text())
    manifest = {"name": name, "pack": pack, "pdf": pdf, "arxiv": arxiv,
                "online_checks": (run_dir / "archive_rows.json").is_file(),
                "recorded": str(date.today()), "recorded_from": str(run_dir),
                "model_profile": summary["config"].get("model_profile"),
                "models": sorted({u["model"] for u in summary["usage"]}),
                "cost_usd": round(summary.get("estimated_cost_usd") or 0, 4)}
    if arxiv:                                            # seed for an offline replay
        from parameter_extractor.ingestion.arxiv_source import ArxivRecord, LookupCache
        source = json.loads((run_dir / "source.json").read_text())
        record = ArxivRecord(**source["arxiv"])
        from parameter_extractor.registry import default_arxiv_cache_dir
        text = LookupCache(default_arxiv_cache_dir()).text(record)
        if not text:
            raise SystemExit(f"{record.label}: its text isn't in the arXiv cache -- run it with the app's cache on")
        seed = LookupCache(ref / "arxiv_cache")
        seed.put(f"arXiv:{arxiv}", record)
        seed.save()
        seed.put_text(record, text)
    (ref / "reference.json").write_text(json.dumps(manifest, indent=2))
    result = replay_reference(ref, out=ref / "_replay")
    for f in (result.csv_path, result.observations_path, result.run_dir / "archive_validation.json"):
        if f and f.is_file():
            shutil.copy(f, ref / ("expected_" + f.name.rsplit("_", 1)[-1] if f.suffix == ".csv" else f.name))
    shutil.rmtree(ref / "_replay")
    print(f"{name}: {len(result.rows)} rows -> {ref}")
    return ref


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("run_dir", type=Path)
    a.add_argument("name")
    a.add_argument("--pdf", default="", help="the PDF, relative to the 'Paper Files' folder")
    a.add_argument("--arxiv", default="", help="the arXiv ID the run read")
    a.add_argument("--pack", default="prebiotic_chemistry")
    args = a.parse_args()
    record(args.run_dir, args.name, args.pdf, args.arxiv, args.pack)
