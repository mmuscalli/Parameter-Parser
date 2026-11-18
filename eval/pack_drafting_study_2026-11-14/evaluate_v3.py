"""Pack study, scoring v3 (Mickey, 2026-11-17): the runs rebuilt with the current code against the corrected hand
dataset (PaperDataTemplate_Nov15_2026.csv, after the v1-v3 audit).

Mickey's rules for this comparison:
- The hand dataset is a reference gathered by a different method, not ground truth: it has slips, and figures or
  tables that weren't digitized. Differences are reported as differences, to be looked at.
- New columns (parameters the app captured that the hand dataset has no column for) don't count against accuracy:
  they are counted and listed separately.
- Rounding and digitizing precision differ, so two values can both be right and differ slightly: every comparison has
  two tiers, 'match' (within rounding: the v2 tolerances) and 'close' (within 10 %).

Three measures per paper and group (metadata, methodology, chemistry in, chemistry out):
1. recall: of the hand values the paper prints (with a unit of their quantity), how many the run has (any column of
   the group) -- as in v2.
2. agreement on shared columns: the run's values in columns the hand dataset also fills for that paper (hand names
   brought to the app's current names, flatten_to_template.current_column_name), each value compared with the hand
   values of the SAME column.
3. new: values in columns the hand dataset doesn't fill for that paper -- listed, not scored.
Two modes: 'written' (the dataset as the unattended run wrote it) and 'reviewed' (plus the values the run held back for
review -- new_variables.json 'left_out', compounds and variables outside the pack's vocabulary -- as if the user had
accepted them all; in the app they are written once accepted).
Pressure is compared only for flowthrough rows (sealed batch pressures in the hand data are assigned, not reported).

Usage: python evaluate_v3.py STUDY_DIR HAND_CSV [BEFORE_YYYYMMDD]  -> per_paper_v3.csv, summary_v3.json, new_columns_v3.csv here
"""
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from parameter_extractor.ingestion.flatten_to_template import current_column_name  # noqa: E402

HERE = Path(__file__).resolve().parent
STUDY, HAND = Path(sys.argv[1]), Path(sys.argv[2])
BEFORE = sys.argv[3] if len(sys.argv) > 3 else ""      # e.g. 20261117: score the queues made before that date
TAG = f"_before{BEFORE}" if BEFORE else ""
PACKS = ["peptide_pack_5", "peptide_pack_25", "peptide_pack_56", "prebiotic_chemistry"]
SCANNED = {"Flores1973", "Inoue1993", "Rabinowitz1969"}
hand = pd.read_csv(HAND, encoding="utf-8-sig", dtype=str, keep_default_na=False)
hand["paper"] = hand.full_id.str[:3]
hand_map = json.loads((HERE / "hand_map.json").read_text())
samples = json.loads((HERE / "samples.json").read_text())

# the v2 definitions (groups, printed-value units, tolerances, helpers), taken from evaluate_v2.py unchanged
_v2 = {"re": re, "math": math}
src = (HERE / "evaluate_v2.py").read_text()
defs = src[src.index("# ---- what is compared"):src.index("def paper_text")]
exec(defs, _v2)
NUMERIC, UNIT_AFTER, GROUPS, EXACT = _v2["NUMERIC"], _v2["UNIT_AFTER"], _v2["GROUPS"], _v2["EXACT"]
printed_numbers, is_printed, num, words = _v2["printed_numbers"], _v2["is_printed"], _v2["num"], _v2["words"]
TEXT = {k: v for k, v in _v2["TEXT"].items() if k != "analysis"}
GROUPS = {g: [k for k in ks if k != "analysis"] for g, ks in GROUPS.items()}
GROUPS["methodology"].append("analysis")

# ---- changes to v2's definitions (Mickey, 2026-11-17) ------------------------------------------------------------
# pH: the hand dataset sometimes keeps a final or after-reaction pH in initial_pH (faisal2005's results table, Leman2004's
# 'Final pH'); a value is found in any pH column of the run, so its placement isn't scored as a miss.
NUMERIC["pH"] = (r"^(initial|sampled)_pH$", r"^(initial|sampled)_pH$", [1], NUMERIC["pH"][3])
_PRINTED = re.compile(r"(?<![\w.])(\d+)(?:\.(\d+))?(?:\s*[×x]\s*10\s*([-−–]?)\s*(\d+)|[eE]([-+]?\d+))?")


def printed_with_decimals(text, unit=None):
    """[(value, decimals as printed)] for numbers followed by a unit of the quantity (v2's printed_numbers, keeping
    the precision each number is printed with)."""
    out = []
    for m in _PRINTED.finditer(text):
        if unit and not re.match(unit, text[m.end():m.end() + 16]):
            continue
        frac = m.group(2) or ""
        v, dec = float(m.group(1) + ("." + frac if frac else "")), len(frac)
        if m.group(4):
            e = int(m.group(4)) * (-1 if m.group(3) else 1)
            v, dec = v * 10 ** e, max(0, dec - e)
        elif m.group(5):
            e = int(m.group(5))
            v, dec = v * 10 ** e, max(0, dec - e)
        out.append((v, dec))
    return out


