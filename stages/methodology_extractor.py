import json
from pathlib import Path
from api_client import call_structured
from schemas.methodology import Methodology
from schemas.structure_plan import StructurePlan
from .prompt_loader import load_prompt


def run_methodology_extraction(
    paper_id: str, paper_text: str, structure_plan: StructurePlan, run_dir: Path
) -> Methodology:
    prompt = load_prompt(
        "methodology",
        PAPER_TEXT=paper_text,
        STRUCTURE_PLAN_JSON=structure_plan.model_dump_json(indent=2),
    )
    return call_structured(
        stage="methodology",
        system_prompt="Extract methodology parameters. Use status='not_reported' rather "
                      "than assuming a typical/default value when the paper is silent.",
        user_content=prompt,
        response_model=Methodology,
        run_dir=run_dir,
    )
