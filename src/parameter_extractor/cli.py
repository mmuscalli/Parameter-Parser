#!/usr/bin/env python3
"""
Command-line front end. A thin wrapper over pipeline.run_pipeline() /
run_triage_only() -- the same calls a GUI makes -- so the CLI and any future
interface can't drift apart in behaviour.

    parameter-extract --pdf "/path/to/paper.pdf"                  # extract a pre-selected paper
    parameter-extract --pdf "/path/to/paper.pdf" --out results/   # choose where results go
    parameter-extract --pdf "/path/to/paper.pdf" --triage-only    # optional screening only
    parameter-extract --pdf paper.pdf --look-for "reaction volume" --look-for "stirring rate"
    parameter-extract --self-check [--pdf paper.pdf]             # check the installation (free)

New variables (no column yet) are left out of the CSV from the command line --
the desktop app's review screen is where they're accepted. Variables accepted
there earlier (the local registry) ARE recognised here.

(From a source checkout without installing: python main.py ... does the same.)

The API key comes from config/.env or the ANTHROPIC_API_KEY environment
variable (see config/.env.example). Each run writes to its own timestamped
folder under --out (default: runs/).
"""
import argparse
import sys
from pathlib import Path

from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import PipelineError
from parameter_extractor.pipeline import run_pipeline, run_triage_only
from parameter_extractor.run_context import ProgressEvent


def print_progress(event: ProgressEvent) -> None:
    print(f"[{event.step}/{event.total_steps}] {event.message}...", flush=True)


def main() -> int:
    if "--self-check" in sys.argv:
        from parameter_extractor.diagnostics import main as self_check
        return self_check(sys.argv[1:])

    parser = argparse.ArgumentParser(description="Extract experimental data from a paper PDF.")
    parser.add_argument("--pdf", required=True, help="Path to the paper PDF")
    parser.add_argument("--out", type=Path, help="Folder for run outputs (default: runs/)")
    parser.add_argument("--prefix", default="001", help="3-digit-ish paper prefix for full_id/set_id")
    parser.add_argument("--look-for", action="append", default=[], metavar="TERM",
                        help="A parameter you especially want found (repeatable); each gets an "
                             "explicit found / not-stated answer")
    parser.add_argument("--triage-only", action="store_true",
                        help="Only screen the paper against prompts/triage.md's inclusion "
                             "criteria; skip extraction")
    args = parser.parse_args()

    from parameter_extractor.registry import default_registry_path
    overrides = {"paper_prefix": args.prefix, "registry_path": default_registry_path(),
                 "focus_terms": args.look_for}
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
    if result.new_variables:
        names = sorted({v.name for v in result.new_variables})
        print(f"{len(names)} new variable(s) left out of the CSV (accept them in the desktop app's "
              f"review screen): {', '.join(names)}")
    if result.unfound_terms:
        print(f"Not stated in the paper: {'; '.join(result.unfound_terms)}")
    print(f"Tokens: {result.input_tokens:,} in / {result.output_tokens:,} out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