def _decimals(x):
    t = f"{round(x, 9):.9f}".rstrip("0")
    return len(t.split(".")[1]) if "." in t else 0


def is_printed_exact(value, factors, numbers):
    """Printed AS this value (Mickey: values calculated or digitized for the hand dataset aren't misses): in the
    printed unit (factor 1) the value has no more decimals than the printed number and equals it at that precision --
    23.8 h isn't the printed '24 h' -- in a converted unit, the printed number converted equals the value at the value's own precision (0.0333 h is a
    printed '2 min'; 71.37 h isn't a printed '3 d', which is 72 h)."""
    for f in factors:
        target = value * f
        if target == 0:
            continue
        for n, dec in numbers:
            if f == 1:
                if _decimals(target) <= dec and abs(n - target) <= 0.5 * 10 ** -dec + 1e-9:
                    return True
            elif abs(n / f - value) <= 0.5 * 10 ** -_decimals(value) + 1e-9:
                return True            # the printed number in the hand value's unit, at the hand value's precision
    return False


def range_values(df, pattern):
    """Both ends of the run's range columns for a quantity ('initial_pH_range' '8.3:8.9' -> 8.3, 8.9): recall only."""
    out = set()
    for c in df.columns:
        if "_range" in c and re.search(pattern, c.replace("_range", "")):
            for v in df[c].dropna().astype(str):
                for part in v.split(":"):
                    x = num(part)
                    if x is not None and x != 0:
                        out.add(round(x, 9))
    return out


THERMO = re.compile(r"pka|pH_calc|pH_working|pH_neutral_delta|WORM|is_balanced_by|^calc_|_IS_|total_monomers|"
                    r"^initial_(Cys-|Phe\+)_mM$")
CHARGED = re.compile(r"^initial_[^_]+[+-]\d*_(?:WORMadd_)?mM$")      # ion speciation (initial_Na+_mM): calculated
RUN_EXCLUDE = re.compile(r"_(err_plus|err_minus|range|log10|ln)(_|$)|^analysis_")
CLOSE = (0.10, 0.0)


def close(a, b, tol):
    rel, ab = tol
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), ab)


def group_of(col):
    for key, (_hp, rpat, _f, tol) in NUMERIC.items():
        if re.search(rpat, col):
            return key, tol
    return None, None


def numeric_values(series):
    out = set()
    for v in series:
        x = num(v)
        if x is not None and x != 0:
            out.add(round(x, 9))
    return out


def hand_columns(hd):
    """{current column name: set of values} for this paper's hand rows (calculated / speciation columns left out)."""
    out = {}
    flow = hd.experiment_type.str.lower() == "flowthrough"
    for c in hd.columns:
        if THERMO.search(c) or CHARGED.search(c) or not re.match(r"^(initial|sampled|mixedPeptide|duration|loading|"
                                                                   r"solvent_volume|flow_|cycle_|solid_material_mass)", c):
            continue
        rows = hd[flow] if c == "initial_pressure_bar" else hd
        vals = numeric_values(rows[c])
        if vals:
            out.setdefault(current_column_name(c), set()).update(vals)
    return out


def techniques_hand(hd):
    return {t.strip().lower() for s in hd.get("analysis_technique", pd.Series(dtype=str)) for t in str(s).split(";")
            if t.strip()}


def techniques_run(run):
    return {c.split("_")[1].lower() for c in run.columns if c.startswith("analysis_") and run[c].astype(str).str.strip()
            .replace("nan", "").ne("").any() and c.count("_") >= 2}


def paper_text(pdf):
    import pdfplumber
    with pdfplumber.open(pdf) as d:
        return "\n".join(p.extract_text() or "" for p in d.pages)


def latest(folder):
    qs = sorted(q for q in folder.glob("queue_*") if not BEFORE or q.name < f"queue_{BEFORE}")
    return qs[-1] if qs else None


def queue_runs(q):
    """{paper name: (prefix, rows)} from a queue folder."""
    papers = list(csv.DictReader(open(q / "papers.csv", encoding="utf-8")))
    combined = pd.read_csv(q / "combined_extracted.csv", dtype=str, low_memory=False)
    return {Path(p["item"]).parent.name: (p["item"], combined[combined.full_id.str[:3] == p["prefix"]]
                                          .dropna(axis=1, how="all"), Path(p["run_folder"])) for p in papers}


