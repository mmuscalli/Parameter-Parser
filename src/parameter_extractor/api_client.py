"""
Thin wrapper around the Anthropic API. Every stage goes through
`call_structured()` so there is exactly one place that (a) gets a structured
response matching a Pydantic schema, (b) records the audit trail (prompt,
response, token counts, model) every stage relies on, and (c) turns API
failures into the named, user-readable errors in errors.py -- rather than
stages each reimplementing API calls and failing differently.

Structured output uses the API's native structured-outputs feature via
`client.messages.stream(output_format=<PydanticModel>)`: the API constrains the
response to the model's JSON schema and the SDK validates it back into the
Pydantic class. (This replaced an earlier forced-tool-use approach --
tool_choice {"type": "tool"} -- which current models such as
claude-sonnet-5-5 reject with a 400.)

The key and model come from the run's RunContext/RunConfig, never from the
environment directly, so a GUI can supply them at run time.
"""
from __future__ import annotations
import base64
import json
import time
from pathlib import Path
from typing import List, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from parameter_extractor import errors
from parameter_extractor.pricing import request_cost
from parameter_extractor.run_context import RunContext, StageUsage

T = TypeVar("T", bound=BaseModel)

_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _image_block(path: Path) -> dict:
    media_type = _MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(f"Unsupported image type for {path} -- expected jpg/jpeg/png.")
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def _send(ctx: RunContext, *, model: str, system_prompt: str, content, response_model):
    """The one network call. Streamed because chemistry output for a
    table-heavy paper can run to tens of thousands of tokens; the SDK requires
    streaming for max_tokens that large. (Tests replace this function to
    replay saved responses without calling the API.)"""
    with ctx.client.messages.stream(
        model=model,
        max_tokens=ctx.config.max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
        output_format=response_model,
    ) as stream:
        return stream.get_final_message()


def _send_mapping_errors(ctx: RunContext, stage: str, model: str, **kwargs):
    import anthropic
    try:
        return _send(ctx, model=model, **kwargs)
    except anthropic.AuthenticationError:
        raise errors.InvalidApiKeyError() from None
    except anthropic.NotFoundError:
        raise errors.ModelUnavailableError(model) from None
    except anthropic.RateLimitError:
        raise errors.RateLimitedError() from None
    except anthropic.APIConnectionError:
        raise errors.NetworkError() from None
    except anthropic.APIStatusError as e:
        raise errors.ApiRequestError(f"The Anthropic API returned an error during the "
                                     f"'{stage}' step: {e.message}") from None
    except ValidationError as e:
        # raised while parsing the streamed JSON -- almost always a cut-off answer
        raise errors.MalformedOutputError(stage, e.errors()[0].get("msg", "invalid JSON")) from None


def call_structured(
    ctx: RunContext,
    *,
    stage: str,
    system_prompt: str,
    user_content: str,
    response_model: Type[T],
    image_paths: Optional[List[Path]] = None,
    audit_name: Optional[str] = None,
) -> T:
    """
    Calls the model, constrains its response to `response_model`'s schema via
    structured outputs, validates it, writes the full audit trail to the run
    folder, records token usage on `ctx`, and returns the validated instance.

    `image_paths`, when given, are attached as image blocks BEFORE the text
    block (images first, then the prompt referencing them, matches Anthropic's
    recommended ordering). `audit_name` names the audit/output files (default:
    the stage name) -- for stages that run more than once per paper. Used for
    table-page rasterizations -- see
    ingestion/pdf_parser.py:rasterize_table_pages -- so the model has the
    actual page layout available, not just the OCR'd/column-garbled text.
    """
    model = ctx.config.model_for(stage)
    if image_paths:
        content = [_image_block(p) for p in image_paths] + [{"type": "text", "text": user_content}]
    else:
        content = user_content

    started = time.time()
    response = _send_mapping_errors(ctx, stage, model, system_prompt=system_prompt,
                                    content=content, response_model=response_model)
    elapsed = time.time() - started

    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise errors.ModelRefusedError(stage, getattr(details, "explanation", "") or "")
    if response.stop_reason == "max_tokens":
        raise errors.OutputTruncatedError(stage)
    if response.parsed_output is None:
        raise errors.MalformedOutputError(stage, f"no structured output; stop_reason="
                                                 f"{response.stop_reason!r}")
    parsed = response.parsed_output
    raw_text = next((b.text for b in response.content if b.type == "text"), None)

    ctx.record_usage(StageUsage(stage=stage, model=model,
                                input_tokens=response.usage.input_tokens,
                                output_tokens=response.usage.output_tokens,
                                elapsed_sec=round(elapsed, 2),
                                cost_usd=request_cost(model, response.usage.input_tokens,
                                                      response.usage.output_tokens)))

    run_dir = ctx.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "stage": stage,
        "model": model,
        "elapsed_sec": round(elapsed, 2),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "estimated_cost_usd": ctx.usage[-1].cost_usd,
        "images_attached": [str(p) for p in (image_paths or [])],
        "system_prompt": system_prompt,
        "user_content": user_content,
        "stop_reason": response.stop_reason,
        "message_id": response.id,
        "raw_response": json.loads(raw_text) if raw_text else None,
    }
    name = audit_name or stage
    (run_dir / f"{name}.audit.json").write_text(json.dumps(audit, indent=2))
    (run_dir / f"{name}.output.json").write_text(parsed.model_dump_json(indent=2))

    return parsed
