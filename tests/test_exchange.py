"""
Requests for another assistant (exchange.py, 2026-11-19): a paper's requests exported as a package (nothing sent),
answered outside the app, imported back into a normal run. The 'other assistant' here answers with the eder1994
reference run's recorded answers, so the import must reproduce that run's dataset exactly. No API calls.

Run with: python tests/test_exchange.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import json
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor import exchange  # noqa: E402
from parameter_extractor.errors import AnswersNeededError  # noqa: E402
from test_pipeline_offline import PDF, REPLAY_DIR, _config, _have_inputs  # noqa: E402

BRANDS = re.compile(r"claude|anthropic|chatgpt|openai|gemini|copilot", re.IGNORECASE)


def _no_key(out: Path):
    """No API key at all: an export sends nothing."""
    from parameter_extractor.config.run_config import RunConfig
    return RunConfig.from_settings(api_key="", output_dir=out)


def _answer_like_the_reference(folder: Path, skip_conditional: bool = True) -> None:
    """The recorded answers of the reference run, as another assistant would have written them."""
    from parameter_extractor.stages.conditions_migration import conditions_from_methodology
    for r in exchange.read_package(folder)["requests"]:
        if r["figure"]:                                      # suggestions for figures: optional, not answered
            continue
        src = REPLAY_DIR / f"{r['stage']}.output.json"
        if r["stage"] == "experimental_conditions":        # recorded under the step's earlier name
            text = json.dumps(conditions_from_methodology(json.loads((REPLAY_DIR / "methodology.output.json")
                                                                      .read_text())))
        elif r["conditional"] and skip_conditional:
            text = '{"skipped": true}'
        else:
            text = src.read_text() if src.is_file() else "{}"     # a step added after the recording: found nothing
        (folder / r["answer"]).write_text(text)
    (folder / "answers" / exchange.ABOUT_FILE).write_text(json.dumps(
        {"model": "example-model 2", "provider": "an example", "assistant": "a test", "date": "2026-11-19"}))


def test_export_writes_a_package_nothing_is_sent():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _no_key(Path(tmp) / "runs")
        folder = exchange.export_package(PDF, cfg, Path(tmp) / "out")
        m = exchange.read_package(folder)
        stages = [r["stage"] for r in m["requests"]]
        assert stages[:2] == ["structure_planner", "metadata"] and len(stages) > 3
        assert [r["n"] for r in m["requests"]] == list(range(1, len(stages) + 1))
        assert m["pdf"] == PDF.name and (folder / PDF.name).is_file() and (folder / "paper.txt").stat().st_size > 1000
        assert m["data_pack"] == "prebiotic_chemistry" and not (folder / ".run").exists()
        for r in m["requests"]:
            text = (folder / r["request"]).read_text()
            assert r["answer"] in text and "Answer format (JSON Schema)" in text
            assert "(a set)" not in text and "(a sample)" not in text           # the stand-in plan never shows
            marks = exchange.ROW_PLAN_MARK in text or exchange.ROW_PLAN_ANSWER_MARK in text
            assert marks == r["uses_row_plan"]
            assert exchange.PAPER_MARK in text or r["stage"] in ("metadata", "figure_planner")   # once, in paper.txt
            assert not BRANDS.search(text)
        assert all(r["uses_row_plan"] for r in m["requests"][2:])
        shared = {f: (folder / f).read_text() for f in (exchange.SHARED_FILE, exchange.SHARED_OPTIONAL_FILE)
                  if (folder / f).is_file()}
        assert m["shared"] == sorted(shared) and exchange.SHARED_FILE in shared
        for r in m["requests"]:                                  # every pointer has its section
            exchange.expand_shared((folder / r["request"]).read_text(), shared)
        guide = (folder / exchange.INSTRUCTIONS_FILE).read_text()
        assert "Work economically" in guide and exchange.SHARED_FILE in guide
        assert "in their numbered order" in guide and exchange.ROW_PLAN_MARK in guide and "about.json" in guide
        assert not BRANDS.search(guide)
        assert not list((folder / "answers").glob("*.json"))


def test_repeated_text_is_shared_and_reads_back_exactly():
    """share_blocks on any requests: repeated paragraphs and runs of list items go to SHARED.md (or
    SHARED-OPTIONAL.md when only optional requests use them); expanding the pointers gives each request back exactly."""
    rules = ["- Only values the paper states, never a typical value; " + "x" * 160,
             "- Keep every quote to the shortest span that shows the value; " + "y" * 160]
    big = "BIG BLOCK " + "z" * 400
    docs = {"requests/01-a.md": "# A\n\nRules:\n" + "\n".join(rules + ["- A's own rule"]) + "\n\n" + big,
            "requests/02-b.md": "# B\n\nRules:\n" + "\n".join(["- B's own rule"] + rules) + "\n\n" + big,
            "requests/03-c.md": "# C\n\nshort text",
            "requests/04-fig.md": "# F\n\n" + "FIG " + "f" * 400,
            "requests/05-fig.md": "# G\n\n" + "FIG " + "f" * 400}
    out, shared = exchange.share_blocks(docs, optional={"requests/04-fig.md", "requests/05-fig.md"})
    assert set(shared) == {exchange.SHARED_FILE, exchange.SHARED_OPTIONAL_FILE}
    assert "BIG BLOCK" in shared[exchange.SHARED_FILE] and "FIG" in shared[exchange.SHARED_OPTIONAL_FILE]
    assert "BIG BLOCK" not in out["requests/01-a.md"] and out["requests/03-c.md"] == docs["requests/03-c.md"]
    assert "A's own rule" in out["requests/01-a.md"] and "Only values" not in out["requests/02-b.md"]
    for path, text in docs.items():
        assert exchange.expand_shared(out[path], shared) == text, path
    assert exchange.share_blocks({"requests/01-a.md": "nothing repeats " * 40}) == \
        ({"requests/01-a.md": "nothing repeats " * 40}, {})


def test_import_reproduces_the_run_and_says_who_answered():
    if not _have_inputs():
        return
    with tempfile.TemporaryDirectory() as tmp:
        folder = exchange.export_package(PDF, _no_key(Path(tmp) / "runs"), Path(tmp) / "out")
        m = exchange.read_package(folder)
        try:                                                            # nothing answered: every needed one listed
            exchange.import_package(folder, _config(Path(tmp) / "imp"))
            raise AssertionError("imported without answers")
        except AnswersNeededError as e:
            assert set(e.keys) == {Path(r["answer"]).stem for r in m["requests"]
                                   if not r["conditional"] and not r["figure"]}
        _answer_like_the_reference(folder)
        broken = folder / m["requests"][1]["answer"]                    # an answer that doesn't fit its format
        good = broken.read_text()
        broken.write_text('{"title": 5, "authors": "nobody"}')
        try:
            exchange.import_package(folder, _config(Path(tmp) / "imp"))
            raise AssertionError("imported a broken answer")
        except AnswersNeededError as e:
            assert e.invalid == [broken.stem] and broken.with_suffix(".error.txt").is_file()
        broken.write_text(good)
        result = exchange.import_package(folder, _config(Path(tmp) / "imp"))
        assert result.csv_path.read_text() == (REPLAY_DIR / "eder1994_auto_extracted.csv").read_text()
        assert not broken.with_suffix(".error.txt").exists()
        audit = json.loads((result.run_dir / "chemistry.audit.json").read_text())
        assert audit["model"] == "example-model 2 (a test)"
        flags = [f for f in result.paper_flags if f.kind == "other_assistant"]
        assert flags and "example-model 2" in flags[0].message
        assert json.loads((result.run_dir / "run_config.json").read_text())["config"]["exchange_dir"] == str(folder)


def test_figures_are_optional_requests():
    """Each figure the paper has: an optional request for digitizing suggestions (after the steps), answered from the
    package on import when its assistant answered it, else 'digitize it by hand'."""
    riggi = Path(__file__).resolve().parents[2] / "Paper Files" / "Test Paper List" / "Riggi2023.pdf"
    if not riggi.is_file():
        print(f"SKIP: needs {riggi}"); return
    from parameter_extractor.errors import PipelineError
    from parameter_extractor.schemas.figures import FigurePlan
    with tempfile.TemporaryDirectory() as tmp:
        folder = exchange.export_package(riggi, _no_key(Path(tmp) / "runs"), Path(tmp) / "out")
        m = exchange.read_package(folder)
        figures = [r for r in m["requests"] if r["figure"]]
        steps = [r for r in m["requests"] if not r["figure"]]
        assert figures and m["requests"][-len(figures):] == figures and not any(r["conditional"] for r in figures)
        shared = {f: (folder / f).read_text() for f in m["shared"]}
        text = exchange.expand_shared((folder / figures[0]["request"]).read_text(), shared)
        assert exchange.SHARED_OPTIONAL_FILE in m["shared"]                 # parts only figures use: apart
        assert exchange.ROW_PLAN_ANSWER_MARK in text and "(a set)" not in text and "**Optional.**" in text
        assert "images/" in text and Path(figures[0]["request"]).name.startswith(f"{figures[0]['n']:02d}-figure-")
        missing = exchange.missing_answers(folder)
        assert set(missing) == {Path(r["answer"]).stem for r in steps if not r["conditional"]}   # figures: never
        answer = FigurePlan(figure_id=figures[0]["figure"], is_data_plot=False, plot_kind="other",
                            duplicates_tabulated_data=False)
        (folder / figures[0]["answer"]).write_text(answer.model_dump_json(by_alias=True))
        got = exchange._answer_from_package(folder, "figure_planner", figures[0]["name"], FigurePlan)
        assert got.parsed_output.figure_id == figures[0]["figure"]
        try:
            exchange._answer_from_package(folder, "figure_planner", figures[1]["name"], FigurePlan)
            raise AssertionError("an unanswered figure gave suggestions")
        except PipelineError as e:
            assert "digitize it by hand" in str(e)


def test_cli_and_window():
    from parameter_extractor import cli
    import inspect
    assert "--export-requests" in inspect.getsource(cli.main) and "--import-answers" in inspect.getsource(cli.main)
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.main_window import MainWindow
    w = MainWindow()
    texts = [a.text() for a in w.menuBar().actions()[0].menu().actions()]
    assert "Export requests for another assistant…" in texts and "Import answers from another assistant…" in texts
    assert not any(BRANDS.search(t) for t in texts)
    from PySide6.QtWidgets import QApplication
    from parameter_extractor.gui.exchange_dialogs import copy_paths
    with tempfile.TemporaryDirectory() as tmp:                 # the new package's path, ready to paste
        assert copy_paths([Path(tmp) / "eder1994"]) == str((Path(tmp) / "eder1994").resolve())
        assert QApplication.clipboard().text() == str((Path(tmp) / "eder1994").resolve())
    w.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All exchange tests passed.")
