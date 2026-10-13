#!/usr/bin/env python3
"""
Command-line front end. A thin wrapper over pipeline.run_pipeline() /
run_triage_only() -- the same calls a GUI makes -- so the CLI and any future
interface can't drift apart in behaviour.

    python main.py --pdf "/path/to/paper.pdf"                  # extract a pre-selected paper
    python main.py --pdf "/path/to/paper.pdf" --out results/   # choose where results go
    python main.py --pdf "/path/to/paper.pdf" --triage-only    # optional screening only

The API key comes from config/.env or the ANTHROPIC_API_KEY environment
variable (see config/.env.example). Each run writes to its own timestamped
folder under --out (default: runs/).
"""
import argparse
import sys
from pathlib import Path

from config.run_config import RunConfig
from errors import PipelineError
from pipeline import run_pipeline, run_triage_only
from run_context import ProgressEvent


def print_progress(event: ProgressEvent) -> None:
    print(f"[{event.step}/{event.total_steps}] {event.message}...", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract experimental data from a paper PDF.")
    parser.add_argument("--pdf", required=True, help="Path to the paper PDF")
    parser.add_argument("--out", type=Path, help="Folder for run outputs (default: runs/)")
    parser.add_argument("--prefix", default="001", help="3-digit-ish paper prefix for full_id/set_id")
    parser.add_argument("--triage-only", action="store_true",
                        help="Only screen the paper against prompts/triage.md's inclusion "
                             "criteria; skip extraction")
    args = parser.parse_args()

    overrides = {"paper_prefix": args.prefix}
    if args.out:
        overrides["output_dir"] = args.out
    config = RunConfig.from_settings(**overrides)

    try:
        if args.triage_only:
            triage = run_triage_only(args.pdf, config, on_progress=print_progress)
            print(f"\nTriage recommendation: {triage.recommendation}\n{triage.reasoning}")
            if triage.excluded_experiment_note:
                print(f"Excluded-experiment note: {triage.excluded_experiment_note}")
            return 0

        result = run_pipeline(args.pdf, config, on_progress=print_progress)
    except PipelineError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130

    print(f"\nWrote {len(result.rows)} rows -> {result.csv_path}")
    if result.flags_path:
        print(f"{len(result.paper_flags)} paper-level flag(s), {len(result.row_flags)} row(s) "
              f"flagged -> {result.flags_path}")
    print(f"Tokens: {result.input_tokens:,} in / {result.output_tokens:,} out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
