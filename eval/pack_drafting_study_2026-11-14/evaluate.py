"""Pack study evaluation: each pack's rows per paper against the hand-built dataset (PaperDataTemplate.xlsx).

Per paper and concept (temperature, duration, pH, starting amino-acid concentration, product yields): the DISTINCT
values the hand dataset has vs the run's. recall = share of hand values the run has (within tolerance); precision =
share of the run's values found in the hand data. Column names differ between packs, so each concept is found by
pattern (drafted packs use the app's naming conventions when tidied). Also: rows, cost, flags, status.

Usage: python evaluate.py STUDY_DIR SCRATCH_DIR  -> per_paper.csv, summary.json in SCRATCH_DIR
"""
import csv
import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

STUDY, SP = Path(sys.argv[1]), Path(sys.argv[2])
PACKS = ["peptide_pack_5", "peptide_pack_25", "peptide_pack_56", "prebiotic_chemistry"]
hand = pd.read_pickle(SP / "hand.pkl")
hand_map = json.loads((SP / "hand_map.json").read_text())
samples = json.loads((STUDY / "samples.json").read_text())
SCANNED = {"Flores1973", "Inoue1993", "Rabinowitz1969"}
AA = ["Gly", "Ala", "Val", "Leu", "Ile", "Phe", "Asp", "Glu", "His", "Ser", "Thr", "Trp", "Met", "Pro", "Lys", "Arg",
      "Cys", "Tyr", "Asn", "Gln", "Gly-Gly", "Ala-Ala", "Gly-Ala"]

EXCLUDE = re.compile(r"^(analysis_|sampled_|quench|stock_|calculated_)|_(err_plus|err_minus|range|log10|ln)(_|$)")


def num(v):
    try:
        x = float(str(v).replace(",", "").strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def columns_for(concept, header):
    """The columns that hold a concept, best first (the app's convention names, then drafted variants)."""
    h = list(header)
    if concept == "temperature":
        first = [c for c in h if c == "initial_temperature_C"]
        rest = [c for c in h if re.search(r"(^|_)(reaction_|heating_|incubation_)?temperature_C$", c)
                and not EXCLUDE.search(c) and c not in first and not re.search(r"dry|wet|quench|cool", c)]
        return first + rest
    if concept == "duration":
        first = [c for c in h if c == "duration_hr"]
        rest = [c for c in h if re.search(r"(^|_)(reaction_|heating_|incubation_)?(time|duration)_hr$", c)
                and not EXCLUDE.search(c) and c not in first and not re.search(r"cycle|dry|wet|residence|half", c)]
        return first + rest
    if concept == "pH":
        return [c for c in h if c in ("initial_pH",)] + [c for c in h if re.search(r"(^|_)pH$", c)
                                                           and not EXCLUDE.search(c) and c != "initial_pH"
                                                           and not re.search(r"final|sampled|buffer", c)]
    if concept == "aa_conc":
        # the hand dataset's older names have no phase ('initial_Gly_mM'); the app's have '_aq_'
        return [c for c in h if re.match(rf"^initial_({'|'.join(map(re.escape, AA))})(_aq)?_mM$", c)]
    if concept == "yield":
        return [c for c in h if re.search(r"yield", c, re.I) and not re.search(r"_(err_plus|err_minus|range|log10|ln)"
                                                                           r"(_|$)", c)
                and not re.search(r"^calculated_", c)]
    return []


TOL = {"temperature": (0.0, 1.0), "duration": (0.02, 0.01), "pH": (0.0, 0.15), "aa_conc": (0.03, 0.0),
       "yield": (0.03, 0.05)}


def close(a, b, concept):
    rel, ab = TOL[concept]
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), ab)


def values(df, concept):
    out = set()
    for c in columns_for(concept, df.columns):
        for v in df[c]:
            x = num(v)
            if x is not None and not (concept == "yield" and x == 0):
                out.add(round(x, 6))
    return out


