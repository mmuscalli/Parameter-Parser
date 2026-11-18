"""
How well the estimate before a run (src/parameter_extractor/estimate.py, W4) matches what recorded runs cost: for every
run folder given (or every paper folder of a queue folder), the estimate for its paper with its settings, against the
cost its requests were recorded at -- the requests of the runs it resumed from included (a resumed run asks only what
was missing). Prints each paper and the share whose cost falls inside the estimated range. Free: nothing is sent.

Usage: PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 python scripts/check_estimates.py FOLDER [FOLDER ...]
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import packs  # noqa: E402
from parameter_extractor.config.run_config import RunConfig  # noqa: E402
from parameter_extractor.estimate import estimate  # noqa: E402
from parameter_extractor.resume import config_for, is_queue_folder, original_item  # noqa: E402


def recorded_cost(run: Path, seen=None) -> float:
    """The run's requests' recorded cost, with those of the runs it resumed from."""
    seen = seen or set()
    if run in seen or not run.is_dir():
        return 0.0
    seen.add(run)
    total = 0.0
    for audit in run.glob("*.audit.json"):
        a = json.loads(audit.read_text())
        if not a.get("reused_from"):
            total += a.get("estimated_cost_usd") or 0.0
    try:
        before = json.loads((run / "run_config.json").read_text())["config"].get("resume_from")
    except (OSError, ValueError, KeyError):
        before = None
    return total + (recorded_cost(Path(before), seen) if before else 0.0)


def runs_in(folder: Path):
    if is_queue_folder(folder):
        yield from sorted(p for p in folder.iterdir() if (p / "run_config.json").is_file())
    elif (folder / "run_config.json").is_file():
        yield folder


def main(folders):
    hits = total = 0
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        base = RunConfig(api_key="", output_dir=Path(tmp))
        for folder in folders:
            for run in runs_in(Path(folder)):
                summary = json.loads((run / "run_config.json").read_text())
                if summary["config"].get("rebuild"):
                    continue
                config = config_for(run, base)
                config.resume_from, config.rebuild = None, False
                try:
                    packs.activate(config.pack)
                except Exception as e:                    # noqa: BLE001 -- a pack this install doesn't have
                    print(f"skip {run.name}: pack {config.pack} ({e})")
                    continue
                cost = recorded_cost(run)
                if cost <= 0:
                    continue
                est = estimate(config, [original_item(run)])
                if not est.cost_known:
                    continue
                inside = est.cost_low <= cost <= est.cost_high
                hits += inside
                total += 1
                rows.append((run.name, config.pack, config.model_profile, config.batch_mode, cost, est.cost_low,
                             est.cost_high, inside))
    for name, pack, profile, batch, cost, lo, hi, inside in rows:
        where = "in" if inside else ("BELOW" if cost < lo else "ABOVE")
        print(f"{where:5s} ${cost:6.3f}  estimate ${lo:.3f}-{hi:.3f}  {profile}{' batch' if batch else ''}  {pack}  "
              f"{name}")
    if total:
        below = sum(1 for r in rows if r[4] < r[5])
        print(f"\n{hits} of {total} runs inside the estimated range ({100 * hits / total:.0f}%); "
              f"{below} cost less, {total - hits - below} more")


if __name__ == "__main__":
    main(sys.argv[1:])
