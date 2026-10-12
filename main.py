#!/usr/bin/env python3
"""
CLI entry point.

    python main.py --pdf "/path/to/paper.pdf"                 # extract a pre-selected paper
    python main.py --pdf "/path/to/paper.pdf" --triage-only   # optional screening only, no extraction

Requires ANTHROPIC_API_KEY (see config/.env.example). Without it, this will
raise ApiKeyMissingError as soon as a stage tries to call the API -- that's
intentional; see README.md for how runs/eder1994/ was produced without one.
"""
import argparse
from pipeline import run_pipeline, run_triage_only
from api_client import ApiKeyMissingError

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="Path to the paper PDF")
    parser.add_argument("--prefix", default="001", help="3-digit-ish paper prefix for full_id/set_id")
    parser.add_argument("--triage-only", action="store_true",
                        help="Only screen the paper against prompts/triage.md's inclusion criteria; skip extraction")
    args = parser.parse_args()

    try:
        if args.triage_only:
            run_triage_only(args.pdf)
        else:
            run_pipeline(args.pdf, paper_prefix=args.prefix)
    except ApiKeyMissingError as e:
        print(f"\n{e}\n")
        raise SystemExit(1)
