"""
Offline tests for the developer-only handoff mode (handoff.py, dev_features.py): requests written to a
folder, answered there (here: copied from eder1994's reference run, as a Claude Code session would
write them), the paper run again round by round, and the result identical to the reference CSV. Also:
off unless the developer switch is set; a bad answer is reported, not used. No API calls.

Run with: python tests/test_handoff.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import dev_features, packs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.errors import AnswersNeededError, PipelineError
from parameter_extractor.pipeline import run_pipeline

REF = ROOT / "runs" / "reference" / "eder1994"
PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Initial Easy Papers" / "eder1994" / "eder1994.pdf"
DEV = {dev_features.ENV_VAR: "1"}


def _config(tmp: Path) -> RunConfig:
    return RunConfig(api_key="", output_dir=tmp / "out", handoff_dir=tmp / "handoff", registry_path=None)


def _answer_all(err: AnswersNeededError) -> list:
    """Answer every request from the reference run's recorded answers (by step name)."""
    stages = []
    for key in err.keys:
        stage = key.rsplit("-", 1)[0]
        shutil.copy(REF / f"{stage}.output.json", Path(err.folder) / "answers" / f"{key}.json")
        stages.append(stage)
    return sorted(stages)


def test_off_without_the_developer_switch():
    with patch.dict(os.environ, {dev_features.ENV_VAR: ""}):
        assert not dev_features.enabled()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                run_pipeline(PDF, _config(Path(tmp)))
            except PipelineError as e:
                assert "developer-only" in str(e)
            else:
                raise AssertionError("handoff ran without the developer switch")


def test_rounds_of_requests_reproduce_the_reference_run():
    if not (PDF.is_file() and REF.is_dir()):
        print("SKIP: needs eder1994.pdf and runs/reference/eder1994"); return
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, DEV):
        tmp, config = Path(tmp), _config(Path(tmp))
        rounds = []
        for _ in range(4):
            try:
                result = run_pipeline(PDF, config)
                break
            except AnswersNeededError as e:
                folder = Path(e.folder)
                assert (folder / "README.md").is_file() and (folder / "paper.txt").stat().st_size > 10000
                for key in e.keys:
                    request = (folder / "requests" / f"{key}.md").read_text()
                    assert f"answers/{key}.json" in request and "## Answer schema" in request
                    assert "calling the" not in request                  # no tool talk in a handoff request
                rounds.append(_answer_all(e))
        else:
            raise AssertionError("never finished")
        packs.activate("prebiotic_chemistry")
        assert rounds == [["metadata", "structure_planner"], ["chemistry", "experimental_conditions"]], rounds
        assert any((folder / "images").iterdir())                         # table pages, for reading tables
        assert result.csv_path.read_text() == (REF / "expected_extracted.csv").read_text()
        assert result.cost_usd in (None, 0)                               # nothing billed


def test_an_answer_that_does_not_fit_is_reported():
    if not PDF.is_file():
        print(f"SKIP: needs {PDF}"); return
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, DEV):
        config = _config(Path(tmp))
        try:
            run_pipeline(PDF, config)
        except AnswersNeededError as e:
            key = next(k for k in e.keys if k.startswith("structure_planner"))
            (Path(e.folder) / "answers" / f"{key}.json").write_text('{"experiment_sets": "not a list"}')
        try:
            run_pipeline(PDF, config)
        except AnswersNeededError as e:
            assert key in e.invalid and "didn't fit" in str(e)
            assert (Path(e.folder) / "answers" / f"{key}.error.txt").is_file()
        else:
            raise AssertionError("a broken answer was accepted")


def test_settings_show_the_developer_section_only_with_the_switch():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from parameter_extractor.gui.settings_dialog import SettingsDialog
    with patch.dict(os.environ, {dev_features.ENV_VAR: ""}):
        d = SettingsDialog()
        assert d.handoff_box is None and d.handoff_dir() is None        # public: not there at all
    with patch.dict(os.environ, DEV):
        d = SettingsDialog()
        d.handoff_edit.setText("/tmp/handoff")
        assert d.handoff_dir() is None                                  # off until ticked
        d.handoff_box.setChecked(True)
        assert str(d.handoff_dir()) == "/tmp/handoff"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All handoff tests passed.")
