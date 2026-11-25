import json
import re
from parameter_extractor.schemas.structure_plan import step_plan_json
from pathlib import Path
from functools import lru_cache
from typing import List, Optional, Sequence
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
                grids: bool = True, check: Sequence[str] = ()) -> str:
    """The step's prompt (also the static instructions cached for every paper of a run: api_client). `scope`: only
    these compounds (scopes.py; the vocabulary shown is then just them). `grids` False: without the table-grid rule.
    `check` (RunConfig.check_compounds): an answer in `checked` for each of these compounds (parameter_checks.py)."""
    from parameter_extractor.scopes import compound_rule
    text = load_prompt("chemistry", PAPER_TEXT=paper_text, STRUCTURE_PLAN_JSON=plan_json,
                       CONTROLLED_VOCAB_JSON=json.dumps(scope or controlled_vocab), COMPOUND_SCOPE=compound_rule(scope)
                       + (_check_paragraph(check) if check else ""))
    return text if grids else _GRID_PARAGRAPH.sub("", text, count=1)     # (the paper text inside stays as it is)


def _check_paragraph(compounds: Sequence[str]) -> str:
    from parameter_extractor.parameter_checks import rule
    return ("\nCOMPOUNDS TO ANSWER FOR: " + "; ".join(compounds) + ".\n"
            + rule(compounds, "compound", "`tables` / `groups`").replace("listed above", "listed here") + "\n")


@lru_cache(maxsize=None)
def answer_format(check: tuple = ()):
    """The step's answer format: ChemistryExtraction, with a `checked` entry per compound when asked."""
    if not check:
        return ChemistryExtraction
    from parameter_extractor.parameter_checks import with_checks
    return with_checks(ChemistryExtraction, list(check))


def run_chemistry_extraction(
    ctx: RunContext, paper_text: str, structure_plan: StructurePlan,
    controlled_vocab: list[str], table_images: Optional[List[Path]] = None, grids: Optional[list] = None,
) -> ChemistryExtraction:
    check = tuple(ctx.config.check_compounds or ())
    prompt = prompt_text(paper_text, step_plan_json(structure_plan), controlled_vocab,
                         ctx.config.scopes.get("chemistry"), grids=ctx.config.table_grids, check=check)
    result = call_structured(
        ctx,
        stage="chemistry",
        system_prompt="Extract every species and concentration from text and tables only "
                      "(not figures). Never drop a species that doesn't match the "
                      "controlled vocabulary -- flag it instead.",
        user_content=prompt,
        response_model=answer_format(check),
        paper_text=paper_text,
        max_tokens=chemistry_budget(structure_plan),
        image_paths=table_images,
    )
    result.fill_grids(grids)          # tables mapped onto the app's grids: cells read here (table_grid.py)
    if check:
        from parameter_extractor.parameter_checks import record
        record(ctx, "chemistry", result, list(check))
    return result
