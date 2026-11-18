"""
The cost and time estimate before a run (estimate.py, W4): which steps it counts, how it prices them for the run's
profile and mode, what it says when the price isn't known, and that showing it sends nothing. No API calls.

Run with: python tests/test_estimate.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import api_client, packs  # noqa: E402
from parameter_extractor.config.run_config import RunConfig  # noqa: E402
from parameter_extractor.estimate import Estimate, PaperInfo, estimate, planned_steps  # noqa: E402
from parameter_extractor.stages.optional import load_specs  # noqa: E402

PACK = "prebiotic_chemistry"


def _config(**changes):
    return replace(RunConfig(api_key="", output_dir=Path(tempfile.gettempdir()), pack=PACK), **changes)


def test_steps_counted_are_the_runs_own():
    packs.activate(PACK)
    config = _config()
    sure, maybe = planned_steps(config, "a paper with no trigger words at all")
    assert sure[:2] == ["structure_planner", "metadata"]
    specs = load_specs()
    for name, spec in specs.items():
        if spec.trigger.always:
            assert name in sure, name
        elif spec.trigger.keywords and not (spec.trigger.set_types or spec.trigger.sample_fields
                                            or spec.trigger.set_patterns):
            assert name not in sure + maybe, name          # keyword-only, and the paper lacks the words
    # switched off: never counted; switched on: always
    name = next(iter(specs))
    assert name not in sum(planned_steps(_config(optional_stages={name: "off"}), "x"), [])
    assert name in planned_steps(_config(optional_stages={name: "on"}), "x")[0]
    # an unread paper: every step that could run is a 'maybe'
    sure_unread, maybe_unread = planned_steps(config, None)
    assert set(maybe_unread) >= set(maybe)


def test_batch_halves_and_passes_and_figures_add():
    paper = [PaperInfo(text="no trigger words", figures=3)]
    plain = estimate(_config(), ["a.pdf"], papers=paper)
    batch = estimate(_config(batch_mode=True), ["a.pdf"], papers=paper)
    assert plain.cost_known and 0 < plain.cost_low < plain.cost_high
    assert abs(batch.cost_low - plain.cost_low / 2) < 1e-9 and batch.minutes_low > plain.minutes_low  # queue waits
    voted = estimate(_config(passes=3), ["a.pdf"], papers=paper)
    assert voted.cost_low > plain.cost_low
    figures = estimate(_config(auto_digitize_figures=True), ["a.pdf"], papers=paper)
    assert figures.cost_low > plain.cost_low
    assert any("figure suggestions you ask for" in n for n in plain.notes)
    many = estimate(_config(), ["a.pdf"] * 10, papers=paper * 10)
    assert abs(many.cost_low - 10 * plain.cost_low) < 1e-9 and many.papers == 10


def test_unknown_prices_and_private_servers():
    paper = [PaperInfo(text="x", figures=0)]
    unknown = estimate(_config(profile_roles={"*": "some-model-without-a-price", "structure_planner": "x",
                                              "metadata": "x"}), ["a.pdf"], papers=paper)
    assert not unknown.cost_known and "unknown cost" in unknown.text()
    private = estimate(_config(provider="local", local={"private": True, "model": "m"}), ["a.pdf"], papers=paper)
    assert private.cost_high == 0 and "no charge" in private.text() and any("local server" in n for n in private.notes)


def test_the_wording():
    e = Estimate(papers=1, cost_low=0.143, cost_high=0.41, minutes_low=3.2, minutes_high=7.5)
    assert e.text() == "About $0.14–0.41 and 3–8 minutes for this paper (estimate)"
    e = Estimate(papers=23, cost_low=4.2, cost_high=12.6, minutes_low=40, minutes_high=150)
    assert e.text() == "About $4.20–13 and 0.7–2.5 hours for these 23 papers (estimate)"


def test_estimate_only_sends_nothing():
    from parameter_extractor import cli

    def no_send(*a, **k):
        raise AssertionError("the estimate sent a request")
    with tempfile.TemporaryDirectory() as tmp:
        argv = ["parameter-extract", "--paper", "2401.00001", "--estimate-only", "--out", tmp]
        with patch.object(api_client, "_send", no_send), patch.object(sys, "argv", argv), \
                patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            assert cli.main() == 0
        assert not any(Path(tmp).iterdir())             # no run folder either


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All estimate tests passed.")
