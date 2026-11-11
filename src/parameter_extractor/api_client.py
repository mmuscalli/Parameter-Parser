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
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from parameter_extractor import errors
from parameter_extractor.pricing import request_cost
from parameter_extractor.run_context import RunContext, StageUsage

T = TypeVar("T", bound=BaseModel)

_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def _piece_label(path: Path) -> str:
    """'page-9-2of2.jpg' -> a note saying how the pieces of a large table page fit together; a page of
    the supplementary information (rendered into an 'SI' folder) is called 'SI page N'."""
    si = path.parent.name.startswith("SI")
    crop = re.fullmatch(r"page-(\d+)-table(ED\d+|[A-Z]?\d+|[IVX]+)(?:-(\d+)of(\d+))?", path.stem)
    if crop:                                  # a table cropped from its page (pdf_parser._table_crops)
        page, table, k, n = crop.groups()
        table = table if not si or table.startswith("S") else f"S{table}"      # a supplement's own 'S' once
        name = f"Extended Data Table {table[2:]}" if table.startswith("ED") else f"Table {table}"
        where = f"{'Supplementary information page S' if si else 'Page '}{page}, {name}"
        return (f"{where}, piece {k} of {n} (a large table is cut into pieces, top to bottom and left to right; "
                f"a piece that continues the table to the right repeats the row labels on its left):" if k
                else f"{where} (the table cropped from the page):")
    m = re.fullmatch(r"page-(\d+)-(\d+)of(\d+)", path.stem)
    if not m:
        whole = re.fullmatch(r"page-(\d+)", path.stem)
        return f"Supplementary information, page S{whole.group(1)}:" if si and whole else ""
    page, k, n = m.groups()
    where = f"Supplementary information page S{page}" if si else f"Page {page}"
    return (f"{where}, piece {k} of {n} (a large table page is cut into pieces, top to bottom and left to "
            f"right; a piece that continues the table to the right repeats the row labels on its left):")


@dataclass
class PaperContext:
    """The paper as every paper-reading step sees it, sent first in each request so it's
    cached once and read by the other steps at 5-10% of the input price (prompt caching:
    the prefix must be byte-identical -- same system prompt, same images, same text)."""
    text: str
    images: List[Path] = field(default_factory=list)
    # every paper-reading step of the run: stage name -> its answer schema, sent as tools in EVERY
    # request (same list, same order) so the cached prefix is shared; non-strict, because the API's
    # strict-grammar size limit can't take them all -- answers are validated here instead
    tools: Dict[str, type] = field(default_factory=dict)
    _definitions: Optional[list] = None
    last_used: float = 0.0           # when a request last read or wrote the cached paper (it lives 5 min / 1 h)
    # every step's static instructions (stage -> its prompt with PLAN_MARK where the paper's structure plan goes;
    # 2026-11-07): sent in the system prompt, cached BEFORE the paper -- the same for every paper of a run's pack
    # and settings, so a queue's later papers read them (and the tool list) at 10% instead of paying them again
    instructions: Dict[str, str] = field(default_factory=dict)
    long_lived: bool = False

    def system_blocks(self):
        """The system prompt: the shared line, then every step's instructions, cached (tools + this = a prefix
        shared across papers). Just the shared line when there are no instructions."""
        if not self.instructions:
            return SHARED_SYSTEM
        cache = {"type": "ephemeral", "ttl": "1h"} if self.long_lived else {"type": "ephemeral"}
        steps = "\n\n".join(f"### STEP `{stage}`\n\n{text}" for stage, text in self.instructions.items())
        return [{"type": "text", "cache_control": cache, "text": (
            f"{SHARED_SYSTEM}\n\nINSTRUCTIONS FOR EACH STEP (each request names its step; where a step's "
            f"instructions show {PLAN_MARK}, the structure plan is in the request):\n\n{steps}")}]

    def task_for(self, stage: str, task_text: str) -> Optional[str]:
        """The request text for a step whose instructions are in the system prompt: only what's specific to this
        paper (the structure plan). None when the step's prompt doesn't match its stored instructions (then the
        whole prompt is sent, as before)."""
        static = self.instructions.get(stage)
        if not static:
            return None
        if PLAN_MARK not in static:
            return "" if task_text == static else None
        head, tail = static.split(PLAN_MARK, 1)
        if not (task_text.startswith(head) and task_text.endswith(tail)) or len(task_text) < len(head) + len(tail):
            return None
        plan = task_text[len(head):len(task_text) - len(tail)]
        return f"STRUCTURE PLAN for this paper:\n\n{plan}"

    def fresh(self, long_lived: bool = False) -> bool:
        """The cached paper is probably still there: used within the last 4.5 minutes (55 with the 1-hour
        cache). A later request would pay to cache the whole paper again."""
        return bool(self.last_used) and time.time() - self.last_used < (3300 if long_lived else 270)

    def tool_definitions(self) -> list:
        if self._definitions is None:
            self._definitions = [{"name": stage, "description": f"Record your answer for the '{stage}' step.",
                                  "input_schema": model_facing_schema(model.model_json_schema())}
                                 for stage, model in self.tools.items()]
        return self._definitions


