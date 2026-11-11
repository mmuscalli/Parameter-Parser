"""
Locally hosted models (local_models.py, 2026-11-08): a fake Ollama / OpenAI-compatible server answers with eder1994's
recorded answers; the run must reproduce the reference CSV byte for byte, with no API key, prompt caching or batches,
and with the requests in the server's format (schema constraint, context length, images only for vision models).
Also: profiles -> models, settings file, refusing a paper that won't fit, an unreachable server, one request at a time.
No network beyond 127.0.0.1, no API.
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QCheckBox

os.environ.setdefault("PARAMETER_EXTRACTOR_NO_KEYCHAIN", "1")      # never the real keychain (macOS asks)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pack_facts as pf  # noqa: E402
from parameter_extractor import errors, local_models, packs
from parameter_extractor.config.run_config import RunConfig

REF = ROOT / "runs" / "reference" / "eder1994"
PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Initial Easy Papers" / "Eder1994" / "eder1994.pdf"


class FakeServer:
    """Answers each step with the reference run's recorded output (by the X-Parameter-Extractor-Step header)."""

    def __init__(self, kind: str, delay: float = 0.0):
        self.kind, self.delay, self.requests, self.active, self.most_at_once = kind, delay, [], 0, 0
        server = self
        lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = ({"models": [{"name": "fake:12b"}]} if self.path == "/api/tags"
                        else {"data": [{"id": "fake-model"}]})
                self._send(json.dumps(body).encode())

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/show":
                    self._send(json.dumps({"capabilities": ["completion", "vision"],
                                           "model_info": {"gemma3.context_length": 131072}}).encode())
                    return
                stage = self.headers.get("X-Parameter-Extractor-Step", "")
                with lock:
                    server.requests.append((self.path, stage, req))
                    server.active += 1
                    server.most_at_once = max(server.most_at_once, server.active)
                time.sleep(server.delay)
                out = REF / f"{stage}.output.json"
                answer = out.read_text() if out.is_file() else "{}"     # steps the reference run didn't have
                if server.kind == "ollama":
                    lines = [{"message": {"content": answer[:10]}, "done": False},
                             {"message": {"content": answer[10:]}, "done": True, "done_reason": "stop",
                              "prompt_eval_count": 1234, "eval_count": 56}]
                    payload = b"".join(json.dumps(x).encode() + b"\n" for x in lines)
                else:
                    events = [{"choices": [{"delta": {"content": answer}, "finish_reason": "stop"}]},
                              {"choices": [], "usage": {"prompt_tokens": 1234, "completion_tokens": 56}}]
                    payload = b"".join(b"data: " + json.dumps(x).encode() + b"\n\n" for x in events) \
                        + b"data: [DONE]\n\n"
                with lock:
                    server.active -= 1
                self._send(payload)

            def _send(self, data: bytes):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()


def _local(server: FakeServer, model: str, vision: bool, parallel: int = 1) -> dict:
    return local_models.LocalSettings(
        kind=server.kind, url=server.url, parallel=parallel, timeout_sec=30,
        models={model: local_models.LocalModel(context=131072, vision=vision)},
        profiles={"Local standard": {"structure_planner": model, "*": model, "figure_planner": model}}).to_dict()


def _run(server, model, vision, out, parallel=1):
    from parameter_extractor.pipeline import run_pipeline
    cfg = RunConfig.from_settings(api_key="", output_dir=out, provider="local", model_profile="Local standard",
                                  local=_local(server, model, vision, parallel), use_pubchem=False,
                                  registry_path=None)
    try:
        return run_pipeline(PDF, cfg)
    finally:
        packs.activate("prebiotic_chemistry")


def test_ollama_run_reproduces_the_reference():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}")
        return
    server = FakeServer("ollama")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(server, "fake:12b", vision=True, out=Path(tmp))
            assert result.csv_path.read_text() == (REF / "expected_extracted.csv").read_text(), pf.why_replay_differs()
            assert any(f.kind == "local_model" and "fake:12b" in f.message for f in result.paper_flags)
            summary = json.loads((result.run_dir / "run_summary.json").read_text())
            assert summary["provider"] == "local" and summary["estimated_cost_usd"] == 0
            assert not summary["config"]["prompt_caching"] and not summary["config"]["batch_mode"]
            paths = {p for p, _, _ in server.requests}
            assert paths == {"/api/chat"}
            stages = [s for _, s, _ in server.requests]
            assert {"structure_planner", "chemistry", "experimental_conditions"} <= set(stages)
            chem = next(r for _, s, r in server.requests if s == "chemistry")
            assert chem["options"]["num_ctx"] == 131072 and chem["format"]["type"] == "object"
            assert chem["messages"][1].get("images"), "a vision model gets the table images"
            assert "JSON Schema" in chem["messages"][0]["content"]
            assert server.most_at_once == 1                     # one request at a time by default
    finally:
        server.close()


