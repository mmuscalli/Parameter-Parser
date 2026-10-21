"""
Wet-dry cycling -- now an optional stage defined in stages/specs/wet_dry.json and run
by stages/optional.py. Kept so existing imports keep working.
"""
from parameter_extractor.stages.optional import load_specs, run_optional_stage


def has_cycling(structure) -> bool:
    return load_specs()["wet_dry"].triggered(structure)


def run_wet_dry(ctx, paper_text, structure):
    return run_optional_stage(ctx, load_specs()["wet_dry"], paper_text, structure)