def model_facing_schema(schema: dict) -> dict:
    """A tool's schema as the model needs it: without pydantic's generated "title" on every field and model,
    and without the classes' docstrings (developer notes); the fields' descriptions stay. 2026-11-03: the
    prebiotic tool list went from 10.6K to 8.8K tokens -- in every run's cached prefix."""
    import copy
    schema = copy.deepcopy(schema)

    def walk(node, model_level: bool) -> None:
        if isinstance(node, dict):
            node.pop("title", None)
            if model_level:
                node.pop("description", None)
            for key, value in node.items():
                if key == "$defs":
                    for d in value.values():
                        walk(d, True)
                elif key == "properties":
                    for p in value.values():
                        walk(p, False)
                else:
                    walk(value, False)
        elif isinstance(node, list):
            for item in node:
                walk(item, False)
    walk(schema, True)
    return schema


SHARED_SYSTEM = ("You extract information from one scientific paper for a research dataset. Report only what the "
                 "paper states. The paper (its text, and images of its table pages) comes first; your task for "
                 "this step follows it.")
PAPER_ABOVE = "(The paper's full text is given above, before these instructions, with images of its table pages.)"
PLAN_MARK = "[THIS PAPER'S STRUCTURE PLAN -- given in the request]"


def _image_blocks(image_paths) -> list:
    blocks = []
    for p in image_paths:
        label = _piece_label(Path(p))
        if label:
            blocks.append({"type": "text", "text": label})
        blocks.append(_image_block(Path(p)))
    return blocks


def _paper_blocks(paper: PaperContext, long_lived: bool = False, cached: bool = True) -> list:
    # batch mode: the 1-hour cache (batches can take longer than the default 5 minutes). `cached` False: the same
    # blocks without the cache mark -- a request whose model no later request uses (Balanced: Sonnet plans the
    # rows, Haiku reads the paper after it; a cache is per model, so Sonnet's would be paid for and never read)
    cache = {"type": "ephemeral", "ttl": "1h"} if long_lived else {"type": "ephemeral"}
    text = {"type": "text", "text": f"PAPER TEXT:\n\n{paper.text}"}
    if cached:
        text["cache_control"] = cache
    return _image_blocks(paper.images) + [text]


def steps_model_differs(config, stage: str = "structure_planner") -> bool:
    """The steps after `stage` read the paper with another model (Balanced profile): `stage` caches nothing."""
    try:
        return config.model_for(stage) != config.model_for("chemistry")
    except Exception:
        return False


def warm_cache(ctx: RunContext) -> None:
    """Before the parallel steps of a run whose steps use another model than the row planning (Balanced): one tiny
    request with the steps' shared prefix (tools, system, paper) writes the paper's cache for their model, so the
    steps read it instead of each writing its own copy at the same time (2026-11-09 cost pass). Skipped in tests
    (the network call is replaced), batch mode, handoff, local servers and without caching."""
    cfg = ctx.config
    if (ctx.paper is None or not cfg.prompt_caching or getattr(cfg, "resume_from", None) or cfg.batch_mode or cfg.handoff_dir or getattr(cfg, "is_local", False)
            or _send is not _REAL_SEND or not getattr(cfg, "api_key", None) or not steps_model_differs(cfg)):
        return
    model = cfg.model_for("chemistry")
    content = _paper_blocks(ctx.paper) + [{"type": "text", "text": "(Writing the paper to the cache for the next "
                                                                   "steps. Reply with one word: OK.)"}]
    request = dict(model=model, max_tokens=1, system=ctx.paper.system_blocks(),
                   messages=[{"role": "user", "content": content}])
    if ctx.paper.tools:
        request.update(tools=ctx.paper.tool_definitions(),
                       tool_choice={"type": "auto", "disable_parallel_tool_use": True})
    start = time.time()
    try:
        message = ctx.client.messages.create(**request)
    except Exception:                        # a failed warm-up only means the steps write the cache themselves
        return
    _record(ctx, "cache_warmup", model, message, time.time() - start)
    ctx.paper.last_used = time.time()


