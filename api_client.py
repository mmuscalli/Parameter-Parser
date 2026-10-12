"""
Thin wrapper around the Anthropic API. Every stage goes through
`call_structured()` so there is exactly one place that (a) knows how to force
a structured response matching a Pydantic schema, (b) records the audit trail
(prompt, response, token counts, model, timestamp) every stage relies on, and
(c) raises a clear, specific error when no API key is configured -- rather
than stages each reimplementing API calls and silently behaving differently.

Structured output is implemented via forced tool use: the Pydantic model's
JSON schema becomes a single tool's input_schema, and tool_choice forces the
model to call it, so the response is always valid JSON matching the schema
(the SDK/Pydantic validation step still runs on the way back, to catch cases
where the model's output technically parses but violates a constraint).
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
    Calls the model, forces its response into `response_model`'s schema via
    tool use, validates it, writes the full audit trail to `run_dir`, and
    returns the validated Pydantic instance.

    `image_paths`, when given, are attached as image blocks BEFORE the text
    block (images first, then the prompt referencing them, matches Anthropic's
    recommended ordering). Used for table-page rasterizations -- see
    ingestion/pdf_parser.py:rasterize_table_pages -- so the model has the
    actual page layout available, not just the OCR'd/column-garbled text.
    """
    client = _client()
    model = settings.MODELS.get(stage, settings.MODELS["chemistry"])
    schema = response_model.model_json_schema()
    tool_name = f"emit_{response_model.__name__.lower()}"

    if image_paths:
        content = [_image_block(p) for p in image_paths] + [{"type": "text", "text": user_content}]
    else:
        content = user_content

    started = time.time()
    response = client.messages.create(
        model=model,
        max_tokens=settings.MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
        tools=[{"name": tool_name, "description": f"Return the extracted {response_model.__name__}.",
                "input_schema": schema}],
        tool_choice={"type": "tool", "name": tool_name},
    )
    elapsed = time.time() - started

    tool_use_block = next(b for b in response.content if b.type == "tool_use")
    parsed = response_model.model_validate(tool_use_block.input)

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
        "raw_response": tool_use_block.input,
    }
    (run_dir / f"{stage}.audit.json").write_text(json.dumps(audit, indent=2))
    (run_dir / f"{stage}.output.json").write_text(parsed.model_dump_json(indent=2))

    return parsed