def with_review(run, folder):
    """The run's rows plus its held-back values (new_variables.json 'left_out'), as if all were accepted."""
    f = folder / "new_variables.json"
    if not f.is_file() or not len(run):
        return run
    run = run.copy()
    for v in json.loads(f.read_text()).get("left_out", []):
        col, val = v.get("proposed_column"), v.get("value")
        if not col or val is None or not v.get("include", True):
            continue
        # held-back ids carry the run's own prefix; the queue renumbers papers, so match on set + sample
        ids = {i[3:] for i in v.get("row_ids", [])}
        mask = run.full_id.str[3:].isin(ids)
        if col not in run.columns:
            run[col] = None
        run.loc[mask & run[col].isna(), col] = val
    return run


rows, new_cols = [], Counter()
texts = {}
for mode, pack in [(m, p) for m in ("written", "reviewed") for p in PACKS]:
    main_queue = latest(STUDY / f"runs_{pack}")
    if main_queue is None:                                # a study folder with only some packs (a validation run)
        continue
    runs = queue_runs(main_queue)
    sq = latest(STUDY / f"scanned_{pack}")
    if sq is not None:
        runs.update(queue_runs(sq))                       # the scanned papers' reruns with text recognition
    for name, (item, run, folder) in runs.items():
        if mode == "reviewed":
            run = with_review(run, folder)
        hid = hand_map.get(name)
        if not hid:
            continue
        hd = hand[hand.paper == hid]
        if name not in texts:
            raw = paper_text(Path(item))
            texts[name] = {k: printed_with_decimals(raw, UNIT_AFTER.get(k)) for k in NUMERIC}
        numbers = texts[name]
        # what the rows are (item 2, 'too many rows'): rows with a product value, figure rows still waiting for their
        # figure to be digitized, rows reproduced from a cited paper
        outcome = [c for c in run.columns if re.match(r"^sampled_.+_(mM|%yield|%recovered|mmol)$", c)
                   and not RUN_EXCLUDE.search(c)]
        has_out = run[outcome].apply(pd.to_numeric, errors="coerce").notna().any(axis=1) if outcome and len(run) \
            else pd.Series(False, index=run.index)
        loc = run.get("data_location", pd.Series("", index=run.index)).fillna("").astype(str)
        cited = run.get("original_data_reference", pd.Series("", index=run.index)).fillna("").astype(str).str.strip() != ""
        rec_rows = {"rows_with_values": int(has_out.sum()),
                    "figure_rows_empty": int((loc.str.startswith("Fig") & ~has_out).sum()),
                    "cited_rows": int(cited.sum()), "other_rows_empty": int((~has_out & ~loc.str.startswith("Fig")).sum())}
        rec = {"mode": mode, "pack": pack, "paper": name, **rec_rows, "rows": len(run), "hand_rows": len(hd),
               "sets": run.full_id.str[:6].nunique() if len(run) else 0, "hand_sets": hd.full_id.str[:6].nunique(),
               "in_5": name in samples["pack_5"], "in_25": name in samples["pack_25"]}
        # 1. recall of printed hand values (any column of the group)
        for key, (hpat, rpat, factors, tol) in NUMERIC.items():
            srcrows = hd[hd.experiment_type.str.lower() == "flowthrough"] if key == "pressure" else hd
            hv = set()
            for c in srcrows.columns:
                if re.search(hpat, c) and not THERMO.search(c) and not CHARGED.search(c):
                    hv |= numeric_values(srcrows[c])
            rv = set()
            for c in run.columns:
                if re.search(rpat, c) and not RUN_EXCLUDE.search(c):
                    rv |= numeric_values(run[c])
            rv |= range_values(run, rpat)
            printed = {v for v in hv if is_printed_exact(v, factors, numbers[key])}
            rec[f"{key}_printed"] = len(printed)
            rec[f"{key}_found"] = sum(any(close(h, r, tol) for r in rv) for h in printed)
            rec[f"{key}_found_close"] = sum(any(close(h, r, CLOSE) for r in rv) for h in printed)
        for key, (hc, rc) in TEXT.items():
            hv = [str(v) for v in hd[hc].unique() if str(v).strip()] if hc in hd else []
            rv = [str(v) for v in run[rc].dropna().unique() if str(v).strip()] if rc in run else []
            inpack = any(rc in r.columns for _n, (_i, r, _f) in runs.items())
            rec[f"{key}_printed"] = len(hv) if inpack else 0
            rec[f"{key}_found"] = rec[f"{key}_found_close"] = sum(
                any(len(words(h) & words(r)) >= max(1, 0.5 * len(words(h))) for r in rv) for h in hv) if inpack else 0
        th, tr = techniques_hand(hd), techniques_run(run)
        rec["analysis_printed"], rec["analysis_found"] = len(th), len(th & tr)
        rec["analysis_found_close"] = rec["analysis_found"]
        for key, (hc, rc) in EXACT.items():
            hv = {str(v).strip().lower().removesuffix(".0") for v in hd[hc] if str(v).strip()}
            rv = {str(v).strip().lower().removesuffix(".0") for v in run[rc].dropna()} if rc in run else set()
            rec[f"{key}_printed"] = len(hv)
            rec[f"{key}_found"] = rec[f"{key}_found_close"] = len(hv & rv)
        # 2. agreement on shared columns, 3. new columns
        hc = hand_columns(hd)
        agree = Counter()
        for c in run.columns:
            if RUN_EXCLUDE.search(c):
                continue
            key, tol = group_of(c)
            if key is None:
                continue
            rv = numeric_values(run[c])
            if not rv:
                continue
            if c in hc:
                g = next(g for g, ks in GROUPS.items() if key in ks)
                agree[f"{g}_shared"] += len(rv)
                agree[f"{g}_match"] += sum(any(close(r, h, tol) for h in hc[c]) for r in rv)
                agree[f"{g}_close"] += sum(any(close(r, h, CLOSE) for h in hc[c]) for r in rv)
            else:
                agree["new_values"] += len(rv)
                agree["new_columns"] += 1
                if mode == "written":
                    new_cols[(pack, c)] += 1
        rec["shared_columns"] = sum(1 for c in run.columns if c in hc)
        rec.update(agree)
        rows.append(rec)

