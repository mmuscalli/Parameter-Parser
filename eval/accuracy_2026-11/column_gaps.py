"""Which model-standard values (P1, reviewed) an arm misses because its pack has no column for them, by family.

Usage: PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 python column_gaps.py ARM[,ARM] [arms.json]   (2026-11-22)
"""
import json, re, sys
from collections import Counter, defaultdict
import score as S
cfg = json.load(open(sys.argv[2] if len(sys.argv) > 2 else "arms.json"))
ms_runs = S.runs_of(cfg["model_standard"]["P1"], "P1")
compound = re.compile(r"^(initial|sampled|stock|calculated)_.+_(aq|gas|solid)_")
for arm in sys.argv[1].split(","):
    runs = S.runs_of(cfg["arms"][arm]["batches"]["P1"], "P1")
    loaded = {k: S.rows_of(f) for k, f in runs.items()}
    fams = {S.family(c)[0] for k, f in runs.items() for c in S.as_archive_columns(loaded[k], f).columns}
    miss, kind, total, found = Counter(), {}, 0, 0
    for key, folder in ms_runs.items():
        if key not in runs: continue
        av = S._values(S.as_archive_columns(S.with_review(loaded[key], runs[key]), runs[key]))
        for fam, (tol, mn, mt) in S._values(S.with_review(S.rows_of(folder), folder)).items():
            n = len(mn) + len(mt); total += n
            _t, an, at = av.get(fam, (tol, set(), set()))
            hit = sum(any(S.close(m, a, tol) for a in an) for m in mn) + sum(S._text_hit(t, at) for t in mt)
            found += hit
            if fam not in fams:
                miss[fam] += n
    print(f"== {arm}: MS values {total}, found {found}; in families the pack has no column for: {sum(miss.values())}")
    groups = Counter()
    for fam, n in miss.items():
        g = "compound" if compound.search(fam) else "analysis" if fam.startswith("analysis_") else "other"
        groups[g] += n
    print("  by kind:", dict(groups))
    for fam, n in miss.most_common(40):
        print(f"   {n:4d} {fam}")