def test_openai_compatible_run_without_vision():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}")
        return
    server = FakeServer("openai")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(server, "fake-model", vision=False, out=Path(tmp))
            assert result.csv_path.read_text() == (REF / "expected_extracted.csv").read_text(), pf.why_replay_differs()
            chem = next(r for _, s, r in server.requests if s == "chemistry")
            assert chem["response_format"]["type"] == "json_schema"
            assert all(part["type"] == "text" for part in chem["messages"][1]["content"])   # images left out
            assert {p for p, _, _ in server.requests} == {"/v1/chat/completions"}
    finally:
        server.close()


def test_parallel_requests_and_listing():
    server = FakeServer("ollama", delay=0.3)
    try:
        local = local_models.LocalSettings.from_dict(_local(server, "fake:12b", True, parallel=2))
        listed = local_models.list_models(local)
        assert listed == [{"name": "fake:12b", "vision": True, "max_context": 131072}]
        ctx = type("Ctx", (), {"config": RunConfig.from_settings(api_key="", output_dir=Path("."), provider="local",
                                                                 local=local.to_dict()),
                               "cancel_event": None, "note": lambda *a: None})()
        from parameter_extractor.schemas.paper_metadata import PaperMetadata
        from parameter_extractor.api_client import _streamed
        _streamed.max_tokens = 4000
        threads = [threading.Thread(target=local_models.send, args=(ctx, "metadata", "fake:12b"),
                                    kwargs=dict(system_prompt="s", content="c", response_model=PaperMetadata))
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert server.most_at_once == 2
    finally:
        server.close()


def test_profiles_settings_and_refusals():
    local = {"profiles": {"Fast": {"*": "small", "structure_planner": "big"}}}
    cfg = RunConfig.from_settings(api_key="", output_dir=Path("."), provider="local", model_profile="Fast", local=local)
    assert cfg.model_for("structure_planner") == "big" and cfg.model_for("chemistry") == "small"
    assert cfg.model_for("figure_planner") == "small" and not cfg.needs_api_key
    assert RunConfig.from_settings(api_key="", output_dir=Path(".")).needs_api_key
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "local_models.json"
        s = local_models.LocalSettings(models={"m": local_models.LocalModel(context=8192, vision=True)},
                                       profiles={"P": {"*": "m"}}, api_key="secret")
        local_models.save(s, path)
        assert "secret" not in path.read_text()
        back = local_models.load(path)
        assert back.models["m"].context == 8192 and back.profiles == {"P": {"*": "m"}}
    pub = RunConfig.from_settings(api_key="", output_dir=Path("."), provider="local",
                                  local={"api_key": "secret", "profiles": {}}).to_public_dict()
    assert "secret" not in json.dumps(pub)
    # a paper too long for the model's context is refused with a clear message, before anything is sent
    ctx = type("Ctx", (), {"config": RunConfig.from_settings(
        api_key="", output_dir=Path("."), provider="local",
        local={"url": "http://127.0.0.1:9", "models": {"m": {"context": 4096}}}), "cancel_event": None})()
    from parameter_extractor.schemas.paper_metadata import PaperMetadata
    try:
        local_models.send(ctx, "metadata", "m", system_prompt="s", content="x" * 40000, response_model=PaperMetadata)
        raise AssertionError("expected a refusal")
    except errors.PipelineError as e:
        assert "context" in str(e)
    ctx.config.local["models"]["m"]["context"] = 65536                 # fits now -- but nothing listens on :9
    try:
        local_models.send(ctx, "metadata", "m", system_prompt="s", content="x", response_model=PaperMetadata)
        raise AssertionError("expected unreachable")
    except errors.PipelineError as e:
        assert "Couldn't reach" in str(e)


def test_models_window_sets_up_a_local_run():
    """Settings > Model provider: Test connection lists the server's models, a profile is added, the main window's
    Models list shows it, a run needs no API key, batch mode is off; the settings file is written on close."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("ParameterExtractorTests")
    QSettings().clear()
    from parameter_extractor.gui import main_window
    from test_gui_offline import FakeKeyStore
    server = FakeServer("ollama")
    keys = FakeKeyStore()
    try:
        with tempfile.TemporaryDirectory() as tmp, patch.object(main_window, "key_store", keys):
            from parameter_extractor.gui.models_window import ModelsWindow
            w = main_window.MainWindow()
            w.out_edit.setText(tmp)
            w.registry_path = Path(tmp) / "registry.json"
            w.models_path = Path(tmp) / "model_profiles.json"
            w._refresh_profiles()
            assert w.profile_combo.currentData() == "standard" and w.batch_box.isEnabled()
            m = ModelsWindow(w, store=w._model_store(), keys=keys, tab="connections")
            m.add_server("ollama", name="Local server")
            m.url_edit.setText(server.url)
            assert m.test_connection() and m._conn().models and list(m._conn().models) == ["fake:12b"]
            assert m.models_table.cellWidget(0, 2).findChild(QCheckBox).isChecked()      # vision from /api/show
            m.new_profile(m._conn_id, label="Local 1")
            assert m.role_combos["*"].currentText() == "fake:12b"
            m.save()
            w._refresh_profiles()
            index = w.profile_combo.findData("local-1")
            assert index >= 0 and "Local server" in w.profile_combo.itemText(index)
            w.profile_combo.setCurrentIndex(index)
            assert not w.batch_box.isEnabled()
            w.papers.add_items([PDF])
            assert w.run_btn.isEnabled()                         # no Anthropic key needed
            cfg = w.current_config()
            assert cfg.provider == "local" and cfg.model_for("chemistry") == "fake:12b" and not cfg.batch_mode
            assert cfg.local["url"] == server.url and cfg.temperature == 0.0
            saved = json.loads((Path(tmp) / "model_profiles.json").read_text())
            assert saved["profiles"]["local-1"]["roles"]["*"] == "fake:12b"
            w.profile_combo.setCurrentIndex(w.profile_combo.findData("standard"))
            assert w.batch_box.isEnabled() and not w.run_btn.isEnabled()      # the API needs its key again
            w.close()
    finally:
        server.close()
        QSettings().clear()


def test_text_values_a_local_model_must_give():
    """qwen3.8:27b on eder1994 (2026-11-10) named experiment_type / solution_type but left their text out (v = 0):
    local requests now require `txt`; an empty text value is reported, never skipped; the flag shows no '= 0'."""
    from parameter_extractor.stages.optional import load_specs, stage_values
    spec = pf.pack("prebiotic_chemistry")
    conditions = load_specs(spec)["experimental_conditions"]
    Item, Result = conditions.models()
    schema = local_models.answer_schema(Result)
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "txt" in (node.get("properties") or {}):
                found.append("txt" in (node.get("required") or []))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(schema)
    assert found and all(found)                                  # required in every configurable step's values
    from parameter_extractor.schemas.analysis import AnalysisResult
    analysis = []
    walk_into = found
    found = analysis
    walk(local_models.answer_schema(AnalysisResult))
    found = walk_into
    assert analysis and not any(analysis)      # not in the analysis step's settings: qwen then wrote numbers as text
    # the sample (planet) of a row: qwen3.8:27b left it out on teng2023 -> every value counted for the whole system
    from parameter_extractor.stages.optional import load_specs as _specs
    _, planet = _specs(pf.pack("exoplanets"))["planet_parameters"].models()
    rows = []

    def rows_of(node):
        if isinstance(node, dict):
            props = node.get("properties") or {}
            if "set" in props and "sample" in props:
                rows.append("sample" in (node.get("required") or []))
            for v in node.values():
                rows_of(v)
        elif isinstance(node, list):
            for v in node:
                rows_of(v)
    rows_of(local_models.answer_schema(planet))
    assert rows and all(rows)
    from anthropic.lib._parse._transform import transform_schema
    from parameter_extractor.api_client import model_facing_schema
    assert "txt" not in json.dumps(model_facing_schema(transform_schema(Result)).get("required", []))  # Claude: as before
    item = Item.model_validate({"col": "experiment_type", "v": 0, "u": "", "q": "heated in a glass flask",
                                "src": "Experimental", "c": "medium", "n": "heated in place = Batch"})
    values, problems = stage_values(conditions, item)
    assert values == {} and problems and "gave no text" in problems[0] and "= Batch" in problems[0]
    ok = Item.model_validate({"col": "experiment_type", "v": 0, "u": "", "txt": "batch", "q": "q", "src": "s",
                              "c": "high"})
    assert stage_values(conditions, ok)[0]["experiment_type"].value == "Batch"
    # the confidence flag says the text is missing instead of '= 0'
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    from parameter_extractor.schemas.methodology import empty_methodology
    from parameter_extractor.validation.plausibility_checks import check_extraction
    result = Result.model_validate({"rows": [{"set": "", "sample": "", "values": [
        {"col": "experiment_type", "v": 0, "u": "", "q": "q", "src": "s", "c": "medium"}]}], "notes": "", "other": []})
    flags = check_extraction(empty_methodology("p"), ChemistryExtraction(), optional=[(conditions, result)])
    shown = [f.message for f in flags if "experiment_type" in f.message]
    assert shown and "(no text given)" in shown[0] and "= 0 " not in shown[0], shown


def test_analysis_numbers_given_as_text():
    """qwen3.8:27b (2026-11-10, with `txt` required) wrote HPLC settings as text: '200', '0.35'. A number setting
    answered with one number (and maybe its unit) in the text is read as that number, in the setting's unit."""
    from types import SimpleNamespace
    from parameter_extractor import analysis_vocab as av
    from parameter_extractor.calculators.analysis_columns import _value
    packs.activate(pf.linked("prebiotic_chemistry", "analysis").id)
    try:
        vocab = av.vocabulary()
        spec = next(st for _, settings in vocab.families.values() for st in settings if st.name == "flow-rate")
        s = lambda text: SimpleNamespace(value=0.0, unit="", high=0.0, text=text)
        value, unit, _, note, problem = _value(s("0.35"), spec)
        assert value == 0.35 and unit == spec.unit and "no unit printed" in note and not problem
        value, unit, _, _, problem = _value(s("350 µL/min"), spec)
        assert abs(value - 0.35) < 1e-9 and not problem
        value, _, _, _, problem = _value(s("fast, about 0.35"), spec)       # not just a number: kept as text
        assert value == "fast, about 0.35" and problem == "given as text"
    finally:
        packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
