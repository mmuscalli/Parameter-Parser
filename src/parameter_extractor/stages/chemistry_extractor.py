import json
from pathlib import Path
from typing import List, Optional
from parameter_extractor.api_client import call_structured
from parameter_extractor.run_context import RunContext
from parameter_extractor.schemas.chemistry import ChemistryExtraction
from parameter_extractor.schemas.structure_plan import StructurePlan
from .prompt_loader import load_prompt


def chemistry_budget(structure: StructurePlan) -> int:
    """Output tokens the chemistry step can plausibly need -- a few species per set and per
    sample, a few hundred tokens each -- so a runaway answer stops early (api_client retries
    once with twice this). The old format used 7-18K on the reference papers."""
    rows = len(structure.experiment_sets) + sum(len(s.samples) for s in structure.experiment_sets)
    return 10000 + 900 * rows


def run_chemistry_extraction(
    ctx: RunContext, paper_text: str, structure_plan: StructurePlan,
    controlled_vocab: list[str], table_images: Optional[List[Path]] = None,
) -> ChemistryExtraction:
    prompt = load_prompt(
        "chemistry",
        PAPER_TEXT=paper_text,
        STRUCTURE_PLAN_JSON=structure_plan.model_dump_json(indent=2),
        CONTROLLED_VOCAB_JSON=json.dumps(controlled_vocab),
    )
    return call_structured(
        ctx,
        stage="chemistry",
        system_prompt="Extract every species and concentration from text and tables only "
                      "(not figures). Never drop a species that doesn't match the "
                      "controlled vocabulary -- flag it instead.",
        user_content=prompt,
        response_model=ChemistryExtraction,
        paper_text=paper_text,
        max_tokens=chemistry_budget(structure_plan),
        image_paths=table_images,
    )
