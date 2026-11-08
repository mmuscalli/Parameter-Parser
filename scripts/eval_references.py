"""
Live runs of the reference papers (runs/reference/<name>/) scored against their expected CSVs -- the measure for
changes to accuracy or cost (2026-11-07: local table reading; method of the 2026-11-03 model comparison).

    python scripts/eval_references.py --out DIR [--models standard] [--only eder1994 kim2017] [--src PATH]
    python scripts/eval_references.py --score DIR          # score runs already in DIR, no API calls

Live runs cost money (Standard ~$0.15-0.45 per paper). Settings as recorded in each reference.json (pack, online
checks), no PubChem, no remembered variables (registry None) -- like the expected files, which were written by
replay. `--src` runs another checkout's code (e.g. a git worktree of an earlier commit, for a baseline).

Accuracy = share of the reference's filled cells (row ids, paper metadata and provenance left out) the run
reproduces on the matching row (rows paired by content): numbers within 1 %, text equal ignoring case and spacing; free-text columns
(wording varies between runs of the same model) count when filled. Columns the reference lacks are not scored.
"""
import argparse
import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "runs" / "reference"
PAPERS = ROOT.parent / "Paper Files"

NOT_SCORED = {"entry_number", "full_id", "set_id", "sample_id", "paper_title", "paper_DOI", "author_list",
              "year_published", "journal_published", "paper_arxiv_id", "source_notes", "extraction_confidence",
              "yield_below_threshold_note", "data_location", "original_data_reference"}
FREE_TEXT = {"analysis_method", "vessel_material", "solvent_name", "headspace_gas_name", "solid_material_name",
             "solid_material_type", "positive_control", "negative_control", "reagent_suppliers",
             "stirring_agitation", "pH_buffer"}


def _number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _same(ref: str, got: str, column: str) -> bool:
    if got in (None, ""):
        return False
    if column in FREE_TEXT or column.endswith(("desc", "method", "jointdesc", "assump", "priors", "software")) \
            or len(ref) > 40:
        return True                                  # filled is what counts
    a, b = _number(ref), _number(got)
    if a is not None and b is not None:
        return abs(a - b) <= 0.01 * max(abs(a), abs(b)) or abs(a - b) < 1e-12
    return " ".join(ref.lower().split()) == " ".join(str(got).lower().split())


def _cells(row: dict) -> dict:
    return {c: v for c, v in row.items() if c not in NOT_SCORED and v not in (None, "")}


def score(expected_csv: Path, got_csv: Path) -> dict:
    """Rows are paired by content, not id: each reference row with the run's row that reproduces most of its cells
    (greedy, best pairs first) -- a plan with one extra row would otherwise shift every id after it."""
    ref = list(csv.DictReader(open(expected_csv)))
    got = list(csv.DictReader(open(got_csv))) if got_csv and got_csv.is_file() else []
    pairs = []
    for i, r in enumerate(ref):
        cells = _cells(r)
        for j, g in enumerate(got):
            pairs.append((sum(1 for c, v in cells.items() if _same(v, g.get(c), c)), i, j))
    pairs.sort(reverse=True)
    match, used = {}, set()
    for n, i, j in pairs:
        if i not in match and j not in used:
            match[i] = j
            used.add(j)
    total = hit = 0
    misses = []
    for i, r in enumerate(ref):
        g = got[match[i]] if i in match else {}
        for col, v in _cells(r).items():
            total += 1
            if _same(v, g.get(col), col):
                hit += 1
            else:
                misses.append((r["full_id"], col, v, g.get(col)))
    return {"rows_ref": len(ref), "rows_got": len(got), "cells": total, "matched": hit,
            "accuracy": hit / total if total else 0.0, "misses": misses}


def usage(run_dir: Path) -> dict:
    s = json.loads((run_dir / "run_summary.json").read_text())
    stages = {}
    for u in s.get("usage", []):
        d = stages.setdefault(u["stage"], {"in": 0, "cache_read": 0, "cache_write": 0, "out": 0, "cost": 0.0})
        d["in"] += u.get("input_tokens", 0) or 0
        d["cache_read"] += u.get("cache_read_tokens", 0) or 0
        d["cache_write"] += u.get("cache_write_tokens", 0) or u.get("cache_creation_tokens", 0) or 0
        d["out"] += u.get("output_tokens", 0) or 0
        d["cost"] += u.get("cost_usd", 0) or 0
    return stages


def live(ref: Path, out: Path, models: str):
    from parameter_extractor import packs
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.pipeline import run_pipeline
    m = json.loads((ref / "reference.json").read_text())
    cfg = dict(output_dir=out, pack=m["pack"], online_checks=m["online_checks"], use_pubchem=False,
               registry_path=None, model_profile=models)
    tmp = None
    if m.get("arxiv"):
        tmp = tempfile.mkdtemp()
        shutil.copytree(ref / "arxiv_cache", Path(tmp) / "cache")
        cfg["arxiv_cache_dir"] = Path(tmp) / "cache"
        item = f"arXiv:{m['arxiv']}"
    else:
        item = PAPERS / m["pdf"]
    try:
        return run_pipeline(item, RunConfig.from_settings(**cfg))
    finally:
        packs.activate("prebiotic_chemistry")
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def report(rows):
    print(f"\n{'paper':22s} {'rows':>9s} {'accuracy':>9s} {'cost':>8s} {'out tok':>8s}  per step (out tokens / $)")
    for name, sc, st in rows:
        cost = sum(d["cost"] for d in st.values())
        out = sum(d["out"] for d in st.values())
        steps = ", ".join(f"{k} {d['out']}/{d['cost']:.3f}" for k, d in st.items())
        print(f"{name:22s} {sc['rows_got']:>4d}/{sc['rows_ref']:<4d} {sc['accuracy']:>8.1%} {cost:>8.4f} {out:>8d}  {steps}")
    if rows:
        print(f"{'mean':22s} {'':9s} {sum(r[1]['accuracy'] for r in rows) / len(rows):>8.1%} "
              f"{sum(sum(d['cost'] for d in r[2].values()) for r in rows) / len(rows):>8.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--score", type=Path, help="score the run folders already in this directory")
    ap.add_argument("--models", default="standard")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--src", type=Path, help="run this checkout's src/ instead")
    ap.add_argument("--misses", action="store_true", help="list every missed cell")
    a = ap.parse_args()
    sys.path.insert(0, str(a.src or ROOT / "src"))
    refs = sorted(p for p in REFERENCES.iterdir() if (p / "reference.json").is_file()
                  and (not a.only or p.name in a.only))
    rows = []
    for ref in refs:
        if a.score:
            m = json.loads((ref / "reference.json").read_text())
            stem = f"arXiv_{m['arxiv']}" if m.get("arxiv") else Path(m["pdf"]).stem
            dirs = sorted(d for d in a.score.iterdir() if d.is_dir() and d.name.startswith(stem + "_"))
            if not dirs:
                continue
            run_dir = dirs[-1]
        else:
            a.out.mkdir(parents=True, exist_ok=True)
            result = live(ref, a.out, a.models)
            run_dir = result.run_dir
            print(f"{ref.name}: {run_dir.name}", flush=True)
        got = next(run_dir.glob("*_extracted.csv"), None)
        sc = score(ref / "expected_extracted.csv", got)
        rows.append((ref.name, sc, usage(run_dir)))
        if a.misses:
            for fid, col, v, g in sc["misses"]:
                print(f"   miss {ref.name} {fid} {col}: expected {v!r}, got {g!r}")
    report(rows)


if __name__ == "__main__":
    main()
