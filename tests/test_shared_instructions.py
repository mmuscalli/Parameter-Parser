"""
Every step's static instructions in the cached system prompt, before the paper (2026-11-07, structural change (2) of
the cost discussion): the tool list + system prompt are identical for every paper of a pack, so a queue's later
papers read them from the cache. Each step's request then carries only its paper-specific part (the structure
plan). Replays two reference papers and records the requests; no API calls.

Run with: python tests/test_shared_instructions.py
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.pipeline import run_pipeline
from test_pipeline_offline import make_replay

REF = ROOT / "runs" / "reference"
PAPERS = ROOT.parent / "Paper Files" / "Paper Lists"


def _requests(name: str, pdf: Path, **cfg):
    sent = []
    replay = make_replay(REF / name)

    def record(ctx, **kw):
        sent.append({"stage": api_client._streamed.stage, "system": kw["system_prompt"], "content": kw["content"],
                     "tools": getattr(api_client._streamed, "tool", None)})
        return replay(ctx, **kw)
    with tempfile.TemporaryDirectory() as tmp, patch.object(api_client, "_send", record):
        result = run_pipeline(pdf, RunConfig.from_settings(api_key="replay", output_dir=Path(tmp), registry_path=None,
                                                           use_pubchem=False, **cfg))
        csv = result.csv_path.read_text()
    return sent, csv


def _last_text(content) -> str:
    return content[-1]["text"] if isinstance(content, list) else content


def test_steps_send_only_their_paper_specific_part():
    pdf = PAPERS / "Initial Easy Papers/Eder1994/eder1994.pdf"
    if not pdf.is_file():
        print("SKIP: eder1994.pdf"); return
    sent, csv = _requests("eder1994", pdf, shared_instructions=True)
    shared = [r for r in sent if r["tools"]]
    assert {r["stage"] for r in shared} >= {"structure_planner", "chemistry", "experimental_conditions", "analysis"}
    for r in shared:
        text = _last_text(r["content"])
        assert f"Follow the instructions for step `{r['stage']}`" in text, r["stage"]
        assert "Answer format" not in text and len(text) < 15000, (r["stage"], len(text))   # not the whole prompt
    systems = {str(r["system"]) for r in shared}
    assert len(systems) == 1                                # one system prompt for every step: one cached prefix
    system = shared[0]["system"][0]
    assert system["cache_control"]["type"] == "ephemeral" and "### STEP `chemistry`" in system["text"]
    # the same CSV as without shared instructions
    _, plain = _requests("eder1994", pdf, shared_instructions=False)
    assert csv == plain


def test_the_cached_prefix_is_the_same_for_another_paper():
    a, b = PAPERS / "Initial Easy Papers/Eder1994/eder1994.pdf", PAPERS / "Kim2019/kim2019.pdf"
    if not (a.is_file() and b.is_file()):
        print("SKIP: eder1994 / kim2019 PDFs"); return
    first = [r for r in _requests("eder1994", a, shared_instructions=True)[0] if r["tools"]][0]
    second = [r for r in _requests("kim2019", b, shared_instructions=True)[0] if r["tools"]][0]
    assert first["system"] == second["system"] and first["tools"][1] == second["tools"][1]


def test_automatic_setting():
    """None (the default): off for a single paper, on in a queue."""
    from parameter_extractor.paper_queue import PaperQueue
    pdf = PAPERS / "Initial Easy Papers/Eder1994/eder1994.pdf"
    if not pdf.is_file():
        print("SKIP: eder1994.pdf"); return
    sent, _ = _requests("eder1994", pdf)
    assert all(isinstance(r["system"], str) for r in sent)          # single run: the plain shared line
    with tempfile.TemporaryDirectory() as tmp:
        q = PaperQueue([pdf], RunConfig.from_settings(api_key="x", output_dir=Path(tmp)))
        assert q.config.shared_instructions is True and q._warm


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS:", name)
    print("All shared-instruction tests passed.")
