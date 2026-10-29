import re
from pathlib import Path
from typing import List, Optional
from parameter_extractor.api_client import call_structured
from parameter_extractor.run_context import RunContext
from parameter_extractor.schemas.structure_plan import StructurePlan
from .prompt_loader import load_prompt


def run_structure_planner(
    ctx: RunContext, paper_text: str, table_images: Optional[List[Path]] = None,
) -> StructurePlan:
    prompt = load_prompt("structure_planner", PAPER_TEXT=paper_text)
    plan = call_structured(
        ctx,
        stage="structure_planner",
        system_prompt="You are planning a database row skeleton from a paper. Precision in "
                      "grouping matters more than speed -- every later extraction step "
                      "depends on getting this right.",
        user_content=prompt,
        response_model=StructurePlan,
        paper_text=paper_text,
        image_paths=table_images,
    )
    fill_durations(plan)
    return plan


# 't = 97.3 h', 'time 45 min', 't=2 d': a time point the label states
_TIME_LABEL = re.compile(r"\b(?:t|time)\s*[=:]?\s*(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours?|min|mins|minutes?|d|days?|s|sec)\b",
                         re.IGNORECASE)
_TO_HOURS = {"h": 1, "hr": 1, "hrs": 1, "hour": 1, "hours": 1, "min": 1 / 60, "mins": 1 / 60, "minute": 1 / 60,
             "minutes": 1 / 60, "d": 24, "day": 24, "days": 24, "s": 1 / 3600, "sec": 1 / 3600}


def fill_durations(plan: StructurePlan) -> int:
    """A sample whose label states its time point ('t = 97.3 h') but whose duration_hr was left empty
    gets it from the label (Economy runs on eder1994 left every duration empty, 5 runs of 5, while
    labelling the samples 't = 97.3 h'). Returns how many were filled."""
    n = 0
    for pset in plan.experiment_sets:
        for sample in pset.samples:
            m = _TIME_LABEL.search(sample.sample_label or "")
            if sample.duration_hr is None and m:
                sample.duration_hr = round(float(m.group(1)) * _TO_HOURS[m.group(2).lower()], 6)
                sample.source = (sample.source + " " if sample.source else "") + "[duration read from the sample label]"
                n += 1
    return n
