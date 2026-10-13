"""
Per-field scoring against a human-curated answer key.

OFF by default (config.settings.USE_GOLD_STANDARD = False) because that
curated "most certain and exhaustive" paper subset doesn't exist yet. This
module is intentionally left unimplemented beyond the scaffold below --
fill in `load_gold_standard` and `score_paper` once
config.settings.GOLD_STANDARD_PATH points at a real file, then flip the flag.

Suggested scoring approach once it's wired up: per template column, report
(a) exact match rate on reported-vs-reported values, (b) false "not_reported"
rate (gold has a value, pipeline said not_reported), and (c) false "found"
rate (pipeline invented a value gold doesn't have) -- those three numbers are
more informative than one blended accuracy score, since they fail in very
different ways for a database like this.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List

from parameter_extractor.config import settings

ENABLED = False  # flip once eval/gold_standard/curated_subset.csv exists


def load_gold_standard(path: Path = settings.GOLD_STANDARD_PATH) -> List[dict]:
    if not ENABLED:
        raise RuntimeError(
            "gold_standard_eval is disabled (ENABLED = False). Drop the curated "
            "subset CSV into eval/gold_standard/, set config.settings.USE_GOLD_STANDARD "
            "= True and ENABLED = True here, then implement this loader against the "
            "CSV's actual columns."
        )
    raise NotImplementedError


def score_paper(extracted_rows: List[dict], gold_rows: List[dict]) -> Dict[str, float]:
    if not ENABLED:
        raise RuntimeError("gold_standard_eval is disabled -- see load_gold_standard().")
    raise NotImplementedError
