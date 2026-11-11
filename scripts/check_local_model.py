"""
Runs a reference paper on a local model server and compares the result with the reference (W6, 2026-11-11; replaces
the one-off scripts in runs/local_models/). The checklist in docs/local_model_notes.md uses it.

    python scripts/check_local_model.py qwen3.8:27b                          # eder1994, context 131072
    python scripts/check_local_model.py gemma4:31b --context 81920 --paper teng2023
    python scripts/check_local_model.py --score RUN_DIR                      # compare a finished run, no server

Papers:
  eder1994  prebiotic pack (~5-7 min on a 27B model): scored against runs/reference/eder1994/expected_extracted.csv
            (share of the reference's cells reproduced, as scripts/eval_references.py --score).
  teng2023  exoplanets (~35 min): the archive check runs against the archive snapshot saved with the Claude run
            (runs/teng2023_auto/archive_rows.json), so no network is needed; prints matches / differs / missing.

The server address and kind come from the app's own local model settings (Settings > Model provider), unless --url /
--kind are given. One model does every step. No PubChem, no remembered variables (like the references). Output goes to
runs/local_models/ (local, never pushed) unless --out says otherwise. Runs cost nothing, but need the server running.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("PARAMETER_EXTRACTOR_NO_KEYCHAIN", "1")

PAPERS_DIR = ROOT.parent / "Paper Files"
PAPERS = {
    "eder1994": {"pack": "prebiotic_chemistry", "pdf": PAPERS_DIR / "Paper Lists/Initial Easy Papers/Eder1994/eder1994.pdf",
                 "online_checks": False},
    "teng2023": {"pack": "exoplanets", "pdf": PAPERS_DIR / "Paper Lists/Teng2023/teng2023.pdf", "online_checks": True},
}
EXPECTED_EDER = ROOT / "runs" / "reference" / "eder1994" / "expected_extracted.csv"
ARCHIVE_SNAPSHOT = ROOT / "runs" / "teng2023_auto" / "archive_rows.json"


def archive_totals(validation_json: Path) -> Counter:
    """Totals of an archive_validation.json, split by whether the row is the solution the archive took."""
    c = Counter()
    for r in json.loads(validation_json.read_text()):
        if r.get("status") != "compared":
            c["rows not compared"] += 1
            continue
        side = "other-solution rows" if r.get("archive_solution") else "adopted rows"
        c[side] += 1
        for k in ("matches", "differs", "minor", "not_extracted"):
            v = r.get(k)
            c[f"{side}: {k}"] += len(v) if isinstance(v, (list, dict)) else (v or 0)
    return c


def _steps(run_dir: Path) -> str:
    s = json.loads((run_dir / "run_summary.json").read_text())
    lines = [f"  {'step':28} {'in':>8} {'out':>7} {'seconds':>8}"]
    for u in s.get("usage", []):
        lines.append(f"  {u['stage']:28} {u.get('input_tokens', 0):8,} {u.get('output_tokens', 0):7,} "
                     f"{u.get('elapsed_sec', 0):8.0f}")
    lines.append(f"  {'total':28} {s.get('input_tokens', 0):8,} {s.get('output_tokens', 0):7,}")
    try:
        took = datetime.fromisoformat(s["finished"]) - datetime.fromisoformat(s["started"])
        lines.append(f"  whole paper: {took.total_seconds() / 60:.1f} min")
    except (KeyError, ValueError, TypeError):
        pass
    return "\n".join(lines)


def compare(run_dir: Path) -> None:
    """Print the step table and the comparison with the reference for a finished run folder."""
    run_dir = Path(run_dir)
    print(f"\n{run_dir}\n{_steps(run_dir)}\n")
    validation = run_dir / "archive_validation.json"
    if validation.is_file():
        c = archive_totals(validation)
        print(f"  archive (adopted rows): {c['adopted rows: matches']:,} match, {c['adopted rows: differs']:,} differ, "
              f"{c['adopted rows: minor']:,} minor, {c['adopted rows: not_extracted']:,} not extracted "
              f"({c['adopted rows']} rows; Claude Standard: 2,132 match, 0 differ, 27 not extracted)")
        for k in sorted(c):
            print(f"  {c[k]:6,}  {k}")
        return
    from eval_references import score
    got = next((p for p in run_dir.glob("*_extracted.csv")), None)
    r = score(EXPECTED_EDER, got)
    print(f"  {r['rows_got']} / {r['rows_ref']} rows; {r['matched']} / {r['cells']} reference cells "
          f"({100 * r['accuracy']:.1f}%)")
    missed = Counter(col for _, col, _, _ in r["misses"])
    for col, n in missed.most_common(15):
        print(f"  missed {n:4}  {col}")
    if len(missed) > 15:
        print(f"  ... and {len(missed) - 15} more columns")


def run(paper: str, model: str, context: int, vision: bool, out: Path, url: str = None, kind: str = None) -> Path:
    from parameter_extractor import local_models
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.pipeline import run_pipeline
    from parameter_extractor.validation import exoplanet_archive

    saved = local_models.load()
    local = {"kind": kind or saved.kind, "url": url or saved.url, "timeout_sec": saved.timeout_sec, "parallel": 1,
             "api_key": saved.api_key,
             "models": {model: {"context": context, "vision": vision}},
             "profiles": {"check": {"structure_planner": model, "*": model, "figure_planner": model}}}
    info = PAPERS[paper]
    cfg = RunConfig.from_settings(output_dir=out, pack=info["pack"], online_checks=info["online_checks"],
                                  use_pubchem=False, registry_path=None, provider="local", local=local,
                                  model_profile="check")
    t0 = time.time()

    def progress(e):
        print(f"{time.time() - t0:7.0f} s  {getattr(e, 'stage', '')}: {getattr(e, 'message', '')}", flush=True)

    print(f"{paper} on {model} (context {context:,}, images {'on' if vision else 'off'}) at {local['url']}")
    if paper == "teng2023":
        snapshot = json.loads(ARCHIVE_SNAPSHOT.read_text())
        with patch.object(exoplanet_archive, "fetch_parameter_sets", lambda names, ref: snapshot):
            result = run_pipeline(info["pdf"], cfg, on_progress=progress)
    else:
        result = run_pipeline(info["pdf"], cfg, on_progress=progress)
    print(f"done in {(time.time() - t0) / 60:.1f} min: {len(result.rows)} rows", flush=True)
    return Path(result.run_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("model", nargs="?", help="model name as the server lists it (e.g. qwen3.8:27b)")
    ap.add_argument("--paper", choices=[*PAPERS, "both"], default="eder1994")
    ap.add_argument("--context", type=int, default=131072, help="context length that fits on the GPU (not the "
                    "model's reported maximum: docs/local_model_notes.md, issue 3)")
    ap.add_argument("--no-vision", action="store_true", help="the model doesn't read images (table images left out)")
    ap.add_argument("--url", help="server address (default: the app's local model settings)")
    ap.add_argument("--kind", choices=["ollama", "openai"], help="server kind (default: the app's settings)")
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "local_models")
    ap.add_argument("--score", type=Path, metavar="RUN_DIR", help="only compare a finished run folder")
    a = ap.parse_args()
    if a.score:
        compare(a.score)
        return 0
    if not a.model:
        ap.error("give a model name, or --score RUN_DIR")
    for paper in (list(PAPERS) if a.paper == "both" else [a.paper]):
        compare(run(paper, a.model, a.context, not a.no_vision, a.out, a.url, a.kind))
    return 0


if __name__ == "__main__":
    sys.exit(main())