def _record(ctx: RunContext, stage: str, model: str, response, elapsed: float) -> StageUsage:
    u = response.usage
    write, read = getattr(u, "cache_creation_input_tokens", 0) or 0, getattr(u, "cache_read_input_tokens", 0) or 0
    write_1h = getattr(getattr(u, "cache_creation", None), "ephemeral_1h_input_tokens", 0) or 0
    batch = bool(ctx.config.batch_mode)
    cost = 0.0 if getattr(ctx.config, "is_local", False) else request_cost(
        model, u.input_tokens, u.output_tokens, write - write_1h, read, cache_write_1h_tokens=write_1h, batch=batch)
    usage = StageUsage(stage=stage, model=model, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                       elapsed_sec=round(elapsed, 2), cost_usd=cost,
                       cache_write_tokens=write, cache_read_tokens=read, batch=batch)
    ctx.record_usage(usage)
    return usage


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
    _streamed.text = ""
    tool = getattr(_streamed, "tool", None)          # (tool name, every tool's definition): shared-paper mode
    request = dict(model=model, max_tokens=getattr(_streamed, "max_tokens", None) or ctx.config.max_tokens,
                   system=system_prompt, messages=[{"role": "user", "content": content}])
    if tool:
        # "auto" (Sonnet 5.5 rejects a forced tool); the task names the tool; one call only
        request.update(tools=tool[1], tool_choice={"type": "auto", "disable_parallel_tool_use": True})
    elif ctx.config.batch_mode:                      # a batch takes raw API parameters
        from anthropic.lib._parse._transform import transform_schema
        request.update(output_config={"format": {"type": "json_schema", "schema": transform_schema(response_model)}})
    else:
        request.update(output_format=response_model)
    if ctx.config.batch_mode:
        message = _send_batch(ctx, request)
        if tool:
            return _from_tool_call(message, tool[0], response_model)
        return _from_json_text(message, response_model)
    with ctx.client.messages.stream(**request) as stream:
        chunks = []
        try:
            for event in stream:                     # kept so a broken answer can be saved
                piece = getattr(event, "partial_json", None) if event.type == "input_json" else (
                    getattr(event, "text", None) if event.type == "text" else None)
                if piece:
                    chunks.append(piece)
        finally:
            _streamed.text = "".join(chunks)
        message = stream.get_final_message()
    return _from_tool_call(message, tool[0], response_model) if tool else message


# first wait, longest wait between status checks. Checks are free; a long interval only delays
# noticing a finished batch -- at 60 s, waits landed on 165 / 349 s marks (2026-10-27 A/B), up to a
# minute after the batch had ended. (Pooling one run's parallel steps into one batch was tried too:
# 2-request batches waited ~350 s per phase vs ~165 s for 1-request ones -> not used for single runs.)
BATCH_POLL_SECONDS = (5, 15)


