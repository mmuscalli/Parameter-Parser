"""
Developer-only: answer the model steps yourself in a Claude Code session instead of through the API
(Mickey, 2026-10-29). NOT part of public builds -- see dev_features.py: Anthropic doesn't allow third-
party products to offer claude.ai login or subscription limits, so the shipped app uses API keys only.

How it works ("handoff"): with RunConfig.handoff_dir set, every model request is written to a folder
instead of being sent, and the run stops with AnswersNeededError once a round of requests is out:

    <handoff_dir>/<paper>/
        README.md                     what to do (for the person, or a Claude Code session)
        paper.txt                     the paper text the requests refer to (written once)
        images/                       table-page images and figure crops the requests refer to
        requests/<step>-<id>.md       one per model request: instructions, task, answer schema
        answers/<step>-<id>.json      the answer: ONE JSON object matching the request's schema
        answers/<step>-<id>.error.txt why an answer didn't validate (fix it, run again)

Running the same paper again reads the answers it finds, and writes the next round's requests (the
extraction steps need the structure plan's answer first; figure suggestions need their figure).
When every answer is there, the run finishes as usual -- checks, conversions, calculations, review,
CSV -- with no API key and no charge. The request id is a hash of the task text, so a re-run maps to
the same files; a changed prompt (a different structure answer) gets a new id.
"""
from __future__ import annotations
import hashlib
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

from parameter_extractor.errors import AnswersNeededError

MODEL_NAME = "claude-code-handoff"
_lock = threading.Lock()

README = """# Answers needed

This folder holds model requests from a Parameter Extractor run in developer handoff mode.
Each file in `requests/` is one step. For each one:

1. Read its instructions and task, the paper in `paper.txt`, and any images it lists (paths are
   relative to this folder).
2. Write the answer to the path the request names (`answers/<id>.json`): ONE JSON object that
   matches the request's answer schema. Short field names (`v`, `q`, `src`, ...) are the schema's own.
   Report only what the paper states, as the instructions say.

Then run the same paper again (same handoff folder). The run uses the answers it finds and either
finishes or writes the next round of requests here. An answer that doesn't fit its schema gets an
`answers/<id>.error.txt` explaining why.
"""


def paper_dir(handoff_dir: Path, paper_name: str) -> Path:
    return Path(handoff_dir) / re.sub(r"[^\w.\-]+", "_", paper_name)


def answer(ctx, stage: str, system_prompt: str, content, response_model):
    """api_client._send's stand-in: the saved answer as a response, or the request written out and
    AnswersNeededError raised."""
    if getattr(ctx, "handoff_paper_dir", None) is None:
        from parameter_extractor.errors import PipelineError
        raise PipelineError("Developer handoff works for full extraction runs only (not focused searches).")
    folder = Path(ctx.handoff_paper_dir)
    texts, images = _flatten(folder, content)
    task = texts[-1] if texts else ""
    key = f"{stage}-{hashlib.sha1((system_prompt + task).encode()).hexdigest()[:8]}"
    answer_path = folder / "answers" / f"{key}.json"
    error_path = folder / "answers" / f"{key}.error.txt"
    if answer_path.is_file():
        raw = answer_path.read_text()
        try:
            from parameter_extractor.api_client import _decoded
            data = json.loads(raw)
            data = _decoded(data) if isinstance(data, dict) else data
            parsed = response_model.model_validate(data)
        except Exception as e:  # noqa: BLE001 -- any problem with the answer goes back to its author
            error_path.write_text(f"The answer in {answer_path.name} doesn't fit the request's schema:\n\n{e}\n\n"
                                  f"Fix it (or delete it and answer again), then run the paper again.")
            raise AnswersNeededError(folder, [key], invalid=[key]) from None
        error_path.unlink(missing_ok=True)
        return SimpleNamespace(id=f"handoff-{key}", stop_reason="end_turn", parsed_output=parsed,
                               content=[SimpleNamespace(type="text", text=raw)],
                               usage=SimpleNamespace(input_tokens=0, output_tokens=0))
    _write_request(folder, key, stage, system_prompt, texts, images, response_model)
    raise AnswersNeededError(folder, [key])


def _flatten(folder: Path, content):
    """(text parts in order, image paths relative to the folder) of a request's content. The paper
    text goes to paper.txt once; images are saved under images/ by content hash."""
    if isinstance(content, str):
        return [content], []
    texts, images = [], []
    for block in content:
        if block.get("type") == "image":
            import base64
            data = base64.standard_b64decode(block["source"]["data"])
            ext = ".png" if block["source"]["media_type"] == "image/png" else ".jpg"
            name = f"images/{hashlib.sha1(data).hexdigest()[:12]}{ext}"
            path = folder / name
            if not path.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            label = texts.pop() if texts and _is_label(texts[-1]) else ""
            images.append((name, label))
        elif block.get("type") == "text":
            text = block["text"]
            if text.startswith("PAPER TEXT:"):
                with _lock:
                    (folder / "paper.txt").write_text(text[len("PAPER TEXT:"):].lstrip("\n"))
                continue
            texts.append(text)
    return texts, images


def _is_label(text: str) -> bool:
    """api_client puts a short label ('Page 9, piece 2 of 2 ...') before an image piece."""
    return text.startswith("Page ") and "\n" not in text


def _write_request(folder: Path, key: str, stage: str, system_prompt: str, texts, images, response_model):
    with _lock:
        (folder / "requests").mkdir(parents=True, exist_ok=True)
        (folder / "answers").mkdir(parents=True, exist_ok=True)
        (folder / "README.md").write_text(README)
    schema = response_model.model_json_schema(by_alias=True)
    parts = [f"# Request `{key}` (step: {stage})", "",
             f"**Write the answer to:** `answers/{key}.json` -- one JSON object matching the schema at the end.", "",
             "## Instructions", "", system_prompt.strip(), "",
             "## Inputs", "",
             "- The paper's text: `paper.txt`" if (folder / "paper.txt").is_file() else "- (no separate paper text)"]
    parts += [f"- Image: `{name}`" + (f" -- {label}" if label else "") for name, label in images]
    task = [re.sub(r"Answer by calling the `[\w-]+` tool\.", "Answer with ONE JSON object matching the schema below.",
                   t.strip()) for t in texts]
    parts += ["", "## Task", ""] + task + [
        "", "## Answer schema (JSON Schema)", "", "```json", json.dumps(schema, indent=1, ensure_ascii=False), "```", ""]
    (folder / "requests" / f"{key}.md").write_text("\n".join(parts))
