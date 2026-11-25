"""
Offline tests for answering for every parameter in a full run (parameter_checks.py; Mickey, 2026-11-24): off, the
steps' requests are as before; on, every configurable step's answer has a required `checked` entry per parameter and
its prompt says so, the chemistry step one per compound listed; after the run, what the model said is compared with
the values it gave (parameter_checks.csv, a flag per step with problems). No API calls.

Run with: python tests/test_parameter_checks.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import csv
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

import pack_facts as pf  # noqa: E402
from parameter_extractor import packs  # noqa: E402
from parameter_extractor import parameter_checks as pc  # noqa: E402
from parameter_extractor.stages.optional import for_run, load_specs  # noqa: E402


def _schema(model) -> dict:
    from anthropic.lib._parse._transform import transform_schema
    return transform_schema(model)


def _a_step():
    packs.activate("prebiotic_chemistry")
    spec = next(s for s in load_specs().values() if len(s.parameters) >= 3)
    return spec


def test_off_the_step_is_as_before_on_it_answers_for_every_parameter():
    spec = _a_step()
    plain, checking = for_run(spec), for_run(spec, check_all=True)
    assert plain.model_dump_json() == checking.model_dump_json()                   # nothing else changes, and the
    assert "check_columns" not in json.loads(checking.model_dump_json())           # field is never written to a file
    some = for_run(spec, check={spec.columns[1], "not_a_column"})                 # the pack's 'Must answer' columns
    assert some.check_columns == (spec.columns[1],)
    checks_some = next(d for n, d in _schema(some.models()[1])["$defs"].items() if n.endswith("Checks"))
    assert checks_some["required"] == [pc.check_keys([spec.columns[1]])[spec.columns[1]]]
    assert f"`{spec.columns[1]}`" in some.prompt_text("PAPER", "{}").split("EVERY PARAMETER CHECKED")[1]
    off = _schema(plain.models()[1])
    assert "checked" not in json.dumps(off)
    on = _schema(checking.models()[1])
    assert "checked" in on["required"] and json.dumps(on).count("anyOf") == json.dumps(off).count("anyOf")
    checks = next(d for n, d in on["$defs"].items() if n.endswith("Checks"))
    assert sorted(checks["required"]) == sorted(pc.check_keys(spec.columns).values())
    assert "EVERY PARAMETER CHECKED" in checking.prompt_text("PAPER", "{}")
    assert "EVERY PARAMETER CHECKED" not in plain.prompt_text("PAPER", "{}")
    # the answer loads, and its answers are read per column
    Result = checking.models()[1]
    keys = pc.check_keys(spec.columns)
    answer = Result.model_validate({"rows": [], "notes": "", "checked": {
        keys[c]: {"s": "reported" if i == 0 else "not reported", "n": "Methods"} for i, c in enumerate(spec.columns)}})
    got = pc.answers(answer, spec.columns)
    assert got[spec.columns[0]]["status"] == "reported" and got[spec.columns[1]]["status"] == "not reported"


def test_the_chemistry_step_answers_for_compound_columns():
    from parameter_extractor.config.run_config import RunConfig
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    from parameter_extractor.stages import chemistry_extractor as ce
    assert ce.answer_format(()) is ChemistryExtraction
    cols = ("initial_Gly_aq_mM", "sampled_Gly-Gly_aq_%yield")
    schema = _schema(ce.answer_format(cols))
    assert "checked" in schema["required"] and set(schema["$defs"]["ChemistryExtractionChecks"]["required"]) == \
        {"initial_Gly_aq_mM", "sampled_Gly-Gly_aq__yield"}
    plain = ce.prompt_text("PAPER", "{}", ["Gly"])
    asked = ce.prompt_text("PAPER", "{}", ["Gly"], check=cols)
    assert "COLUMNS TO ANSWER FOR" in asked and "starting concentration of Gly (dissolved)" in asked
    assert "COLUMNS TO ANSWER FOR" not in plain and plain == ce.prompt_text("PAPER", "{}", ["Gly"], check=())
    packs.activate("prebiotic_chemistry")                    # the run's own columns: only compound ones go here
    cfg = RunConfig.from_settings(api_key="x", check_columns=["initial_Gly_aq_mM", "initial_temperature_C"])
    assert ce.compound_checks(cfg) == ("initial_Gly_aq_mM",)


def test_answers_compared_with_the_values_given():
    spec = _a_step()
    checking = for_run(spec, check_all=True)
    Result = checking.models()[1]
    keys = pc.check_keys(spec.columns)
    c0, c1, c2 = spec.columns[:3]
    answer = Result.model_validate({"rows": [], "notes": "", "checked": {
        keys[c]: {"s": "not reported", "n": "-"} for c in spec.columns} | {
        keys[c0]: {"s": "reported", "n": "Table 1"}, keys[c1]: {"s": "not reported", "n": "-"},
        keys[c2]: {"s": "reported", "n": "Methods"}}})
    ctx = SimpleNamespace()
    pc.record(ctx, spec.name, answer, spec.columns)
    pc.record(ctx, spec.name, Result.model_validate({"rows": [], "notes": "", "checked": {
        keys[c]: {"s": "unclear", "n": "second pass"} for c in spec.columns}}), spec.columns)    # first pass kept
    assert ctx.parameter_checks[spec.name][c0]["status"] == "reported"
    item = lambda col: SimpleNamespace(parameter=col)                                          # noqa: E731
    result = SimpleNamespace(parameters=[item(c0), item(c1)])                    # c1 given, though not reported
    from parameter_extractor.schemas.chemistry import SoluteEntry
    gly = SoluteEntry(name="Gly", role="initial", phase="aq", concentration_value=5, concentration_unit_raw="mM")
    pc.record(ctx, "chemistry", SimpleNamespace(checked=None), ["initial_Gly_aq_mM"])     # no answers: nothing kept
    assert "chemistry" not in ctx.parameter_checks
    from parameter_extractor.stages import chemistry_extractor as ce
    chem_cols = ["initial_Gly_aq_mM", "sampled_Gly_aq_mM"]
    chem = ce.answer_format(tuple(chem_cols)).model_validate({"checked": {
        "initial_Gly_aq_mM": {"s": "reported", "n": "Table 1"}, "sampled_Gly_aq_mM": {"s": "reported", "n": "?"}}})
    pc.record(ctx, "chemistry", chem, chem_cols)
    ex = SimpleNamespace(optional={spec.name: (spec, result)}, chemistry=SimpleNamespace(solutes=[gly]))
    with tempfile.TemporaryDirectory() as tmp:
        flags = pc.finish(ctx, ex, Path(tmp))
        rows = {r["parameter"]: r for r in csv.DictReader(open(Path(tmp) / pc.CHECKS_FILE))}
    assert rows[c0]["problem"] == "" and rows[c0]["values"] == "1"
    assert "marked not reported" in rows[c1]["problem"]
    assert rows[c2]["problem"] == "marked reported, but no value given"
    with tempfile.TemporaryDirectory() as tmp:
        pc.finish(ctx, ex, Path(tmp))
        chem_rows = {r["parameter"]: r for r in csv.DictReader(open(Path(tmp) / pc.CHECKS_FILE)) if r["step"] == "chemistry"}
    assert chem_rows["initial_Gly_aq_mM"]["values"] == "1" and not chem_rows["initial_Gly_aq_mM"]["problem"]
    assert chem_rows["sampled_Gly_aq_mM"]["problem"] == "marked reported, but no value given"
    assert len(flags) == 2 and all(f.kind == "parameter_check" for f in flags) and c2 in flags[0].message
    assert pc.finish(SimpleNamespace(), ex, Path(".")) == []                     # not asked for: nothing written


def test_run_config_and_cli():
    from parameter_extractor.config.run_config import RunConfig
    cfg = RunConfig.from_settings(api_key="x")
    assert cfg.check_every_parameter is False and cfg.check_columns == []
    import os
    import subprocess
    out = subprocess.run([sys.executable, "-c", "import sys; from parameter_extractor.cli import main; "
                          "sys.argv = ['parameter-extract', '--help']; main()"], capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(ROOT / "src")}).stdout
    assert "--check-every-parameter" in out and "--check-column COLUMN" in out


def test_must_answer_columns_in_the_columns_tab():
    """The Columns tab (2026-11-25, Mickey): select columns, 'Must answer' marks them all (highlighted, saved as the
    pack's check_columns); a column no step or compound fills isn't marked; a run with the pack answers for them."""
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    from parameter_extractor.gui.pack_windows import PackEditor
    from parameter_extractor.gui.themes import MARKS
    from parameter_extractor.pack_editing import PackDraft
    with tempfile.TemporaryDirectory() as tmp, patch.object(packs, "user_packs_dir", lambda: Path(tmp)):
        pack = packs.create_pack("must_answer", "Must answer", base=Path(tmp))
        step_cols = [p["column"] for spec in PackDraft.load(pack.folder).stages.values() for p in spec["parameters"]]
        editor = PackEditor(pack.folder)
        editor.add_column_named("nothing_fills_this")
        items = []
        tree = editor.column_tree
        for i in range(tree.topLevelItemCount()):
            for item in editor._column_children(tree.topLevelItem(i)):
                if item.text(0) in step_cols[:2] or item.text(0) == "nothing_fills_this":
                    items.append(item)
        tree.clearSelection()
        for item in items:
            item.setSelected(True)
        shown = []
        with patch.object(QMessageBox, "information", lambda *a: shown.append(a[2])):
            editor._set_required(True)
        assert editor._required == set(step_cols[:2]) and shown and "nothing_fills_this" in shown[0]
        marked = [i for i in items if i.text(0) in step_cols[:2]]
        assert all(i.text(3) == "must answer" and i.background(0).color() == MARKS["must_answer"] for i in marked)
        assert editor.save()
        assert PackDraft.load(pack.folder).manifest["check_columns"] == sorted(step_cols[:2])
        packs.activate(pack.id)
        from parameter_extractor import pipeline
        from parameter_extractor.config.run_config import RunConfig
        assert pipeline._step_checks(RunConfig.from_settings(api_key="x")) == frozenset(step_cols[:2])
        spec = next(iter(load_specs(packs.current()).values()))
        asked = for_run(spec, check=pipeline._step_checks(RunConfig.from_settings(api_key="x")))
        assert set(asked.check_columns) == set(step_cols[:2]) & set(spec.columns)
        again = PackEditor(pack.folder)                                    # reopened: still marked
        assert again._required == set(step_cols[:2])
        tree.clearSelection()                                              # saving fills the tree again
        for i in range(tree.topLevelItemCount()):
            for item in editor._column_children(tree.topLevelItem(i)):
                if item.text(0) in step_cols[:2]:
                    assert item.text(3) == "must answer"                    # marked after the refill too
                    item.setSelected(True)
        editor._set_required(False)
        assert editor.save() and "check_columns" not in PackDraft.load(pack.folder).manifest
    packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All parameter-check tests passed.")
