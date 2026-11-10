"""
Checks that the test suite doesn't depend on the exact contents of the app's own data packs (2026-11-09). Runs the whole
suite (scripts/run_tests.py) once per variation, each a change someone might make to a data pack, then restores the
files and reports which test files failed:

  link      Prebiotic links every app module
  unlink    Prebiotic without the Mineral surfaces and Flow reactor modules
  new       a new always-on module (its own step, column and category) linked to both app packs
  analysis  Prebiotic without the Analysis methods module

Only the files changed here are touched (the two app packs' pack.json, a temporary modules/zz_probe folder); the run
refuses to start while those have uncommitted changes, and puts them back with `git checkout` afterwards (also after
Ctrl+C). Expect 0 failures in every variation. Unlinking a module that the reference runs were recorded with
(tests/pack_facts.RECORDED_WITH: kinetics, wet_dry, ...) fails the replays ON PURPOSE -- their outputs really
change; their message says so.

Run with:  python scripts/check_test_robustness.py              (all variations, ~2 min each)
           python scripts/check_test_robustness.py new unlink   (only these)
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PE = ROOT / "src" / "parameter_extractor"
PREBIOTIC = PE / "packs" / "prebiotic_chemistry" / "pack.json"
EXOPLANETS = PE / "packs" / "exoplanets" / "pack.json"
PROBE = PE / "modules" / "zz_probe"


def _modules(path: Path) -> list:
    return json.loads(path.read_text()).get("modules", [])


def _set_modules(path: Path, mods: list) -> None:
    text = path.read_text()
    listed = json.dumps(mods)
    if re.search(r'"modules": \[[^\]]*\]', text):
        text = re.sub(r'"modules": \[[^\]]*\]', lambda _m: '"modules": ' + listed, text, count=1)
    else:
        text = text.replace("{", '{\n  "modules": ' + listed + ",", 1)
    path.write_text(text)
    assert _modules(path) == mods


def _probe_module() -> None:
    (PROBE / "stages").mkdir(parents=True)
    (PROBE / "module.json").write_text(json.dumps({
        "id": "zz_probe", "label": "Probe module", "description": "A test module.", "covers": "Probe values.",
        "version": 1, "evidence": {"words": ["probe"]},
        "variable_categories": [{"id": "zz_probe", "table_order": 33, "label": "Probe", "value_type": "any",
                                 "model_assigns": True, "description": "Probe values."}],
        "category_columns": {"zz_probe": {"columns": ["zz_probe_value_C"]}}}, indent=2))
    (PROBE / "stages" / "zz_probe.json").write_text(json.dumps({
        "name": "zz_probe", "label": "Probe values", "description": "Probe.", "origin": "probe stage",
        "schema_name": "ZzProbe", "trigger": {"always": True}, "per": "sample", "set_word": "experiment set",
        "intro": "Record probe values.", "parameters": [
            {"column": "zz_probe_value_C", "unit": "°C", "description": "A probe temperature."},
            {"column": "zz_probe_note", "kind": "text", "description": "A probe note."}], "rules": []}, indent=2))


def _all_app_modules() -> list:
    return sorted(p.parent.name for p in (PE / "modules").glob("*/module.json") if p.parent.name != "zz_probe")


VARIATIONS = {
    "link": lambda: _set_modules(PREBIOTIC, list(dict.fromkeys(_modules(PREBIOTIC) + _all_app_modules()))),
    "unlink": lambda: _set_modules(PREBIOTIC, [m for m in _modules(PREBIOTIC)
                                               if m not in ("mineral_surfaces", "flow_reactor")]),
    "new": lambda: (_probe_module(), _set_modules(PREBIOTIC, ["zz_probe"] + _modules(PREBIOTIC)),
                    _set_modules(EXOPLANETS, _modules(EXOPLANETS) + ["zz_probe"])),
    "analysis": lambda: _set_modules(PREBIOTIC, [m for m in _modules(PREBIOTIC) if m != "analysis"]),
}


def _restore() -> None:
    subprocess.run(["git", "checkout", "--", str(PREBIOTIC), str(EXOPLANETS)], cwd=ROOT, check=True)
    shutil.rmtree(PROBE, ignore_errors=True)


def main() -> int:
    chosen = sys.argv[1:] or list(VARIATIONS)
    unknown = [c for c in chosen if c not in VARIATIONS]
    if unknown:
        print(f"unknown variation(s) {unknown}; choose from {list(VARIATIONS)}")
        return 2
    dirty = subprocess.run(["git", "status", "--porcelain", "--", str(PREBIOTIC), str(EXOPLANETS)], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    if dirty or PROBE.exists():
        print("The app packs' pack.json files have uncommitted changes (or modules/zz_probe exists): commit or "
              "stash them first -- this check restores those files with git.\n" + dirty)
        return 2
    results = {}
    try:
        for name in chosen:
            VARIATIONS[name]()
            proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_tests.py")], cwd=ROOT,
                                  capture_output=True, text=True)
            _restore()
            failed = re.findall(r"FAIL\s+[\d.]+ s\s+(\S+)", proc.stdout)
            summary = next((l for l in proc.stdout.splitlines() if " passed, " in l), "no summary")
            results[name] = failed
            print(f"{name:>9}: {summary}" + (f"\n           failed: {', '.join(failed)}" if failed else ""),
                  flush=True)
    finally:
        _restore()
    return 1 if any(results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
