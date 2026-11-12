"""
Locally hosted models (Mickey, 2026-11-08): the app's steps answered by a model running on the user's own machine or
network instead of the Anthropic API. Two kinds of server:

- "ollama"  -- Ollama's own API (POST /api/chat). The only way to set the context length per request (`num_ctx`);
               Ollama's default (a few thousand tokens) would silently cut a paper off.
- "openai"  -- any OpenAI-compatible server (POST /v1/chat/completions): LM Studio, llama.cpp's llama-server, vLLM,
               ... The context length is the server's own setting; ours is only used to refuse a paper that won't fit.

Both are asked for a JSON answer constrained to the step's schema (Ollama `format`, OpenAI `response_format`
json_schema), and the schema (with its field descriptions) is also in the system prompt -- a grammar alone doesn't tell
the model what a field means. The answer is validated by the step's pydantic model as usual; a broken answer is asked
again once by api_client.call_structured.

What differs from an API run (RunConfig.__post_init__ switches these off): no prompt caching, batch mode or shared
cached instructions -- every step sends its own request with the paper. Table / figure images go only to models marked
as reading images. Requests to one server wait for each other (`parallel`, default 1: most local servers answer one
request at a time), so parallel steps, passes, queues and focused searches all work unchanged. Cost is $0; tokens
come from the server's reply. Every local run gets a `local_model` flag: results from an unvalidated local model.

Settings live in <app data>/local_models.json (`LocalSettings`): the server, each model's context length and whether it
reads images, and the user's model PROFILES (like Standard / Balanced / Economy: which model plans the rows, which
does the extraction steps, which suggests figure settings). A run carries them in RunConfig.local (a plain dict).
Plain HTTP via urllib -- no extra dependency. Nothing here is used unless RunConfig.provider == "local".
"""
from __future__ import annotations
import base64
import json
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional

from parameter_extractor import errors

KINDS = {"ollama": "Ollama", "openai": "OpenAI-compatible server (LM Studio, llama.cpp, vLLM, ...)"}
DEFAULT_URLS = {"ollama": "http://localhost:11434", "openai": "http://localhost:1234"}
DEFAULT_CONTEXT = 32768
# profile keys: which model does what (RunConfig.model_for)
PROFILE_ROLES = [("structure_planner", "Plans the rows"), ("*", "Extraction steps"),
                 ("figure_planner", "Figure suggestions")]
# E1: the start every step of a paper shares (see send)
PAPER_FIRST_SYSTEM = ("You extract information from one scientific paper for a research dataset. The paper comes "
                      "first; the task, its instructions and the answer format follow in the next message. Report only "
                      "what the paper states.")
PAPER_HEADING = "THE PAPER (text, as extracted from its PDF):\n\n"
PAPER_IN_FIRST_MESSAGE = "[the paper: in the first message above]"
KEEP_ALIVE = "30m"           # Ollama keeps the model loaded between steps and papers (its default is 5 minutes)

FLAG_TEXT = ("Extracted with a locally hosted model ({models}). Local models aren't validated for this app the way the "
             "default Anthropic models are: check the values against the paper.")
HOSTED_FLAG_TEXT = ("Extracted with {models} on {server}. Models other than the default Anthropic ones aren't validated for "
                    "this app: check the values against the paper.")


def flag_text(config) -> str:
    """The paper flag of a run on a model server: local, or a hosted service (Models > Connections)."""
    local = config.local or {}
    models = ", ".join(models_used(config)) or "?"
    if local.get("name") and local.get("private") is False:
        return HOSTED_FLAG_TEXT.format(models=models, server=local["name"])
    return FLAG_TEXT.format(models=models)


def _temperature(ctx) -> float:
    """A profile's temperature; 0 when it sets none (repeatable answers)."""
    t = getattr(ctx.config, "temperature", None)
    return 0 if t is None else t


def server_cost(config, model: str, input_tokens: int, output_tokens: int):
    """$ for one request to a model server: the model's prices when set (Models > Connections); free on a private
    server; unknown (None) on a hosted one without prices."""
    local = config.local or {}
    m = (local.get("models") or {}).get(model) or {}
    if m.get("price_input") is not None or m.get("price_output") is not None:
        return (input_tokens * float(m.get("price_input") or 0) + output_tokens * float(m.get("price_output") or 0)) \
            / 1_000_000
    return None if local.get("private") is False else 0.0


