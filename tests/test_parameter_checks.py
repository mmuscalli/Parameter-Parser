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
    plain, checking = for_run(spec), for_run(spec, check_every=True)
    assert plain.model_dump_json() == checking.model_dump_json()                   # nothing else changes, and the
    assert "check_every" not in json.loads(checking.model_dump_json())             # field is never written to a file
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


def test_the_chemistry_step_answers_for_the_compounds_listed():
    from parameter_extractor.schemas.chemistry import ChemistryExtraction
    from parameter_extractor.stages import chemistry_extractor as ce
    assert ce.answer_format(()) is ChemistryExtraction
    Model = ce.answer_format(("Gly", "Gly-Gly"))
    schema = _schema(Model)
    assert "checked" in schema["required"] and set(schema["$defs"]["ChemistryExtractionChecks"]["required"]) == \
        {"Gly", "Gly-Gly"}
    plain = ce.prompt_text("PAPER", "{}", ["Gly"])
    asked = ce.prompt_text("PAPER", "{}", ["Gly"], check=("Gly", "Gly-Gly"))
    assert "COMPOUNDS TO ANSWER FOR: Gly; Gly-Gly" in asked and "COMPOUNDS TO ANSWER FOR" not in plain
    assert plain == ce.prompt_text("PAPER", "{}", ["Gly"], check=())                # off: the same prompt


def test_answers_compared_with_the_values_given():
    spec = _a_step()
    checking = for_run(spec, check_every=True)
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
    ex = SimpleNamespace(optional={spec.name: (spec, result)}, chemistry=None)
    with tempfile.TemporaryDirectory() as tmp:
        flags = pc.finish(ctx, ex, Path(tmp))
        rows = {r["parameter"]: r for r in csv.DictReader(open(Path(tmp) / pc.CHECKS_FILE))}
    assert rows[c0]["problem"] == "" and rows[c0]["values"] == "1"
    assert "marked not reported" in rows[c1]["problem"]
    assert rows[c2]["problem"] == "marked reported, but no value given"
    assert len(flags) == 1 and flags[0].kind == "parameter_check" and c2 in flags[0].message
    assert pc.finish(SimpleNamespace(), ex, Path(".")) == []                     # not asked for: nothing written


def test_run_config_and_cli():
    from parameter_extractor.config.run_config import RunConfig
    cfg = RunConfig.from_settings(api_key="x")
    assert cfg.check_every_parameter is False and cfg.check_compounds == []
    import os
    import subprocess
    out = subprocess.run([sys.executable, "-c", "import sys; from parameter_extractor.cli import main; "
                          "sys.argv = ['parameter-extract', '--help']; main()"], capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(ROOT / "src")}).stdout
    assert "--check-every-parameter" in out and "--check-compound NAME" in out


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All parameter-check tests passed.")
