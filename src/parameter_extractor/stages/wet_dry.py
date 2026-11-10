"""
Wet-dry cycling -- now an optional stage defined in packs/prebiotic_chemistry/stages/wet_dry.json and run
by stages/optional.py. Kept so existing imports keep working.
"""
from parameter_extractor.stages.optional import load_specs, run_optional_stage


def has_cycling(structure) -> bool:
    spec = load_specs().get("wet_dry")             # None when the active pack doesn't link the Wet-dry module
    return bool(spec and spec.triggered(structure))


def run_wet_dry(ctx, paper_text, structure):
    return run_optional_stage(ctx, load_specs()["wet_dry"], paper_text, structure)