class BatchCollector:
    """Requests from many threads pooled into shared Message Batches (focused search, 2026-10-25: 1,389
    papers sent as 1,389 one-request batches, each waiting ~2.5 min in the queue, 4 at a time -> 14 h).
    A batch is sent once no request has joined it for `quiet_sec`, `max_wait_sec` after its first
    request, or at `max_size` requests; each batch is polled on its own thread, and every caller gets
    its own result back (submit() blocks like a direct call, so retries, usage records and audits stay
    as they are). `flush()` sends what's waiting now (when no more requests will come)."""
    def __init__(self, client, quiet_sec: float = 20.0, max_wait_sec: float = 120.0, max_size: int = 2000):
        import uuid
        self._uuid = uuid
        self.client, self.quiet, self.max_wait, self.max_size = client, quiet_sec, max_wait_sec, max_size
        self._cv = threading.Condition()
        self._pending: list = []
        self._first = self._last = 0.0
        self._flush_now = False
        self._thread = None
        self.batches: list = []                   # ids of the batches sent (for the summary)

    def submit(self, request: dict, stage: str, cancel_event=None):
        """(message, batch id) for one request, once its batch has ended."""
        from types import SimpleNamespace
        entry = SimpleNamespace(custom_id=f"{stage}-{self._uuid.uuid4().hex[:16]}", params=request,
                                done=threading.Event(), result=None, error=None, batch_id=None, cancel=cancel_event)
        with self._cv:
            if not self._pending:
                self._first = time.monotonic()
            self._last = time.monotonic()
            self._pending.append(entry)
            if self._thread is None:
                self._thread = threading.Thread(target=self._sender, daemon=True, name="batch-sender")
                self._thread.start()
            self._cv.notify_all()
        while not entry.done.wait(1.0):
            if cancel_event is not None and cancel_event.is_set():
                raise errors.RunCancelledError()
        if entry.error is not None:
            raise entry.error
        return _batch_message(entry.result, stage), entry.batch_id

    def flush(self) -> None:
        with self._cv:
            self._flush_now = True
            self._cv.notify_all()

    def _sender(self) -> None:
        while True:
            with self._cv:
                while not self._pending:
                    self._flush_now = False
                    self._cv.wait()
                now = time.monotonic()
                due = (self._flush_now or len(self._pending) >= self.max_size or now - self._last >= self.quiet
                       or now - self._first >= self.max_wait)
                if not due:
                    self._cv.wait(timeout=1.0)
                    continue
                group, self._pending = self._pending[:self.max_size], self._pending[self.max_size:]
                self._first = self._last = time.monotonic()
            try:
                batch = self.client.messages.batches.create(
                    requests=[{"custom_id": e.custom_id, "params": e.params} for e in group])
            except Exception as exc:              # the API refused the batch: each caller gets the error
                for e in group:
                    e.error = exc
                    e.done.set()
                continue
            self.batches.append(batch.id)
            for e in group:
                e.batch_id = batch.id
            threading.Thread(target=self._poll, args=(batch, group), daemon=True, name="batch-poll").start()

    def _poll(self, batch, group) -> None:
        delay = BATCH_POLL_SECONDS[0]
        try:
            while batch.processing_status != "ended":
                time.sleep(delay)
                if all(e.cancel is not None and e.cancel.is_set() for e in group):
                    self.client.messages.batches.cancel(batch.id)
                    for e in group:
                        e.error = errors.RunCancelledError()
                    return
                delay = min(delay * 1.5, BATCH_POLL_SECONDS[1])
                batch = self.client.messages.batches.retrieve(batch.id)
            by_id = {e.custom_id: e for e in group}
            for item in self.client.messages.batches.results(batch.id):
                if item.custom_id in by_id:
                    by_id[item.custom_id].result = item.result
            for e in group:
                if e.result is None and e.error is None:
                    e.error = errors.ApiRequestError("The batch ended without an answer for this request.")
        except Exception as exc:
            for e in group:
                if e.result is None:
                    e.error = exc
        finally:
            for e in group:
                e.done.set()


def _batch_message(result, stage: str):
    """A batch request's result -> its message, or the error it stands for."""
    if result.type == "succeeded":
        return result.message
    if result.type == "errored":
        error = getattr(result.error, "error", result.error)
        kind, text = getattr(error, "type", ""), getattr(error, "message", str(error))
        raise _BatchRequestError(kind, text)
    if result.type == "expired":
        raise errors.BatchExpiredError(stage)
    raise errors.RunCancelledError()


