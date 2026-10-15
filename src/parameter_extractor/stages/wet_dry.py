"""
Optional stage, run only when the structure plan contains wet-dry cycling sets
(set_type "Evaporation Cycle", or samples with a cycle_number): extracts the
cycle duration and the wet- and dry-phase conditions per set. Values go into
the template's cycle_duration_hr and the app's standard wet/dry phase columns
(schemas/standard_columns.json).
"""
from parameter_extractor.api_client import call_structured
from parameter_extractor.run_context import RunContext
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.schemas.wet_dry import WetDryConditions
from .prompt_loader import load_prompt


def has_cycling(structure: StructurePlan) -> bool:
    return any(s.set_type == "Evaporation Cycle" or any(x.cycle_number is not None for x in s.samples)
               for s in structure.experiment_sets)


def run_wet_dry(ctx: RunContext, paper_text: str, structure: StructurePlan) -> WetDryConditions:
    prompt = load_prompt("wet_dry", STRUCTURE_PLAN_JSON=structure.model_dump_json(indent=2),
                         PAPER_TEXT=paper_text)
    return call_structured(
        ctx,
        stage="wet_dry",
        system_prompt="Extract wet-dry cycling conditions. Report only what the paper states.",
        user_content=prompt,
        response_model=WetDryConditions,
    )
