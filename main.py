#!/usr/bin/env python3
"""Run the command-line extractor from a source checkout without installing:

    python main.py --pdf "/path/to/paper.pdf" [--out results/] [--triage-only]

Equivalent to the `parameter-extract` command that `pip install -e .` provides.
The code itself lives in src/parameter_extractor/ (see cli.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from parameter_extractor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
