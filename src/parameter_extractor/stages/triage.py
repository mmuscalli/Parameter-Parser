from parameter_extractor.api_client import call_structured
from parameter_extractor.run_context import RunContext
from parameter_extractor.schemas.triage import TriageResult
from .prompt_loader import load_prompt


def run_triage(ctx: RunContext, paper_text: str) -> TriageResult:
    prompt = load_prompt("triage", PAPER_TEXT=paper_text)
    return call_structured(
        ctx,
        stage="triage",
        system_prompt="You are a meticulous research-database curator. Only report what "
                      "the text supports; never guess.",
        user_content=prompt,
        response_model=TriageResult,
    )
