"""
The experience behind the cost and time estimate before a run (src/parameter_extractor/estimate.py, W4): tokens and
seconds per step from the requests of earlier runs, written to src/parameter_extractor/estimate_data.json (bundled).

Every audit (one request to Claude) under the given folders counts once -- answers reused by a resume or rebuild don't
(they asked nothing). Per step family ('chemistry', 'figure_planner', a pack's configurable step...): medians of the
uncached input, cache-write and cache-read tokens, output tokens (20th / 50th / 80th percentile) and seconds (direct
calls and batch requests apart). Configurable steps without enough requests of their own share the pooled
'_configurable' row. Also: figures per paper (figure suggestions are one request per figure).

Usage: python scripts/build_estimate_data.py [FOLDER ...]   (default: runs/ and ~/Documents/Parameter Extractor)
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "parameter_extractor" / "estimate_data.json"
BUILT_IN = {"structure_planner", "metadata", "methodology", "chemistry", "analysis", "fit_models", "figure_planner",
            "equations", "term_search", "triage"}
MIN_OWN = 8                     # requests a configurable step needs for a row of its own


def _pct(values, q):
    values = sorted(values)
    if not values:
        return 0
    k = (len(values) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo))


def collect(folders):
    requests, figures = [], []
    for folder in folders:
        for summary in Path(folder).expanduser().rglob("run_summary.json"):
            run = summary.parent
            found = run / "figures_found.json"
            if found.is_file():
                try:
                    figures.append(len(json.loads(found.read_text())))
                except ValueError:
                    pass
            for audit_file in run.glob("*.audit.json"):
                try:
                    a = json.loads(audit_file.read_text())
                except ValueError:
                    continue
                model = a.get("model") or ""
                if a.get("reused_from") or not model.startswith("claude-") or "handoff" in model:
                    continue
                family = re.sub(r"\.(fig|pass).*$", "", audit_file.name.replace(".audit.json", ""))
                requests.append(dict(family=family, batch=bool(a.get("batch_id")),
                                     input=a.get("input_tokens") or 0, cache_write=a.get("cache_write_tokens") or 0,
                                     cache_read=a.get("cache_read_tokens") or 0, output=a.get("output_tokens") or 0,
                                     seconds=a.get("elapsed_sec") or 0))
    return requests, figures


def row(reqs):
    direct = [r["seconds"] for r in reqs if not r["batch"]]
    batch = [r["seconds"] for r in reqs if r["batch"]]
    out = {"n": len(reqs)}
    for k in ("input", "cache_write", "cache_read"):
        out[k] = _pct([r[k] for r in reqs], 50)
    out.update(output_low=_pct([r["output"] for r in reqs], 20), output=_pct([r["output"] for r in reqs], 50),
               output_high=_pct([r["output"] for r in reqs], 80))
    if direct:
        out.update(seconds=_pct(direct, 50), seconds_high=_pct(direct, 80))
    if batch:
        out.update(batch_seconds=_pct(batch, 50), batch_seconds_high=_pct(batch, 80))
    return out


def main(folders):
    requests, figures = collect(folders)
    by_family = defaultdict(list)
    for r in requests:
        by_family[r["family"]].append(r)
    steps = {}
    pooled = []
    for family, reqs in sorted(by_family.items()):
        if family in BUILT_IN or len(reqs) >= MIN_OWN:
            steps[family] = row(reqs)
        if family not in BUILT_IN:
            pooled += reqs
    if pooled:
        steps["_configurable"] = row(pooled)
    data = {"about": "Tokens and seconds per step from earlier runs' requests (scripts/build_estimate_data.py); "
                     "used by estimate.py for the estimate before a run.",
            "requests": len(requests), "steps": steps,
            "figures_per_paper": {"low": _pct(figures, 20), "median": _pct(figures, 50), "high": _pct(figures, 80)}}
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"{len(requests)} requests, {len(steps)} step rows, {len(figures)} runs' figures -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:] or [ROOT / "runs", Path.home() / "Documents" / "Parameter Extractor"])
