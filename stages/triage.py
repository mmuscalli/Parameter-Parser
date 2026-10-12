from pathlib import Path
from api_client import call_structured
from schemas.triage import TriageResult
from .prompt_loader import load_prompt


def run_triage(paper_id: str, paper_text: str, run_dir: Path) -> TriageResult:
    prompt = load_prompt("triage", PAPER_TEXT=paper_text)
    return call_structured(
        stage="triage",
        system_prompt="You are a meticulous research-database curator. Only report what "
                      "the text supports; never guess.",
        user_content=prompt,
        response_model=TriageResult,
        run_dir=run_dir,
    )