def score(hv, rv, concept):
    if not hv:
        return None, None
    recall = sum(any(close(h, r, concept) for r in rv) for h in hv) / len(hv)
    precision = (sum(any(close(r, h, concept) for h in hv) for r in rv) / len(rv)) if rv else None
    return recall, precision


def queue_dir(pack):
    found = sorted((STUDY / f"runs_{pack}").glob("queue_*"))
    return found[-1] if found else None


CONCEPTS = ["temperature", "duration", "pH", "aa_conc", "yield"]
rows = []
for pack in PACKS:
    q = queue_dir(pack)
    if q is None or not (q / "papers.csv").is_file():
        continue
    papers = list(csv.DictReader(open(q / "papers.csv", encoding="utf-8")))
    combined = pd.read_csv(q / "combined_extracted.csv", dtype=str) if (q / "combined_extracted.csv").is_file() \
        else pd.DataFrame()
    for p in papers:
        name = Path(p["item"]).parent.name
        hid = hand_map.get(name)
        run = combined[combined.full_id.str[:3] == p["prefix"]] if len(combined) else pd.DataFrame()
        hd = hand[hand.paper == hid] if hid else pd.DataFrame()
        rec = {"pack": pack, "paper": name, "hand_id": hid or "", "status": p["status"],
               "rows": len(run), "hand_rows": len(hd), "n_flags": num(p.get("flags")) or 0,
               "cost": num(p.get("cost_usd")) or 0, "figures": num(p.get("figures_digitized")) or 0,
               "in_5": name in samples["pack_5"], "in_25": name in samples["pack_25"], "scanned": name in SCANNED}
        for c in CONCEPTS:
            hv = values(hd, c) if len(hd) else set()
            rv = values(run, c) if len(run) else set()
            r, pr = score(hv, rv, c)
            rec[f"{c}_recall"], rec[f"{c}_precision"] = r, pr
            rec[f"{c}_hand_n"], rec[f"{c}_run_n"] = len(hv), len(rv)
        rows.append(rec)

df = pd.DataFrame(rows)
df.to_csv(SP / "per_paper.csv", index=False)


def summary(sub):
    out = {"papers": int(len(sub)), "finished": int((sub.status == "finished").sum()),
           "rows": int(sub.rows.sum()), "cost": round(float(sub.cost.sum()), 2),
           "flags_per_row": round(float(sub.n_flags.sum() / max(1, sub.rows.sum())), 2)}
    h = sub[(sub.hand_id != "") & (sub.hand_rows > 0) & ~sub.scanned]
    out["papers_with_hand"] = int(len(h))
    ratio = (h.rows.clip(lower=0.5) / h.hand_rows).apply(math.log2)
    out["row_ratio_median"] = round(float(2 ** ratio.median()), 2) if len(h) else None
    out["row_count_within_2x"] = round(float((ratio.abs() <= 1).mean()), 2) if len(h) else None
    out["no_rows"] = int((h.rows == 0).sum())
    for c in CONCEPTS:
        r = h[f"{c}_recall"].dropna()
        pr = h[f"{c}_precision"].dropna()
        out[f"{c}_recall"] = round(float(r.mean()), 3) if len(r) else None
        out[f"{c}_precision"] = round(float(pr.mean()), 3) if len(pr) else None
        out[f"{c}_n"] = int(len(r))
    out["mean_recall"] = round(float(pd.concat([h[f"{c}_recall"] for c in CONCEPTS]).dropna().mean()), 3) \
        if len(h) else None
    return out


result = {}
for pack in PACKS:
    sub = df[df.pack == pack] if len(df) else df
    if not len(sub):
        continue
    result[pack] = {"all": summary(sub)}
    result[pack]["with_rows"] = summary(sub[sub.rows > 0])
    for label, mask in (("in_pack5_sample", sub.in_5), ("not_in_pack5_sample", ~sub.in_5),
                        ("in_pack25_sample", sub.in_25), ("not_in_pack25_sample", ~sub.in_25)):
        result[pack][label] = summary(sub[mask])
(SP / "summary.json").write_text(json.dumps(result, indent=1))
print(json.dumps({k: v["all"] for k, v in result.items()}, indent=1))