df = pd.DataFrame(rows).fillna(0)
df.to_csv(HERE / f"per_paper_v3{TAG}.csv", index=False)
pd.DataFrame([{"pack": p, "column": c, "papers": n} for (p, c), n in new_cols.most_common()]).to_csv(
    HERE / f"new_columns_v3{TAG}.csv", index=False)


def pooled(sub, keys, tier=""):
    printed = sum(sub[f"{k}_printed"].sum() for k in keys)
    found = sum(sub[f"{k}_found{tier}"].sum() for k in keys)
    return round(found / printed, 3) if printed else None


def paper_mean(sub, keys, tier=""):
    vals = [sum(r[f"{k}_found{tier}"] for k in keys) / p for _, r in sub.iterrows()
            if (p := sum(r[f"{k}_printed"] for k in keys))]
    return round(sum(vals) / len(vals), 3) if vals else None


def view(sub):
    out = {"papers": int(len(sub)), "rows": int(sub.rows.sum()), "hand_rows": int(sub.hand_rows.sum())}
    allk = [k for ks in GROUPS.values() for k in ks]
    for g, keys in list(GROUPS.items()) + [("overall", allk)]:
        out[g] = {"recall": pooled(sub, keys), "recall_close": pooled(sub, keys, "_close"),
                  "paper_mean_recall": paper_mean(sub, keys), "paper_mean_recall_close": paper_mean(sub, keys, "_close"),
                  "printed_values": int(sum(sub[f"{k}_printed"].sum() for k in keys))}
        if g != "overall":
            s = sub.get(f"{g}_shared", pd.Series([0])).sum()
            out[g]["shared_values"] = int(s)
            out[g]["agree_match"] = round(sub.get(f"{g}_match", pd.Series([0])).sum() / s, 3) if s else None
            out[g]["agree_close"] = round(sub.get(f"{g}_close", pd.Series([0])).sum() / s, 3) if s else None
    for k in allk:
        out[k] = {"recall": pooled(sub, [k]), "recall_close": pooled(sub, [k], "_close"),
                  "printed": int(sub[f"{k}_printed"].sum())}
    out["new_values"] = int(sub.get("new_values", pd.Series([0])).sum())
    out["new_columns_per_paper"] = round(float(sub.get("new_columns", pd.Series([0])).mean()), 1)
    out["no_rows"] = int((sub.rows == 0).sum())
    return out


PACKS = [p for p in PACKS if (df.pack == p).any()]
summary = {mode: {pack: {"all": view(df[(df["mode"] == mode) & (df.pack == pack)]),
                         "with_rows": view(df[(df["mode"] == mode) & (df.pack == pack) & (df.rows > 0)])}
                  for pack in PACKS} for mode in ("written", "reviewed")}
(HERE / f"summary_v3{TAG}.json").write_text(json.dumps(summary, indent=1))
for mode, pack in [(m, p) for m in ("written", "reviewed") for p in PACKS]:
    w = summary[mode][pack]["with_rows"]
    print(f"{mode:8} {pack:20} papers {w['papers']:2}  recall {w['overall']['paper_mean_recall']} "
          f"(close {w['overall']['paper_mean_recall_close']})  "
          + "  ".join(f"{g}: {w[g]['paper_mean_recall']}/{w[g]['agree_match']}" for g in GROUPS)
          + f"  new values {w['new_values']}")