def _send_batch(ctx: RunContext, request: dict):
    """One request through the Message Batches API (half price; usually done in seconds to minutes,
    at most 24 h): submit, poll until it has ended, return its message. Cancelling the run cancels
    the batch. Errors come back per request and are mapped like direct-call errors. With a shared
    collector on the context (ctx.batch_collector), the request joins other threads' requests."""
    import uuid
    stage = getattr(_streamed, "stage", "step")
    collector = getattr(ctx, "batch_collector", None)
    if collector is not None:
        message, _streamed.batch_id = collector.submit(request, stage, ctx.cancel_event)
        return message
    batch = ctx.client.messages.batches.create(
        requests=[{"custom_id": f"{stage}-{uuid.uuid4().hex[:12]}", "params": request}])
    _streamed.batch_id = batch.id
    ctx.note(stage, f"{stage}: queued as a batch request (half price) -- waiting for Anthropic to process it")
    started, delay, last_note = time.time(), BATCH_POLL_SECONDS[0], time.time()
    while batch.processing_status != "ended":
        cancel = ctx.cancel_event
        if cancel is not None:
            cancelled = cancel.wait(delay)            # wakes at once when the user cancels
        else:
            time.sleep(delay)
            cancelled = False
        if cancelled:
            ctx.client.messages.batches.cancel(batch.id)
            raise errors.RunCancelledError()
        delay = min(delay * 1.5, BATCH_POLL_SECONDS[1])
        batch = ctx.client.messages.batches.retrieve(batch.id)
        if time.time() - last_note > 60:
            ctx.note(stage, f"{stage}: batch request still queued ({(time.time() - started) / 60:.0f} min)")
            last_note = time.time()
    return _batch_message(next(iter(ctx.client.messages.batches.results(batch.id))).result, stage)


class _BatchRequestError(Exception):
    """A batch request that came back errored: mapped in _send_mapping_errors."""
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


def _from_json_text(message, response_model):
    """A batch answer with output_config: its JSON text validated into the response model, in the
    shape the streaming helper returns (parsed_output)."""
    from types import SimpleNamespace
    text = next((b.text for b in message.content if b.type == "text"), None)
    _streamed.text = text or ""
    parsed = response_model.model_validate_json(text) if text else None
    return SimpleNamespace(id=message.id, usage=message.usage, parsed_output=parsed, stop_reason=message.stop_reason,
                           stop_details=getattr(message, "stop_details", None), content=message.content)


def _out_of_credits(status: int, kind: str, text: str) -> bool:
    """Credit balance used up, a spend limit / the monthly spend cap reached, or a billing problem."""
    text = (text or "").lower()
    return status == 402 or kind == "billing_error" or any(
        k in text for k in ("credit balance", "spend limit", "spend cap", "spending limit", "billing"))


def _decoded(data):
    """Tool inputs aren't grammar-constrained (non-strict tools): a list or object sent as a JSON
    *string* (Haiku, teng2023: "parameters": "[{...}]") is decoded instead of failing the step -- also when stray
    words follow the complete JSON inside the string (Sonnet, 2026-11-09: '[...]\nthe rows', twice in a row)."""
    if not isinstance(data, dict):
        return data
    out = {}
    for key, value in data.items():
        if isinstance(value, str) and value.lstrip()[:1] in ("[", "{"):
            try:
                value = json.loads(value)
            except ValueError:
                try:
                    value = json.JSONDecoder().raw_decode(value.lstrip())[0]
                except ValueError:
                    pass
        out[key] = value
    return out


def _from_tool_call(message, name: str, response_model):
    """A forced tool call's input, validated like a structured output (a ValidationError here is
    handled like a broken answer: retried once)."""
    from types import SimpleNamespace
    block = next((b for b in message.content if b.type == "tool_use" and b.name == name), None)
    parsed = response_model.model_validate(_decoded(block.input)) if block is not None else None
    return SimpleNamespace(
        id=message.id, usage=message.usage, parsed_output=parsed,
        stop_reason="end_turn" if message.stop_reason == "tool_use" else message.stop_reason,
        stop_details=getattr(message, "stop_details", None),
        content=[SimpleNamespace(type="text", text=json.dumps(block.input))] if block is not None else [])


# the text streamed by the current thread's call (stages run in parallel threads)
_streamed = threading.local()


def _finished_steps(ctx: RunContext) -> list:
    seen = []
    for u in ctx.usage:
        if u.stage not in seen:
            seen.append(u.stage)
    return seen


