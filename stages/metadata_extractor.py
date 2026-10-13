from api_client import call_structured
from run_context import RunContext
from schemas.paper_metadata import PaperMetadata
from ingestion.crossref_lookup import lookup_doi
from .prompt_loader import load_prompt


def run_metadata_extraction(ctx: RunContext, title_page_text: str) -> PaperMetadata:
    prompt = load_prompt("metadata", PAPER_TEXT=title_page_text)
    metadata = call_structured(
        ctx,
        stage="metadata",
        system_prompt="Extract bibliographic metadata only. Do not fabricate a DOI.",
        user_content=prompt,
        response_model=PaperMetadata,
    )

    if metadata.paper_doi:
        metadata.doi_source = "paper_text"
    else:
        # Fall back to CrossRef only when the paper itself didn't state one.
        match = lookup_doi(metadata.paper_title, metadata.authors, metadata.year_published)
        if match.accepted:
            metadata.paper_doi = match.doi
            metadata.doi_source = "crossref_api"
            metadata.doi_confidence = match.title_similarity
            metadata.doi_match_title = match.matched_title
            metadata.doi_note = match.reason
        else:
            metadata.doi_source = "not_found"
            metadata.doi_note = match.reason
            metadata.doi_match_title = match.matched_title  # kept for a human to eyeball, even when rejected

    (ctx.run_dir / "metadata.output.json").write_text(metadata.model_dump_json(indent=2))
    return metadata
