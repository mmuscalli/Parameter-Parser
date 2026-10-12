import json
from pathlib import Path
from typing import List, Optional
from api_client import call_structured
from schemas.chemistry import ChemistryExtraction
from schemas.structure_plan import StructurePlan
from .prompt_loader import load_prompt


def run_chemistry_extraction(
    paper_id: str, paper_text: str, structure_plan: StructurePlan,
    controlled_vocab: list[str], run_dir: Path,
    table_images: Optional[List[Path]] = None,
) -> ChemistryExtraction:
    prompt = load_prompt(
        "chemistry",
        PAPER_TEXT=paper_text,
        STRUCTURE_PLAN_JSON=structure_plan.model_dump_json(indent=2),
        CONTROLLED_VOCAB_JSON=json.dumps(controlled_vocab),
    )
    return call_structured(
        stage="chemistry",
        system_prompt="Extract every species and concentration from text and tables only "
                      "(not figures). Never drop a species that doesn't match the "
                      "controlled vocabulary -- flag it instead.",
        user_content=prompt,
        response_model=ChemistryExtraction,
        run_dir=run_dir,
        image_paths=table_images,
    )