@dataclass
class LocalModel:
    context: int = DEFAULT_CONTEXT          # tokens the model may hold (prompt + answer); Ollama's num_ctx
    vision: bool = False                     # reads images (table crops, figures)
    thinking: str = "model"                  # E2: "model" = as the model decides; "off" = Ollama's think: false


@dataclass
class LocalSettings:
    kind: str = "ollama"
    url: str = DEFAULT_URLS["ollama"]
    timeout_sec: int = 900                   # longest wait for the next piece of an answer (a long prompt is read first)
    parallel: int = 1                        # requests the server answers at once
    models: Dict[str, LocalModel] = field(default_factory=dict)
    profiles: Dict[str, Dict[str, str]] = field(default_factory=dict)   # name -> {role: model}
    api_key: str = ""                        # OpenAI-compatible servers that want one (never saved to the file)

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "LocalSettings":
        d = dict(d or {})
        models = {name: LocalModel(**{k: v for k, v in (m or {}).items() if k in ("context", "vision", "thinking")})
                  for name, m in (d.pop("models", None) or {}).items()}
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(models=models, **known)

    def to_dict(self, with_key: bool = True) -> dict:
        d = asdict(self)
        if not with_key:
            d.pop("api_key", None)
        return d

    def model(self, name: str) -> LocalModel:
        return self.models.get(name) or LocalModel()

    def profile_names(self) -> List[str]:
        return list(self.profiles)


def default_path() -> Path:
    from parameter_extractor.registry import default_registry_path
    return default_registry_path().with_name("local_models.json")


def load(path: Optional[Path] = None) -> LocalSettings:
    path = Path(path) if path else default_path()
    try:
        return LocalSettings.from_dict(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        return LocalSettings()


def save(local: LocalSettings, path: Optional[Path] = None) -> None:
    path = Path(path) if path else default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(local.to_dict(with_key=False), indent=2))


def model_for(local: dict, profile: str, stage: str) -> str:
    """The model a local profile gives a step: its own role, figure steps -> 'figure_planner', else '*'."""
    profiles = (local or {}).get("profiles") or {}
    chosen = profiles.get(profile) or (next(iter(profiles.values())) if profiles else {})
    if stage in chosen:
        return chosen[stage]
    if stage == "equations" and chosen.get("figure_planner"):
        return chosen["figure_planner"]
    if chosen.get("*"):
        return chosen["*"]
    raise errors.PipelineError(f"The local model profile '{profile}' names no model for the '{stage}' step. Choose "
                               f"models in Models > Model profiles….")


# ---- talking to the server ---------------------------------------------------------------------------------------

def _endpoint(local: LocalSettings, path: str) -> str:
    base = local.url.rstrip("/")
    if local.kind == "openai" and not base.endswith("/v1"):
        base += "/v1"
    return base + path


def _headers(local: LocalSettings, stage: str = "") -> dict:
    h = {"Content-Type": "application/json"}
    if local.api_key:
        h["Authorization"] = f"Bearer {local.api_key}"
    if stage:
        h["X-Parameter-Extractor-Step"] = stage       # shows in server logs; used by the tests' fake server
    return h


def _unreachable(local: LocalSettings, e) -> errors.PipelineError:
    name = "Ollama" if local.kind == "ollama" else "the local model server"
    return errors.PipelineError(f"Couldn't reach {name} at {local.url} ({getattr(e, 'reason', e)}). Is it running? "
                                f"(Ollama: open the app, or run 'ollama serve'.) The address is in Models > "
                                f"Connections.")


