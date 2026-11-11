"""
Offline tests for model profiles and connections (model_profiles.py, gui/models_window.py; 2026-11-11): the defaults
send Claude exactly the requests they did before; changed and user-made profiles, server connections, prices,
temperature, the old local_models.json brought over, the command line, and the Models window.

Run with: python tests/test_model_profiles.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client, local_models  # noqa: E402
from parameter_extractor import model_profiles as mp  # noqa: E402
from parameter_extractor.config.run_config import RunConfig  # noqa: E402
from parameter_extractor.pipeline import stage_order  # noqa: E402
from parameter_extractor.pricing import request_cost  # noqa: E402
from parameter_extractor.schemas.paper_metadata import PaperMetadata  # noqa: E402

STAGES = list(stage_order()) + ["triage", "methodology", "chemistry", "experimental_conditions", "kinetics",
                                "figure_planner", "equations", "metadata", "structure_planner"]


def _config(**kw) -> RunConfig:
    return RunConfig(api_key="sk-test", output_dir=Path("/tmp"), **kw)


def _store(tmp) -> mp.ModelStore:
    return mp.ModelStore(Path(tmp) / "model_profiles.json")


class _Stream:
    """messages.stream stand-in: records the request, answers nothing useful."""
    def __init__(self, sink, kwargs):
        sink.append(kwargs)
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def __iter__(self):
        return iter(())
    def get_final_message(self):
        return SimpleNamespace(content=[], stop_reason="end_turn", parsed_output=None, id="x",
                               usage=SimpleNamespace(input_tokens=0, output_tokens=0))


def _request(config: RunConfig, stage: str = "metadata") -> dict:
    sink = []
    client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: _Stream(sink, kw)))
    ctx = SimpleNamespace(config=config, client=client)
    api_client._send(ctx, model=config.model_for(stage), system_prompt="sys", content="text",
                     response_model=PaperMetadata)
    request = sink[0]
    request["output_format"] = request["output_format"].__name__
    return request


def test_the_defaults_are_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        for key in ("standard", "balanced", "economy"):
            before = _config(model_profile=key)                # as runs were configured before profiles
            after = mp.apply(_config(), key, store)
            assert after.profile_roles == {} and after.provider == "anthropic"
            assert [before.model_for(s) for s in STAGES] == [after.model_for(s) for s in STAGES], key
            assert (after.max_tokens, after.temperature, after.max_parallel_stages, after.max_retries,
                    after.prompt_caching) == (before.max_tokens, None, before.max_parallel_stages, 5, True)
            for stage in ("metadata", "chemistry", "structure_planner"):
                assert _request(before, stage) == _request(after, stage)
            assert "temperature" not in _request(after)
            # the roles written out pick the same models (the starting point of a changed copy)
            explicit = _config(model_profile=key, profile_roles=mp.builtin_roles(key))
            assert [before.model_for(s) for s in STAGES] == [explicit.model_for(s) for s in STAGES], key


def test_changing_and_resetting_a_default():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        p = store.profile("economy")
        p.roles["structure_planner"] = "claude-sonnet-5-5"
        p.temperature = 0.2
        p.parallel_steps = 3
        store.update(p)
        store.save()
        again = _store(tmp)
        assert again.is_changed("economy")
        assert again.builtin_changes["economy"] == {"temperature": 0.2, "parallel_steps": 3,
                                                    "roles": {"structure_planner": "claude-sonnet-5-5"}}
        cfg = mp.apply(_config(), "economy", again)
        assert cfg.model_for("structure_planner") == "claude-sonnet-5-5" and cfg.model_for("chemistry") == \
            "claude-haiku-5-5" and cfg.max_parallel_stages == 3
        assert _request(cfg)["temperature"] == 0.2
        again.reset("economy")
        assert not again.is_changed("economy") and mp.apply(_config(), "economy", again).profile_roles == {}


def test_own_claude_profile_with_prices_for_an_unknown_model():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        p = store.add_profile("Opus planner", copy_of="standard")
        p.roles.update(structure_planner="claude-opus-5-5", **{"*": "claude-future-9"})
        p.prices = {"claude-future-9": {"input": 3.0, "output": 15.0}}
        p.retries = 2
        store.update(p)
        cfg = mp.apply(_config(), p.id, store)
        assert cfg.model_for("structure_planner") == "claude-opus-5-5"
        assert cfg.model_for("chemistry") == "claude-future-9" and cfg.model_for("kinetics") == "claude-future-9"
        assert cfg.model_for("metadata") == "claude-haiku-5-5" and cfg.max_retries == 2
        assert request_cost("claude-future-9", 1_000_000, 1_000_000, prices=cfg.prices) == 18.0
        assert request_cost("claude-future-9", 1_000_000, 0) is None          # unknown without the profile's prices


def test_server_profiles_local_and_hosted():
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        local = store.add_connection("Lab GPU", "ollama", "http://192.168.1.129:11434")
        local.models["qwen3.8:27b"] = mp.ServerModel(context=131072, vision=True)
        hosted = store.add_connection("OpenRouter", "openai", "https://openrouter.ai/api")
        hosted.models["some/model"] = mp.ServerModel(context=200000)
        hosted.models["priced/model"] = mp.ServerModel(context=200000, price_input=1.0, price_output=4.0)
        lp = store.add_profile("Qwen", local.id)
        assert lp.roles["*"] == "qwen3.8:27b" and lp.temperature == 0.0
        cfg = mp.apply(_config(), lp.id, store, key="")
        assert cfg.provider == "local" and not cfg.prompt_caching and not cfg.batch_mode
        assert cfg.model_for("chemistry") == "qwen3.8:27b" and cfg.local["url"] == local.url
        assert local_models.server_cost(cfg, "qwen3.8:27b", 10_000, 1_000) == 0.0             # private: free
        assert "locally hosted" in local_models.flag_text(cfg)
        hp = store.add_profile("Hosted", hosted.id)
        hp.roles = {r: "some/model" for r, _ in mp.ROLES}
        hp.roles["*"] = "priced/model"
        cfg = mp.apply(_config(), hp.id, store, key="sk-or")
        assert cfg.local["api_key"] == "sk-or" and cfg.local["private"] is False
        assert local_models.server_cost(cfg, "some/model", 10_000, 1_000) is None              # hosted, no price
        assert local_models.server_cost(cfg, "priced/model", 1_000_000, 1_000_000) == 5.0
        assert "on OpenRouter" in local_models.flag_text(cfg)
        hp.roles["*"] = "missing/model"
        assert store.problems(hp) and "missing/model" in store.problems(hp)[0]
        try:
            mp.apply(_config(), hp.id, store)
            raise AssertionError("a profile naming a model the server doesn't have should be refused")
        except Exception as e:
            assert "can't run" in str(e)
        store.save()
        again = _store(tmp)
        assert again.connection(hosted.id).models["priced/model"].price_output == 4.0
        assert again.remove_connection(local.id) == ["Qwen"] and again.profile(lp.id) is None


def test_the_old_local_settings_are_brought_over():
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp) / "local_models.json"
        old.write_text(json.dumps({"kind": "ollama", "url": "http://192.168.1.129:11434", "timeout_sec": 900,
                                   "parallel": 1, "models": {"qwen3.8:27b": {"context": 131072, "vision": True}},
                                   "profiles": {"qwen": {"structure_planner": "qwen3.8:27b", "*": "qwen3.8:27b",
                                                         "figure_planner": "qwen3.8:27b"}}}))
        with patch.object(local_models, "default_path", lambda: old):
            store = _store(tmp)
        assert store.migrated_from == old
        conn = store.connection("local")
        assert conn.name == "Local server" and conn.models["qwen3.8:27b"].context == 131072
        assert conn.account == "local-model-server"                   # the key stays where it was
        assert store.profile("qwen").roles["*"] == "qwen3.8:27b"
        cfg = mp.apply(_config(), "qwen", store)
        assert cfg.model_for("equations") == "qwen3.8:27b" and cfg.model_for("metadata") == "qwen3.8:27b"


def test_command_line_models_option():
    from parameter_extractor import cli
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(tmp)
        p = store.add_profile("Opus planner", copy_of="standard")
        p.roles["structure_planner"] = "claude-opus-5-5"
        store.update(p)
        store.save()
        parser = argparse.ArgumentParser()
        with patch.object(mp, "default_path", lambda: Path(tmp) / "model_profiles.json"):
            out = cli._provider_overrides(SimpleNamespace(provider="anthropic", models=p.id, no_cache=False), parser)
            assert out["profile_roles"]["structure_planner"] == "claude-opus-5-5" and out["provider"] == "anthropic"
            assert cli._provider_overrides(SimpleNamespace(provider="anthropic", models=None, no_cache=True),
                                           parser)["prompt_caching"] is False
            cfg = RunConfig.from_settings(api_key="x", output_dir=Path(tmp), **out)
            assert cfg.model_for("structure_planner") == "claude-opus-5-5"
            assert cli._list_models() == 0


def test_the_models_window():
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setOrganizationName("ParameterExtractorTests")
    app = QApplication.instance() or QApplication([])
    from parameter_extractor.gui import main_window
    from parameter_extractor.gui.models_window import ModelsWindow
    from test_gui_offline import FakeKeyStore
    with tempfile.TemporaryDirectory() as tmp:
        QSettings().clear()
        keys = FakeKeyStore()
        with patch.object(main_window, "key_store", keys):
            w = main_window.MainWindow()
        w.models_path = Path(tmp) / "model_profiles.json"
        w._refresh_profiles()
        m = ModelsWindow(w, store=w._model_store(), keys=keys)
        m.select_profile("standard")
        assert not m.role_combos["*"].isEnabled() and m.unlock_btn.isVisibleTo(m)       # locked until confirmed
        assert "tested default" in m.note_label.text()
        m._confirm_change = lambda label: False                         # Cancel: still locked
        m.unlock()
        assert not m.role_combos["*"].isEnabled()
        m._confirm_change = lambda label: True
        m.unlock()
        assert m.role_combos["*"].isEnabled()
        m.role_combos["*"].setCurrentText("claude-haiku-5-5")
        assert m.store.is_changed("standard") and "Changed from the tested default" in m.note_label.text()
        assert "changed" in m.profile_list.currentItem().text() and m.reset_btn.isEnabled()
        m.role_combos["*"].setCurrentText("claude-unknown-1")           # a model without a known price
        assert m.prices_box.isVisibleTo(m) and m.prices_table.rowCount() == 1
        m.prices_table.cellWidget(0, 1).setValue(2.5)
        assert m.store.profile("standard").prices["claude-unknown-1"]["input"] == 2.5
        m.reset_profile()
        assert not m.store.is_changed("standard") and not m.role_combos["*"].isEnabled()
        m.new_profile(mp.ANTHROPIC, label="Opus everywhere")
        for combo in m.role_combos.values():
            combo.setCurrentText("claude-opus-5-5")
        m.temp_box.setChecked(True)
        m.temp_spin.setValue(0.3)
        # a hosted server with a key
        m.tabs.setCurrentIndex(1)
        m.add_server("openai", name="University server")
        m.url_edit.setText("https://llm.example.edu")
        m.conn_key_edit.setText("sk-uni")
        m.add_model("big/model")
        assert m.models_table.rowCount() == 1
        m.save()
        assert m.saved and keys.other.get("model-connection:university-server") == "sk-uni"
        w._refresh_profiles()
        labels = [w.profile_combo.itemText(i) for i in range(w.profile_combo.count())]
        assert any(t.startswith("Opus everywhere") for t in labels), labels
        w.profile_combo.setCurrentIndex(w.profile_combo.findData("opus-everywhere"))
        cfg = w.current_config()
        assert cfg.model_for("metadata") == "claude-opus-5-5" and cfg.temperature == 0.3 and w.batch_box.isEnabled()
        saved = json.loads((Path(tmp) / "model_profiles.json").read_text())
        assert "university-server" in saved["connections"] and "sk-uni" not in json.dumps(saved)   # key: keychain
        w.close()
        app.processEvents()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All model profile tests passed.")
