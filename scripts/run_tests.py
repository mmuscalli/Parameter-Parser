"""
Runs the test suite in parallel (2026-11-04): every tests/test_*.py file in its own process (they're independent:
each writes only to temporary folders; the GUI tests keep their preferences under their own QSettings name), a few
at a time, slowest first. Prints each file's time, then any FAILED (non-zero exit) and SKIPPED files (a SKIP prints
but exits 0 -- e.g. a paper's PDF moved), with the end of their output. Exit code 1 when anything failed or skipped.

Run with:  python scripts/run_tests.py             (all files, one worker per CPU core)
           python scripts/run_tests.py -j 4 pipeline reference   (4 workers; only files whose name contains a word)
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMES = ROOT / "tests" / ".last_times.json"     # last run's time per file: the slowest start first next time


def run(path: Path) -> dict:
    start = time.time()
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run([sys.executable, str(path)], cwd=ROOT, env=env, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    return {"file": path.name, "seconds": round(time.time() - start, 1), "code": proc.returncode,
            "skipped": "SKIP" in out, "tail": "\n".join(out.strip().splitlines()[-8:])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4, help="files run at once")
    parser.add_argument("words", nargs="*", help="only test files whose name contains one of these")
    args = parser.parse_args()
    files = sorted((ROOT / "tests").glob("test_*.py"))
    if args.words:
        files = [f for f in files if any(w in f.name for w in args.words)]
    last = json.loads(TIMES.read_text()) if TIMES.is_file() else {}
    files.sort(key=lambda f: -last.get(f.name, 60))     # long ones first: the run ends sooner
    start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for future in as_completed([pool.submit(run, f) for f in files]):
            r = future.result()
            results.append(r)
            mark = "FAIL" if r["code"] else "SKIP" if r["skipped"] else "ok"
            print(f"{mark:>4}  {r['seconds']:6.1f} s  {r['file']}", flush=True)
    if not args.words:
        TIMES.write_text(json.dumps({r["file"]: r["seconds"] for r in results}, indent=1))
    failed = [r for r in results if r["code"]]
    skipped = [r for r in results if r["skipped"] and not r["code"]]
    for label, group in (("FAILED", failed), ("SKIPPED", skipped)):
        for r in group:
            print(f"\n== {label}: {r['file']}\n{r['tail']}")
    print(f"\n{len(results)} files in {time.time() - start:.0f} s ({args.jobs} at a time): "
          f"{len(results) - len(failed) - len(skipped)} passed, {len(failed)} failed, {len(skipped)} skipped")
    return 1 if failed or skipped else 0


if __name__ == "__main__":
    sys.exit(main())
