"""
A streamed answer cut off by the server or the network (2026-11-06, Mickey's Riggi2023 run: httpx
RemoteProtocolError "peer closed connection without sending complete message body" in the structure step,
shown as "a bug in the app"). Now the request is asked again (twice, after a short wait), then a NetworkError
naming the step. No API calls.

Run with: python tests/test_dropped_connection.py
"""
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx2 as httpx_mod                     # the HTTP stack the installed anthropic SDK uses

from parameter_extractor import api_client, errors


def _ctx():
    notes = []
    return SimpleNamespace(config=SimpleNamespace(handoff_dir=None), cancel_event=threading.Event(), usage=[],
                           note=lambda stage, msg: notes.append((stage, msg)), notes=notes)


def _dropping(times):
    calls = {"n": 0}

    def fake_send(ctx, model, **kwargs):
        calls["n"] += 1
        if calls["n"] <= times:
            raise httpx_mod.RemoteProtocolError("peer closed connection without sending complete message body "
                                                "(incomplete chunked read)")
        return "answer"
    return fake_send, calls


def test_recognised():
    assert api_client._dropped_connection(httpx_mod.RemoteProtocolError("x"))
    assert api_client._dropped_connection(httpx_mod.ReadTimeout("x"))
    assert not api_client._dropped_connection(ValueError("x"))


def test_asked_again_then_works():
    fake, calls = _dropping(2)
    ctx = _ctx()
    with patch.object(api_client, "_send", fake), patch.object(api_client, "STREAM_RETRY_WAITS", (0, 0)):
        assert api_client._send_mapping_errors(ctx, "structure_planner", "m") == "answer"
    assert calls["n"] == 3 and len(ctx.notes) == 2


def test_gives_up_with_a_plain_message():
    fake, calls = _dropping(10)
    with patch.object(api_client, "_send", fake), patch.object(api_client, "STREAM_RETRY_WAITS", (0, 0)):
        try:
            api_client._send_mapping_errors(_ctx(), "structure_planner", "m")
        except errors.NetworkError as e:
            assert "structure_planner" in str(e) and "broke off" in str(e)
        else:
            raise AssertionError("no NetworkError")
    assert calls["n"] == 3


def test_cancel_during_the_wait():
    fake, _ = _dropping(10)
    ctx = _ctx()
    ctx.cancel_event.set()
    with patch.object(api_client, "_send", fake):
        try:
            api_client._send_mapping_errors(ctx, "chemistry", "m")
        except errors.RunCancelledError:
            pass
        else:
            raise AssertionError("not cancelled")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS:", name)
    print("All dropped-connection tests passed.")
