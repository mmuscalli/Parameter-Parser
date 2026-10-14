"""
Optional stage, run only when the user entered "parameters to look for": a
targeted search that must answer every term explicitly (found with a value
and quote, or not stated), so a parameter the user cares about is never
silently missed. Findings go to the "Review new variables" screen like any
other new variable -- nothing reaches the CSV without the user accepting it
(or having accepted the same parameter on an earlier run).
"""
import json
from typing import List

from parameter_extractor.api_client import call_structured
from parameter_extractor.run_context import RunContext
from parameter_extractor.schemas.structure_plan import StructurePlan
from parameter_extractor.schemas.variables import TermSearch
from .prompt_loader import load_prompt


def run_term_search(ctx: RunContext, terms: List[str], paper_text: str, structure_plan: StructurePlan,
                    columns: List[str]) -> TermSearch:
    prompt = load_prompt(
        "term_search",
        TERMS="\n".join(f"- {t}" for t in terms),
        STRUCTURE_PLAN_JSON=structure_plan.model_dump_json(indent=2),
        COLUMNS_JSON=json.dumps(columns),
        PAPER_TEXT=paper_text,
    )
    result = call_structured(
        ctx,
        stage="term_search",
        system_prompt="You search a scientific paper for specific parameters a researcher asked "
                      "for. Report only what the paper states; say plainly when it doesn't.",
        user_content=prompt,
        response_model=TermSearch,
    )
    # make sure every term has an answer, even if the model skipped one
    answered = {f.term.strip().lower() for f in result.findings}
    from parameter_extractor.schemas.variables import TermFinding
    for t in terms:
        if t.strip().lower() not in answered:
            result.findings.append(TermFinding(term=t, found=False, name="", value="", column="",
                                               set_label="", quote="", source="", confidence="low"))
    return result