# a streamed answer cut off by the server or the network (2026-11-06, Mickey's Riggi run: httpx RemoteProtocolError
# "peer closed connection without sending complete message body" in the structure step). The SDK retries a request
# only until the stream starts; a drop mid-stream came out as a raw transport error, i.e. "a bug in the app".
STREAM_RETRY_WAITS = (3, 10)                  # seconds before the 2nd and 3rd try


def _dropped_connection(e: BaseException) -> bool:
    """An SDK connection error, or a transport error of the HTTP stack (httpx / httpcore / h11, any fork name)."""
    import anthropic
    if isinstance(e, anthropic.APIConnectionError):
        return True
    for cls in type(e).__mro__:
        root = cls.__module__.split(".")[0]
        if root.startswith(("httpx", "httpcore", "h11")) and cls.__name__ in (
                "TransportError", "NetworkError", "ProtocolError", "RemoteProtocolError", "ReadError",
                "ReadTimeout", "TimeoutException", "ConnectError", "WriteError", "CloseError"):
            return True
    return False


def _send_resuming(ctx: RunContext, stage: str, model: str, **kwargs):
    """`_send`, asked again (up to twice, after a short wait) when the connection drops; then NetworkError."""
    for attempt in range(len(STREAM_RETRY_WAITS) + 1):
        try:
            return _send(ctx, model=model, **kwargs)
        except Exception as e:
            if not _dropped_connection(e):
                raise
            if attempt == len(STREAM_RETRY_WAITS):
                raise errors.NetworkError(stage) from None
            if hasattr(ctx, "note"):
                ctx.note(stage, "The connection to the Anthropic API broke off; asking again …")
            cancel = getattr(ctx, "cancel_event", None)
            if cancel is not None and cancel.wait(STREAM_RETRY_WAITS[attempt]):
                raise errors.RunCancelledError() from None
            if cancel is None:
                import time
                time.sleep(STREAM_RETRY_WAITS[attempt])


def _send_mapping_errors(ctx: RunContext, stage: str, model: str, **kwargs):
    import anthropic
    _streamed.stage = stage
    if ctx.config.handoff_dir:                 # developer only (dev_features.py): answered in Claude Code
        try:
            from parameter_extractor import handoff
        except ImportError:
            raise errors.PipelineError("Developer handoff mode isn't part of this build.") from None
        return handoff.answer(ctx, stage, kwargs["system_prompt"], kwargs["content"], kwargs["response_model"])
    credits = lambda detail: errors.OutOfCreditsError(stage, detail, _finished_steps(ctx), getattr(ctx, "run_dir", None))
    try:
        if getattr(ctx.config, "is_local", False):     # a model on the user's own server (local_models.py)
            from parameter_extractor import local_models
            return local_models.send(ctx, stage, model, **kwargs)
        return _send_resuming(ctx, stage, model, **kwargs)
    except _BatchRequestError as e:
        if _out_of_credits(0, e.kind, e.message):
            raise credits(e.message) from None
        raise errors.ApiRequestError(f"The Anthropic API returned an error for the '{stage}' step's batch "
                                     f"request: {e.message}") from None
    except anthropic.AuthenticationError:
        raise errors.InvalidApiKeyError() from None
    except anthropic.NotFoundError:
        raise errors.ModelUnavailableError(model) from None
    except anthropic.RateLimitError as e:
        if _out_of_credits(429, "", e.message):           # the tier's monthly spend cap: retrying won't help
            raise credits(e.message) from None
        raise errors.RateLimitedError() from None
    except anthropic.APIConnectionError:
        raise errors.NetworkError() from None
    except anthropic.APIStatusError as e:
        kind = getattr(e, "type", None) or ""
        if _out_of_credits(getattr(e, "status_code", 0), kind, e.message):
            raise credits(e.message) from None
        if getattr(e, "status_code", 0) == 529 or "overloaded" in str(e.message).lower():
            raise errors.ApiRequestError(f"Anthropic's API is overloaded right now (the '{stage}' step was retried "
                                         f"several times). Try the paper again in a few minutes.") from None
        raise errors.ApiRequestError(f"The Anthropic API returned an error during the "
                                     f"'{stage}' step: {e.message}") from None
    except ValidationError as e:
        # raised while parsing the streamed JSON -- almost always a cut-off answer; keep what
        # arrived (<stage>.failed_output.txt) so the cause can be seen
        raw = getattr(_streamed, "text", "")
        if raw and getattr(ctx, "run_dir", None):
            (Path(ctx.run_dir) / f"{stage}.failed_output.txt").write_text(raw)
        raise errors.MalformedOutputError(stage, e.errors()[0].get("msg", "invalid JSON")) from None


