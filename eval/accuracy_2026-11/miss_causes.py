"""Why an arm misses model-standard values in quantities its pack HAS a column for (P1, reviewed), each miss given the
first cause that fits (2026-11-22, Mickey: sort the misses by cause):

  elsewhere      the arm has the value, under another of its columns (naming, unit or role differ)
  near           the arm has a value in that column within 10 % (CLOSE), not within the tolerance
  not printed    the standard's number isn't printed in the paper's text (derived, converted or calculated)
  other rows     the arm records that quantity for the paper, but not this value (a row or entry it doesn't have)
  not recorded   the arm records nothing in that column for the paper

Usage: PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 python miss_causes.py ARM [arms.json]
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import score as S

arm = sys.argv[1]
cfg = json.loads(Path(sys.argv[2] if len(sys.argv) > 2 else "arms.json").read_text())
ms_runs = S.runs_of(cfg["model_standard"]["P1"], "P1")
runs = S.runs_of(cfg["arms"][arm]["batches"]["P1"], "P1")
loaded = {k: S.rows_of(f) for k, f in runs.items()}
families = {S.family(c)[0] for k, f in runs.items() for c in S.as_archive_columns(loaded[k], f).columns}
causes, by_family, examples = Counter(), defaultdict(Counter), defaultdict(list)
for key, folder in sorted(ms_runs.items()):
    if key not in runs:
        continue
    av = S._values(S.as_archive_columns(S.with_review(loaded[key], runs[key]), runs[key]))
    numbers_anywhere = {a for _t, an, _at in av.values() for a in an}
    pdf = S.BATCHES["P1"][key]["pdf"]
    printed = [v for v, _dec in S.printed_with_decimals(S.paper_text(Path(pdf)), None)]
    for fam, (tol, mn, mt) in S._values(S.with_review(S.rows_of(folder), folder)).items():
        if fam not in families:
            continue                                   # no column: column_gaps.py
        _t, an, at = av.get(fam, (tol, set(), set()))
        missed = [m for m in mn if not any(S.close(m, a, tol) for a in an)] + \
                 [t for t in mt if not S._text_hit(t, at)]
        for m in missed:
            if isinstance(m, float) and any(S.close(m, a, tol) for a in numbers_anywhere):
                cause = "elsewhere"
            elif isinstance(m, float) and any(S.close(m, a, S.CLOSE) for a in an):
                cause = "near"
            elif isinstance(m, float) and not any(S.close(abs(m), p, (0.005, 0.0)) for p in printed):
                cause = "not printed"
            elif an or at:
                cause = "other rows"
            else:
                cause = "not recorded"
            causes[cause] += 1
            by_family[cause][fam] += 1
            if len(examples[cause]) < 12:
                examples[cause].append((key, fam, m))
print(f"{arm}: {sum(causes.values())} missed values in columns the pack has")
for cause, n in causes.most_common():
    print(f"\n{cause}: {n}   by column: {dict(by_family[cause].most_common(8))}")
    for e in examples[cause]:
        print("   ", e)
