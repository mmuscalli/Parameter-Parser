import json
import re
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


# the prompt's paragraph on TABLE GRIDS (ingestion/table_grid.py): only when the run reads grids (RunConfig.table_grids,
# off by default) -- ~200 tokens of every run's instructions otherwise (organics test set, 2026-11-09)
_GRID_PARAGRAPH = re.compile(r'\nTABLES IN "TABLE GRIDS".*?(?=\n\s*\n)', re.S)


def prompt_text(paper_text: str, plan_json: str, controlled_vocab: list, scope: Optional[list] = None,
                grids: bool = True) -> str:
    """The step's prompt (also the static instructions cached for every paper of a run: api_client). `scope`: only
    these compounds (scopes.py; the vocabulary shown is then just them). `grids` False: without the table-grid rule."""
    from parameter_extractor.scopes import compound_rule
    text = load_prompt("chemistry", PAPER_TEXT=paper_text, STRUCTURE_PLAN_JSON=plan_json,
                       CONTROLLED_VOCAB_JSON=json.dumps(scope or controlled_vocab), COMPOUND_SCOPE=compound_rule(scope))
    return text if grids else _GRID_PARAGRAPH.sub("", text, count=1)     # (the paper text inside stays as it is)


def run_chemistry_extraction(
    ctx: RunContext, paper_text: str, structure_plan: StructurePlan,
    controlled_vocab: list[str], table_images: Optional[List[Path]] = None, grids: Optional[list] = None,
) -> ChemistryExtraction:
    prompt = prompt_text(paper_text, structure_plan.model_dump_json(indent=2), controlled_vocab,
                         ctx.config.scopes.get("chemistry"), grids=ctx.config.table_grids)
    result = call_structured(
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
    result.fill_grids(grids)          # tables mapped onto the app's grids: cells read here (table_grid.py)
    return result
