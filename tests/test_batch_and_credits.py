"""
Offline tests for batch mode (every request through the Message Batches API at
half price: submit, poll, read the result, map per-request errors; the 1-hour
cache; cancelling cancels the batch) and for running out of credits (a clear
error naming the step, what had finished and where the partial results are).
A stand-in batch API and SDK error objects; no API calls.

Run with: python tests/test_batch_and_credits.py
"""
import json
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

import anthropic
from pydantic import BaseModel

from parameter_extractor import api_client, errors, packs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pipeline import run_pipeline
from parameter_extractor.pricing import request_cost
from parameter_extractor.run_context import RunContext
from test_pipeline_offline import make_replay

PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Nielsen2019" / "nielsen2019.pdf"
REF = ROOT / "runs" / "nielsen2019_auto"


class Answer(BaseModel):
    planet: str
    period_days: float


class FakeBatches:
    """messages.batches: a request 'ends' after `polls` status checks with the given result."""
    def __init__(self, result, polls=2):
        self.result, self.polls, self.created, self.cancelled, self.checks = result, polls, [], [], 0

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id="msgbatch_1", processing_status="in_progress")

    def retrieve(self, batch_id):
        self.checks += 1
        return SimpleNamespace(id=batch_id, processing_status="ended" if self.checks >= self.polls else "in_progress")

    def results(self, batch_id):
        return iter([SimpleNamespace(custom_id="x", result=self.result)])

    def cancel(self, batch_id):
        self.cancelled.append(batch_id)


def _ctx(tmp, batches, cancel=None, **kw):
    ctx = RunContext(config=RunConfig.from_settings(api_key="x", output_dir=Path(tmp), batch_mode=True, **kw),
                     run_dir=Path(tmp), total_steps=1, cancel_event=cancel)
    ctx._client = SimpleNamespace(messages=SimpleNamespace(batches=batches))
    return ctx


def _message(content, usage=None):
    return SimpleNamespace(id="msg_1", stop_reason="end_turn", stop_details=None, content=content,
                           usage=usage or SimpleNamespace(input_tokens=10, output_tokens=5))


def test_a_request_goes_through_a_batch():
    with patch.object(api_client, "BATCH_POLL_SECONDS", (0.01, 0.01)), tempfile.TemporaryDirectory() as tmp:
        text = SimpleNamespace(type="text", text='{"planet": "HD 1397 b", "period_days": 11.535}')
        batches = FakeBatches(SimpleNamespace(type="succeeded", message=_message([text])))
        ctx = _ctx(tmp, batches)
        out = api_client.call_structured(ctx, stage="planet_parameters", system_prompt="s", user_content="u",
                                         response_model=Answer)
        assert out == Answer(planet="HD 1397 b", period_days=11.535)
        params = batches.created[0][0]["params"]
        assert params["output_config"]["format"]["type"] == "json_schema" and "output_format" not in params
        assert batches.created[0][0]["custom_id"].startswith("planet_parameters-")
        usage = ctx.usage[0]
        assert usage.batch and abs(usage.cost_usd - request_cost("claude-sonnet-5-5", 10, 5) / 2) < 1e-12
        audit = json.loads((Path(tmp) / "planet_parameters.audit.json").read_text())
        assert audit["batch_id"] == "msgbatch_1"


def test_batch_errors_and_cancelling():
    with patch.object(api_client, "BATCH_POLL_SECONDS", (0.01, 0.01)), tempfile.TemporaryDirectory() as tmp:
        broke = SimpleNamespace(type="errored", error=SimpleNamespace(error=SimpleNamespace(
            type="invalid_request_error", message="Your credit balance is too low to access the Anthropic API.")))
        ctx = _ctx(tmp, FakeBatches(broke))
        ctx.usage.append(SimpleNamespace(stage="structure_planner"))
        try:
            api_client.call_structured(ctx, stage="planet_parameters", system_prompt="s", user_content="u",
                                       response_model=Answer)
        except errors.OutOfCreditsError as e:
            assert e.stage == "planet_parameters" and e.finished == ["structure_planner"]
            assert "structure_planner" in str(e) and str(tmp) in str(e) and "Billing" in str(e)
        else:
            raise AssertionError("an out-of-credits batch result must stop the run")
        try:
            api_client.call_structured(_ctx(tmp, FakeBatches(SimpleNamespace(type="expired"))), stage="fit_models",
                                       system_prompt="s", user_content="u", response_model=Answer)
        except errors.BatchExpiredError as e:
            assert "24-hour" in str(e)
        else:
            raise AssertionError("an expired batch request must say so")
        cancel = threading.Event()
        cancel.set()
        batches = FakeBatches(broke, polls=99)
        try:
            api_client.call_structured(_ctx(tmp, batches, cancel), stage="fit_models", system_prompt="s",
                                       user_content="u", response_model=Answer)
        except errors.RunCancelledError:
            assert batches.cancelled == ["msgbatch_1"]          # the queued batch is cancelled too
        else:
            raise AssertionError("cancelling must stop the wait")


def test_the_cached_paper_lives_an_hour_in_batch_mode():
    paper = api_client.PaperContext(text="paper", images=[])
    assert api_client._paper_blocks(paper, long_lived=True)[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert api_client._paper_blocks(paper)[-1]["cache_control"] == {"type": "ephemeral"}
    # prices: 1-hour writes at 2x input, batch halves everything
    assert abs(request_cost("claude-sonnet-5-5", 0, 0, cache_write_1h_tokens=1_000_000) - 4.0) < 1e-9
    assert abs(request_cost("claude-sonnet-5-5", 1_000_000, 1_000_000, batch=True) - 6.0) < 1e-9


def _status_error(cls, status, message, kind):
    response = SimpleNamespace(status_code=status, headers={}, request=SimpleNamespace(method="POST"))
    return cls(message, response=response, body={"type": "error", "error": {"type": kind, "message": message}})


def test_running_out_of_credits_mid_run():
    """A direct (non-batch) run whose credits run out at the planet step: the error says where."""
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    cases = [(anthropic.BadRequestError, 400, "Your credit balance is too low to access the Anthropic API. "
                                              "Please go to Plans & Billing to upgrade or purchase credits.",
              "invalid_request_error"),
             (anthropic.APIStatusError, 402, "There's an issue with your billing.", "billing_error"),
             (anthropic.RateLimitError, 429, "You have reached your monthly spend cap.", "rate_limit_error")]
    try:
        for cls, status, message, kind in cases:
            replay = make_replay(REF)

            def send(ctx, **kw):
                if kw["response_model"].__name__ == "PlanetParametersResult":
                    raise _status_error(cls, status, message, kind)
                return replay(ctx, **kw)
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, \
                    patch.object(api_client, "_send", send), \
                    patch.object(api_client, "_streamed", threading.local()):
                try:
                    run_pipeline(PDF, RunConfig.from_settings(api_key="x", output_dir=Path(tmp), pack="exoplanets"))
                except errors.OutOfCreditsError as e:
                    assert e.stage == "planet_parameters" and "structure_planner" in e.finished, e.finished
                    assert e.run_dir is not None and Path(e.run_dir).is_dir()
                    assert "run out of credits" in str(e) and message in str(e)
                else:
                    raise AssertionError(f"{status}: must stop with an out-of-credits error")
        # an ordinary bad request isn't mistaken for credits
        assert not api_client._out_of_credits(400, "invalid_request_error", "messages: field required")
    finally:
        packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All batch / credit tests passed.")