def request_fingerprint(model: str, system_prompt, user_content: str, cached_prefix: Optional[str], image_paths,
                        response_model) -> str:
    """What a step asks, as one hash (W1): the model, the step's own instructions and input (paper text, plan), the
    images by file name (a new run renders them into its own folder) and the answer format. Taken before the
    request is laid out for caching, batch mode or a local server, so it doesn't depend on those."""
    import hashlib
    try:
        schema = json.dumps(response_model.model_json_schema(), sort_keys=True)
    except Exception:                       # pragma: no cover -- every answer format has a schema
        schema = response_model.__name__
    record = {"model": model, "system": system_prompt if isinstance(system_prompt, str) else "",
              "user": user_content, "prefix": cached_prefix or "",
              "images": [Path(p).name for p in (image_paths or [])], "schema": schema}
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def call_structured(
    ctx: RunContext,
    *,
    stage: str,
    system_prompt: str,
    user_content: str,
    response_model: Type[T],
    image_paths: Optional[List[Path]] = None,
    audit_name: Optional[str] = None,
    max_tokens: Optional[int] = None,
    paper_text: Optional[str] = None,
    cached_prefix: Optional[str] = None,
    on_paper: bool = False,
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
    model = "claude-code-handoff" if ctx.config.handoff_dir else ctx.config.model_for(stage)
    name = (audit_name or stage) + (getattr(_streamed, "pass_suffix", "") or "")   # '.pass2' with several passes
    fingerprint = request_fingerprint(model, system_prompt, user_content, cached_prefix, image_paths, response_model)
    if getattr(ctx.config, "resume_from", None):        # an earlier run's saved answer (resume.py, W1)
        from parameter_extractor import resume
        reused = resume.saved_answer(ctx, stage, name, model, fingerprint, system_prompt, user_content,
                                     cached_prefix, response_model)
        if reused is not None:
            return reused
    shared = (paper_text is not None and ctx.paper is not None and ctx.config.prompt_caching
              and paper_text in user_content)
    _streamed.tool = None
    if on_paper and ctx.paper is not None and stage in ctx.paper.tools:
        # a step that reads the cached paper and adds a cached layer of its own (figure_planner, 2026-11-03):
        # the paper (cached by the extraction steps), then `cached_prefix` -- the same for every figure of the
        # paper, cached as a second breakpoint --, then this request's images and text
        cache = {"type": "ephemeral", "ttl": "1h"} if ctx.config.batch_mode else {"type": "ephemeral"}
        content = (_paper_blocks(ctx.paper, ctx.config.batch_mode)
                   + [{"type": "text", "text": f"YOUR TASK: {system_prompt}\n\n{cached_prefix or ''}",
                       "cache_control": cache}]
                   + (_image_blocks(image_paths) if image_paths else [])
                   + [{"type": "text", "text": f"{user_content}\n\nAnswer by calling the `{stage}` tool."}])
        system_prompt = ctx.paper.system_blocks()
        _streamed.tool = (stage, ctx.paper.tool_definitions())
        shared = True                  # the paper's cache was read: keep it marked fresh
    elif shared:
        # the paper first, identical in every step and cached; the step's own task after it. With
        # tools (`ctx.paper.tools`), every step sends the same tool list and is made to call its own:
        # the API's cache key includes a request's output schema, so a different schema per step
        # (output_format) would give every step its own cache entry (measured 2026-10-22)
        task_text = user_content.replace(paper_text, PAPER_ABOVE)
        own = ctx.paper.task_for(stage, task_text)
        if own is not None:            # the step's instructions are in the cached system prompt
            task_text = (f"Follow the instructions for step `{stage}` in the system prompt."
                         + (f"\n\n{own}" if own else ""))
        content = _paper_blocks(ctx.paper, ctx.config.batch_mode,
                                cached=not (stage == "structure_planner" and steps_model_differs(ctx.config))) + [
            {"type": "text", "text": (f"YOUR TASK: {system_prompt}\n\n" + task_text
            + (f"\n\nAnswer by calling the `{stage}` tool." if stage in ctx.paper.tools else ""))}]
        system_prompt = ctx.paper.system_blocks()
        image_paths = ctx.paper.images
        if stage in ctx.paper.tools:
            _streamed.tool = (stage, ctx.paper.tool_definitions())
    elif cached_prefix and ctx.config.prompt_caching:
        # a prefix shared by several requests of a run (figure_planner: the same for every figure),
        # marked for caching; then this request's images and text
        cache = {"type": "ephemeral", "ttl": "1h"} if ctx.config.batch_mode else {"type": "ephemeral"}
        content = ([{"type": "text", "text": cached_prefix, "cache_control": cache}]
                   + (_image_blocks(image_paths) if image_paths else []) + [{"type": "text", "text": user_content}])
    elif image_paths:
        content = _image_blocks(image_paths) + [{"type": "text", "text": (cached_prefix or "") + user_content}]
    else:
        content = (cached_prefix or "") + user_content

    # `max_tokens`: the stage's output budget (a runaway answer -- the model repeating itself
    # inside a field, aa57186-25 -- then stops in seconds, not after 64K tokens / 7 minutes).
    # A broken or cut-off answer is retried once with twice the budget: these are rare and random.
    budget = min(max_tokens, ctx.config.max_tokens) if max_tokens else ctx.config.max_tokens
    for attempt in (1, 2):
        # retry: twice the stage's budget (never more than the maximum) -- room for an answer that
        # really is longer, without letting a second runaway take minutes
        _streamed.max_tokens = budget if attempt == 1 else min(2 * budget, ctx.config.max_tokens)
        started = time.time()
        try:
            response = _send_mapping_errors(ctx, stage, model, system_prompt=system_prompt,
                                            content=content, response_model=response_model)
            if response.stop_reason == "max_tokens":
                _record(ctx, stage, model, response, time.time() - started)   # paid for, even if unusable
                raise errors.OutputTruncatedError(stage)
            if response.parsed_output is None and response.stop_reason != "refusal":
                raise errors.MalformedOutputError(stage, f"no structured output; stop_reason="
                                                         f"{response.stop_reason!r}")
            if shared and ctx.paper is not None:
                ctx.paper.last_used = time.time()
            break
        except (errors.OutputTruncatedError, errors.MalformedOutputError) as e:
            if attempt == 2:
                raise
            ctx.note(stage, f"{stage}: the answer broke off -- asking again")
    elapsed = time.time() - started

    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise errors.ModelRefusedError(stage, getattr(details, "explanation", "") or "")
    parsed = response.parsed_output
    if getattr(ctx, "plan_ids", None) and parsed is not None:       # ids for sets / samples -> their labels
        from parameter_extractor.schemas.structure_plan import expand_ids
        expand_ids(parsed, ctx.plan_ids)
    raw_text = next((b.text for b in response.content if b.type == "text"), None)

    usage = _record(ctx, stage, model, response, elapsed)

    run_dir = ctx.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "cache_write_tokens": usage.cache_write_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "stage": stage,
        "model": model,
        "elapsed_sec": round(elapsed, 2),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "estimated_cost_usd": usage.cost_usd,
        "batch_id": getattr(_streamed, "batch_id", None) if ctx.config.batch_mode else None,
        "images_attached": [str(p) for p in (image_paths or [])],
        # the cached system prompt holds every step's instructions: named, not copied into every audit
        "system_prompt": system_prompt if isinstance(system_prompt, str) else
        f"{SHARED_SYSTEM} + cached instructions for steps: {', '.join(ctx.paper.instructions) if ctx.paper else ''}",
        "user_content": user_content,
        "cached_prefix": cached_prefix,
        "stop_reason": response.stop_reason,
        "message_id": response.id,
        "request_fingerprint": fingerprint,          # a later resume reuses this answer for the same request
        "raw_response": json.loads(raw_text) if raw_text else None,
    }
    (run_dir / f"{name}.audit.json").write_text(json.dumps(audit, indent=2))
    (run_dir / f"{name}.output.json").write_text(parsed.model_dump_json(indent=2))

    return parsed


_REAL_SEND = _send          # warm_cache: tests replace _send to replay answers -- never call the API then
