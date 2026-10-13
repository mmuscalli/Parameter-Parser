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
    return call_structured(
        ctx,
        stage="structure_planner",
        system_prompt="You are planning a database row skeleton from a paper. Precision in "
                      "grouping matters more than speed -- every later extraction step "
                      "depends on getting this right.",
        user_content=prompt,
        response_model=StructurePlan,
        image_paths=table_images,
    )