def _get_json(local: LocalSettings, path: str, body: Optional[dict] = None, timeout: float = 15) -> dict:
    req = urllib.request.Request(_endpoint(local, path), headers=_headers(local),
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise errors.ApiRequestError(f"The local model server answered {e.code}: {_error_text(e)}") from None
    except (urllib.error.URLError, OSError) as e:
        raise _unreachable(local, e) from None


def _error_text(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read() or b"{}")
        err = body.get("error")
        return (err.get("message") if isinstance(err, dict) else err) or json.dumps(body)[:300]
    except Exception:
        return str(e.reason)


def list_models(local: LocalSettings) -> List[dict]:
    """The server's models: [{name, vision (True/False/None = unknown), max_context (or None)}]."""
    if local.kind == "ollama":
        out = []
        for m in _get_json(local, "/api/tags").get("models", []):
            name = m.get("name") or m.get("model")
            info = {"name": name, "vision": None, "max_context": None}
            try:
                shown = _get_json(local, "/api/show", {"model": name})
                caps = shown.get("capabilities")
                if caps is not None:
                    info["vision"] = "vision" in caps
                ctx = [v for k, v in (shown.get("model_info") or {}).items() if k.endswith(".context_length")]
                info["max_context"] = int(ctx[0]) if ctx else None
            except errors.PipelineError:
                pass
            out.append(info)
        return out
    return [{"name": m.get("id"), "vision": None, "max_context": None}
            for m in _get_json(local, "/models").get("data", [])]


_gates: Dict[tuple, threading.Semaphore] = {}
_gates_lock = threading.Lock()


def _gate(local: LocalSettings) -> threading.Semaphore:
    """Requests to one server wait for each other (local servers answer `parallel` at a time)."""
    key = (local.url.rstrip("/"), max(1, int(local.parallel or 1)))
    with _gates_lock:
        return _gates.setdefault(key, threading.Semaphore(key[1]))


def _text_and_images(content) -> tuple:
    """Anthropic-style content (a string, or text / image blocks) -> [('text', s) | ('image', (media, b64))]."""
    if isinstance(content, str):
        return [("text", content)]
    parts = []
    for block in content:
        if block.get("type") == "text":
            parts.append(("text", block["text"]))
        elif block.get("type") == "image":
            src = block["source"]
            parts.append(("image", (src.get("media_type", "image/png"), src["data"])))
    return parts


def _system_text(system_prompt) -> str:
    if isinstance(system_prompt, str):
        return system_prompt
    return "\n\n".join(b.get("text", "") for b in system_prompt or [])


# fields optional in the compact answer formats (left out to save Claude tokens) that a local model must still give.
# Local runs are free, so the grammar makes them required; Claude's requests are unchanged. Each rule: (field, the
# property an object must also have for the rule to apply).
# - `txt` in configurable steps' values (objects with `col`, each parameter declared text or number): qwen3.8:27b named
#   experiment_type / solution_type but left the text out (eder1994, 2026-11-10; 84 values). NOT in the analysis
#   step's settings, where nothing says which are text: required there, qwen wrote every number as text, units lost.
# - `sample` wherever an answer names a set and a sample: qwen3.8:27b left it out of every planet row (teng2023,
#   2026-11-10), so each value counted for the whole system -- planet c got planet b's numbers, joint-fit rows the
#   RV fit's (168 archive differences).
# - `mode` / `meth` in configurable steps' values: qwen gave teng2023 Table 4's prograde / retrograde inclinations as
#   plain second values (no `mode`), so they read as conflicts instead of posterior modes.
LOCAL_REQUIRED = (("txt", "col"), ("sample", "set"), ("mode", "col"), ("meth", "col"))


def _require_local_fields(node):
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            wanted = [field for field, alongside in LOCAL_REQUIRED if field in props and alongside in props]
            if wanted:
                node["required"] = list(dict.fromkeys(list(node.get("required") or []) + wanted))
        for v in node.values():
            _require_local_fields(v)
    elif isinstance(node, list):
        for v in node:
            _require_local_fields(v)
    return node


def answer_schema(response_model) -> dict:
    """The schema the model must follow -- the same transformation the API's structured outputs use, minus titles,
    with LOCAL_REQUIRED fields required."""
    from anthropic.lib._parse._transform import transform_schema
    from parameter_extractor.api_client import model_facing_schema
    return _require_local_fields(model_facing_schema(transform_schema(response_model)))


def estimate_tokens(text: str, images: int = 0) -> int:
    """A rough count (no tokenizer for an arbitrary local model): ~3.5 characters a token, ~600 per image."""
    return int(len(text) / 3.5) + 600 * images


# ---- E3 (2026-11-11): the real context, and the room left in it ---------------------------------------------------
_run_lock = threading.Lock()


def _calibration(ctx, model: str) -> float:
    """How many real tokens the server counted per estimated one, for this run and model (1.0 until it has said)."""
    return (getattr(ctx, "token_ratio", None) or {}).get(model, 1.0)


def _calibrate(ctx, model: str, estimated: int, reported: int) -> None:
    """Learn the ratio from a request the server read in full. With the paper first (E1) a later request may report
    only the newly read part, so counts well below the estimate are not used; the ratio only ever grows (the check
    before sending must not underestimate), within 0.5-2."""
    if not reported or not estimated:
        return
    base = estimated / _calibration(ctx, model)
    ratio = reported / base
    if ratio < 0.5 or not hasattr(ctx, "config"):
        return
    with _run_lock:
        ratios = dict(getattr(ctx, "token_ratio", None) or {})
        ratios[model] = round(min(2.0, max(ratios.get(model, 0.5), ratio)), 3)
        ctx.token_ratio = ratios


def spill_of(entry: dict) -> float:
    """The share of a loaded model NOT in GPU memory (Ollama /api/ps: size, size_vram), 0..1."""
    size, vram = entry.get("size") or 0, entry.get("size_vram")
    if not size or vram is None:
        return 0.0
    return max(0.0, 1.0 - vram / size)


def _check_spill(ctx, local: "LocalSettings", model: str) -> None:
    """Once per model and run, after its first answer: is all of it in the GPU's memory? A context length too large
    for the GPU moves part of the model to the CPU -- several times slower (qwen3.8:27b at 262,144: ~30 -> 6.5 tokens
    a second). Noted and flagged; never stops the run."""
    with _run_lock:
        checked = set(getattr(ctx, "spill_checked", None) or ())
        if model in checked:
            return
        ctx.spill_checked = checked | {model}
    try:
        loaded = _get_json(local, "/api/ps", timeout=5).get("models") or []
    except Exception:
        return
    entry = next((m for m in loaded if m.get("name") == model or m.get("model") == model), None)
    share = spill_of(entry) if entry else 0.0
    if share < 0.02:
        return
    spec = local.model(model)
    message = (f"{model} didn't fit in the server's GPU memory: {share:.0%} of it ran on the CPU, which makes it several "
               f"times slower. Its context length ({spec.context:,} tokens) is probably larger than the GPU can hold: "
               f"lower it in Models > Connections (the model's reported maximum is not what fits).")
    with _run_lock:
        ctx.server_flags = list(getattr(ctx, "server_flags", None) or []) + [message]
    if hasattr(ctx, "note"):
        ctx.note("local", message)


# ---- E1: priming (2026-11-11) ---------------------------------------------------------------------------------------
# Measured on qwen3.8:27b (Ollama 0.40.16, a hybrid model with recurrent layers): the server reuses what it read only
# back to a checkpoint, and checkpoints sit near the end of each request -- after a long step, the next step could
# not go back to "just after the paper" and read the whole paper again (eder1994: 27-44 s of reading per step, no
# reuse). A tiny request with only the opening (system line + paper, a 1-token answer) leaves a checkpoint right after
# the paper; the step that follows reads only its own part (conditions 34.9 -> 16.3 s, chemistry 42.0 -> 23.5 s,
# kinetics 31.6 -> 12.9 s), and repeating the priming when the checkpoint is there costs ~0.1 s. Sent before every
# step that starts with the paper, inside the server's one-request slot. Only on private servers: on a hosted service
# each priming request would be paid for as a full read of the paper.
def _primes(local: "LocalSettings") -> bool:
    from parameter_extractor.model_profiles import Connection
    return Connection(id="x", name="x", kind=local.kind, url=local.url).is_private


def _prime(local: "LocalSettings", path: str, body: dict, stage: str, model: str, cancel) -> float:
    """The opening of `body` alone, with a 1-token answer; returns the server's reading time (s), or -1 when the
    server reported none. Failures are ignored: the step's own request follows anyway."""
    prime = {k: v for k, v in body.items() if k not in ("format", "response_format", "messages", "stream_options")}
    prime["messages"] = body["messages"][:2]
    if local.kind == "ollama":
        prime["options"] = dict(body.get("options") or {}, num_predict=1)
    else:
        prime["max_tokens"] = 1
    try:
        _raw, _stop, _usage, timing = _stream(local, path, prime, f"{stage}-priming", model, cancel)
    except errors.RunCancelledError:
        raise
    except Exception:
        return -1.0
    return timing.get("prompt_eval", -1.0) if timing else -1.0


def send(ctx, stage: str, model: str, *, system_prompt, content, response_model):
    """One step's request to the local server; returns an object shaped like the Anthropic SDK's message
    (id, stop_reason, parsed_output, content, usage) so call_structured treats it like any other answer."""
    from parameter_extractor.api_client import _streamed
    local = LocalSettings.from_dict(ctx.config.local)
    spec = local.model(model)
    schema = answer_schema(response_model)
    system = (_system_text(system_prompt) + "\n\nAnswer with ONE JSON object that follows this JSON Schema -- the "
              "field descriptions say what each field holds. Output the JSON only.\n" + json.dumps(schema))
    parts = _text_and_images(content)
    images = [p for kind, p in parts if kind == "image"]
    if images and not spec.vision:
        if hasattr(ctx, "note"):
            ctx.note(stage, f"{model} isn't marked as reading images: {len(images)} table/figure image(s) left out")
        parts, images = [p for p in parts if p[0] == "text"], []
    text = "\n\n".join(p for kind, p in parts if kind == "text")
    # the estimate, scaled by what the server reported for earlier requests of this run (E3, 2026-11-11)
    prompt_tokens = int(estimate_tokens(system + text, len(images)) * _calibration(ctx, model))
    # E1 (2026-11-11): every step of a paper starts the same way -- a fixed system line, then the paper alone -- so
    # the server can reuse what it already read (Ollama / llama.cpp keep the previous prompt and reuse the part that is
    # the same from the start). The step's own instructions, images and answer format come after. Before, the step's
    # system prompt and schema came first and the paper sat inside each step's prompt: read again for every step.
    paper = getattr(_streamed, "paper_text", None)
    paper_first = bool(paper) and paper in text
    room = spec.context - prompt_tokens
    if room < 1024:
        raise errors.PipelineError(
            f"The '{stage}' step needs about {prompt_tokens:,} tokens of context, but '{model}' is set to "
            f"{spec.context:,}. Raise its context length in Models > Connections (the model and your memory "
            f"must allow it), or use a model with a longer context.")
    max_tokens = getattr(_streamed, "max_tokens", None) or ctx.config.max_tokens
    out_tokens = max(1024, min(max_tokens, room))

    if paper_first:
        task = (_system_text(system_prompt) + "\n\n" + text.replace(paper, PAPER_IN_FIRST_MESSAGE)
                + "\n\nAnswer with ONE JSON object that follows this JSON Schema -- the field descriptions say what "
                  "each field holds. Output the JSON only.\n" + json.dumps(schema))
        messages = [{"role": "system", "content": PAPER_FIRST_SYSTEM},
                    {"role": "user", "content": PAPER_HEADING + paper}]
    if local.kind == "ollama":
        if paper_first:
            message = {"role": "user", "content": task}
            if images:
                message["images"] = [data for _, data in images]
            messages = messages + [message]
        else:
            message = {"role": "user", "content": text}
            if images:
                message["images"] = [data for _, data in images]
            messages = [{"role": "system", "content": system}, message]
        body = {"model": model, "stream": True, "format": schema, "messages": messages, "keep_alive": KEEP_ALIVE,
                "options": {"num_ctx": spec.context, "num_predict": out_tokens, "temperature": _temperature(ctx)}}
        if getattr(spec, "thinking", "model") == "off":      # E2: no reasoning before the answer
            body["think"] = False
        path = "/api/chat"
    else:
        image_parts = [{"type": "image_url", "image_url": {"url": f"data:{p[0]};base64,{p[1]}"}}
                       for kind, p in parts if kind == "image"]
        if paper_first:
            user = image_parts + [{"type": "text", "text": task}]
        else:
            user = [{"type": "text", "text": p} if kind == "text" else
                    {"type": "image_url", "image_url": {"url": f"data:{p[0]};base64,{p[1]}"}} for kind, p in parts]
        body = {"model": model, "stream": True, "temperature": _temperature(ctx), "max_tokens": out_tokens,
                "stream_options": {"include_usage": True},
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": stage, "schema": schema, "strict": True}},
                "messages": (messages + [{"role": "user", "content": user}]) if paper_first else
                [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        path = "/chat/completions"

    gate = _gate(local)
    cancel = getattr(ctx, "cancel_event", None)
    while not gate.acquire(timeout=0.5):              # waiting for the server's other requests
        if cancel is not None and cancel.is_set():
            raise errors.RunCancelledError()
    try:
        primed = _prime(local, path, body, stage, model, cancel) if paper_first and _primes(local) else None
        raw, stop, usage, timing = _stream(local, path, body, stage, model, cancel)
    finally:
        gate.release()
    if primed is not None and timing:
        timing = dict(timing, priming=primed)
    _streamed.text = raw
    _calibrate(ctx, model, prompt_tokens, usage[0])
    if local.kind == "ollama":
        _check_spill(ctx, local, model)
    parsed = response_model.model_validate_json(raw) if stop != "max_tokens" else None
    return SimpleNamespace(
        id=f"local-{int(time.time() * 1000)}", stop_reason=stop, parsed_output=parsed,
        content=[SimpleNamespace(type="text", text=raw)],
        usage=SimpleNamespace(input_tokens=usage[0] or prompt_tokens, output_tokens=usage[1] or 0,
                              cache_creation_input_tokens=0, cache_read_input_tokens=0),
        server_timing=dict(timing, estimated_prompt_tokens=prompt_tokens) if timing else None)


def _stream(local: LocalSettings, path: str, body: dict, stage: str, model: str, cancel) -> tuple:
    """POST a streamed request on a helper thread (so Cancel works while the server reads a long prompt);
    returns (answer text, stop reason, (input tokens, output tokens), the server's timings in seconds -- Ollama:
    load, read (prompt evaluation), write (generation), total; {} when the server reports none)."""
    req = urllib.request.Request(_endpoint(local, path), data=json.dumps(body).encode(),
                                 headers=_headers(local, stage))
    pieces: "queue.Queue" = queue.Queue()
    holder = {}

    def worker():
        try:
            with urllib.request.urlopen(req, timeout=local.timeout_sec) as r:
                holder["response"] = r
                for line in r:
                    pieces.put(("line", line))
            pieces.put(("end", None))
        except BaseException as e:                 # handed to the waiting thread
            pieces.put(("error", e))

    threading.Thread(target=worker, daemon=True, name=f"local-{stage}").start()
    chunks, stop, usage, timing = [], "end_turn", [0, 0], {}
    while True:
        try:
            kind, item = pieces.get(timeout=0.5)
        except queue.Empty:
            if cancel is not None and cancel.is_set():
                r = holder.get("response")
                if r is not None:
                    try:
                        r.close()                  # the server stops generating when the connection goes
                    except Exception:
                        pass
                raise errors.RunCancelledError()
            continue
        if kind == "end":
            break
        if kind == "error":
            e = item
            if isinstance(e, urllib.error.HTTPError):
                detail = _error_text(e)
                if e.code == 404 or "not found" in detail.lower():
                    raise errors.PipelineError(f"The local model '{model}' isn't installed on the server ({detail}). "
                                               f"Ollama: 'ollama pull {model}'; or choose another model in "
                                               f"Models > Connections.") from None
                raise errors.ApiRequestError(f"The local model server returned an error during the '{stage}' step "
                                             f"({e.code}): {detail}") from None
            if isinstance(e, (TimeoutError, )) or "timed out" in str(e).lower():
                raise errors.ApiRequestError(f"The local model didn't answer the '{stage}' step within "
                                             f"{local.timeout_sec} s. A long paper can take minutes to read on a "
                                             f"local machine: raise the time limit in Models > Connections.") \
                    from None
            if isinstance(e, (urllib.error.URLError, OSError)):
                raise _unreachable(local, e) from None
            raise e
        line = item.decode("utf-8", "replace").strip()
        if not line:
            continue
        if local.kind == "ollama":
            data = json.loads(line)
            if data.get("error"):
                raise errors.ApiRequestError(f"Ollama returned an error during the '{stage}' step: {data['error']}")
            chunks.append((data.get("message") or {}).get("content") or "")
            if data.get("done"):
                stop = "max_tokens" if data.get("done_reason") == "length" else "end_turn"
                usage = [data.get("prompt_eval_count") or 0, data.get("eval_count") or 0]
                timing = {k: round((data.get(f"{k}_duration") or 0) / 1e9, 2)
                          for k in ("load", "prompt_eval", "eval", "total")}
        else:
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            data = json.loads(payload)
            if data.get("error"):
                raise errors.ApiRequestError(f"The local model server returned an error during the '{stage}' "
                                             f"step: {data['error']}")
            for choice in data.get("choices") or []:
                chunks.append((choice.get("delta") or {}).get("content") or "")
                if choice.get("finish_reason") == "length":
                    stop = "max_tokens"
            if data.get("usage"):
                usage = [data["usage"].get("prompt_tokens") or 0, data["usage"].get("completion_tokens") or 0]
    return "".join(chunks), stop, tuple(usage), timing


def models_used(config) -> List[str]:
    """The local models a run's profile names (for the flag and the summary)."""
    profiles = (config.local or {}).get("profiles") or {}
    chosen = profiles.get(config.model_profile) or {}
    return list(dict.fromkeys(m for m in chosen.values() if m))
