"""Accuracy evaluation helper: for one paper, the hand dataset's printed values of a quantity the run doesn't have,
next to the run's values of that quantity (validation of the model standard, and of arms).
Usage: python inspect_misses.py RUN_FOLDER PAPER_KEY [QUANTITY ...]"""
import json, re, sys
from pathlib import Path
import score as S

run_dir, key = Path(sys.argv[1]), sys.argv[2]
wanted = set(sys.argv[3:])
meta = S.BATCHES["P1"][key]
hand = S.pd.read_csv(json.loads((S.HERE / "arms_test.json").read_text())["hand_csv"], encoding="utf-8-sig", dtype=str,
                     keep_default_na=False)
hd = hand[hand.full_id.str[:3] == meta["hand_id"]]
run = S.with_review(S.rows_of(run_dir), run_dir)
raw = S.paper_text(Path(meta["pdf"]))
for k, (hpat, rpat, factors, tol) in S.NUMERIC.items():
    if wanted and k not in wanted:
        continue
    numbers = S.printed_with_decimals(raw, S.UNIT_AFTER.get(k))
    hv = {}
    for c in hd.columns:
        if re.search(hpat, c) and not S.THERMO.search(c) and not S.CHARGED.search(c):
            for v in S.numeric_values(hd[c]):
                hv.setdefault(v, set()).add(c)
    rv = {}
    for c in run.columns:
        if re.search(rpat, c) and not S.RUN_EXCLUDE.search(c):
            for v in S.numeric_values(run[c]):
                rv.setdefault(v, set()).add(c)
    printed = {v for v in hv if S.is_printed_exact(v, factors, numbers)}
    missed = [v for v in printed if not any(S.close(v, r, S.CLOSE) for r in rv)]
    if missed:
        print(f"== {k}: missed {[(v, sorted(hv[v])) for v in sorted(missed)]}")
        print(f"   run has {[(v, sorted(c)) for v, c in sorted(rv.items())][:12]}")
for col in ("vessel_material", "solid_material_name"):
    if col in hd and (not wanted or "text" in wanted):
        print(col, "hand:", sorted(set(hd[col]) - {""}), "run:", sorted(set(run[col].dropna())) if col in run else "-")
