from parameter_extractor.api_client import call_structured
from parameter_extractor.run_context import RunContext
from parameter_extractor.schemas.methodology import Methodology
from parameter_extractor.schemas.structure_plan import StructurePlan
from .prompt_loader import load_prompt


def run_methodology_extraction(
    ctx: RunContext, paper_text: str, structure_plan: StructurePlan,
) -> Methodology:
    prompt = load_prompt(
        "methodology",
        PAPER_TEXT=paper_text,
        STRUCTURE_PLAN_JSON=structure_plan.model_dump_json(indent=2),
    )
    return call_structured(
        ctx,
        stage="methodology",
        system_prompt="Extract methodology parameters. Use status='not_reported' rather "
                      "than assuming a typical/default value when the paper is silent.",
        user_content=prompt,
        response_model=Methodology,
        paper_text=paper_text,
        # 10 fixed fields + a few per-set values and other parameters per set (2-3.5K used so far)
        max_tokens=6000 + 500 * len(structure_plan.experiment_sets),
    )
