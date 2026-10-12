#!/usr/bin/env python3
"""
CLI entry point.

    python main.py --pdf "/path/to/paper.pdf"

Requires ANTHROPIC_API_KEY (see config/.env.example). Without it, this will
raise ApiKeyMissingError as soon as a stage tries to call the API -- that's
intentional; see README.md for how runs/eder1994/ was produced without one.
"""
import argparse
from pipeline import run_pipeline
from api_client import ApiKeyMissingError

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="Path to the paper PDF")
    parser.add_argument("--prefix", default="001", help="3-digit-ish paper prefix for full_id/set_id")
    args = parser.parse_args()

    try:
        run_pipeline(args.pdf, paper_prefix=args.prefix)
    except ApiKeyMissingError as e:
        print(f"\n{e}\n")
        raise SystemExit(1)
