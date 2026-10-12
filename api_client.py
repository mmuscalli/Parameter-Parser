"""
Thin wrapper around the Anthropic API. Every stage goes through
`call_structured()` so there is exactly one place that (a) knows how to force
a structured response matching a Pydantic schema, (b) records the audit trail
(prompt, response, token counts, model, timestamp) every stage relies on, and
(c) raises a clear, specific error when no API key is configured -- rather
than stages each reimplementing API calls and silently behaving differently.

Structured output uses the API's native structured-outputs feature via
`client.messages.stream(output_format=<PydanticModel>)`: the API constrains the
response to the model's JSON schema and the SDK validates it back into the
Pydantic class. (This replaced an earlier forced-tool-use approach --
tool_choice {"type": "tool"} -- which current models such as
claude-sonnet-5-5 reject with a 400.)
"""
from __future__ import annotations
import base64
import json
import time
from pathlib import Path
from typing import List, Optional, Type, TypeVar

from pydantic import BaseModel

from config import settings

T = TypeVar("T", bound=BaseModel)

_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _image_block(path: Path) -> dict:
    media_type = _MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(f"Unsupported image type for {path} -- expected jpg/jpeg/png.")
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


class ApiKeyMissingError(RuntimeError):
    pass


def _client():
    if not settings.ANTHROPIC_API_KEY:
        raise ApiKeyMissingError(
            "ANTHROPIC_API_KEY is not set. Copy config/.env.example to config/.env "
            "and add your key, or export ANTHROPIC_API_KEY in your shell. Until then, "
            "stages/* cannot make real API calls -- see README.md for the manual-run "
            "workaround used to produce runs/eder1994/."
        )
    import anthropic  # imported lazily so the rest of the package works without the dep installed
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def call_structured(
    *,
    stage: str,
    system_prompt: str,
    user_content: str,
    response_model: Type[T],
    run_dir: Path,
    image_paths: Optional[List[Path]] = None,
) -> T:
    """
    Calls the model, constrains its response to `response_model`'s schema via
    structured outputs, validates it, writes the full audit trail to `run_dir`, and
    returns the validated Pydantic instance.

    `image_paths`, when given, are attached as image blocks BEFORE the text
    block (images first, then the prompt referencing them, matches Anthropic's
    recommended ordering). Used for table-page rasterizations -- see
    ingestion/pdf_parser.py:rasterize_table_pages -- so the model has the
    actual page layout available, not just the OCR'd/column-garbled text.
    """
    client = _client()
    model = settings.MODELS.get(stage, settings.MODELS["chemistry"])

    if image_paths:
        content = [_image_block(p) for p in image_paths] + [{"type": "text", "text": user_content}]
    else:
        content = user_content

    started = time.time()
    # Streamed because chemistry output for a table-heavy paper can run to tens
    # of thousands of tokens; the SDK requires streaming for max_tokens that
    # large (non-streaming requests risk HTTP timeouts).
    with client.messages.stream(
        model=model,
        max_tokens=settings.MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
        output_format=response_model,
    ) as stream:
        response = stream.get_final_message()
    elapsed = time.time() - started

    if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
        raise RuntimeError(
            f"[{stage}] no usable structured output from {model}: stop_reason="
            f"{response.stop_reason!r}, stop_details={getattr(response, 'stop_details', None)!r}, "
            f"message_id={response.id}. If stop_reason is 'max_tokens', raise "
            f"config.settings.MAX_TOKENS."
        )
    parsed = response.parsed_output
    raw_text = next((b.text for b in response.content if b.type == "text"), None)

    run_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "stage": stage,
        "model": model,
        "elapsed_sec": round(elapsed, 2),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "images_attached": [str(p) for p in (image_paths or [])],
        "system_prompt": system_prompt,
        "user_content": user_content,
        "stop_reason": response.stop_reason,
        "message_id": response.id,
        "raw_response": json.loads(raw_text) if raw_text else None,
    }
    (run_dir / f"{stage}.audit.json").write_text(json.dumps(audit, indent=2))
    (run_dir / f"{stage}.output.json").write_text(parsed.model_dump_json(indent=2))

    return parsed
