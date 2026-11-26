"""Controlled test (Mickey, 2026-11-25): runs scored on the CHOSEN columns only -- a data pack's 'Must answer' columns
(parameter_checks.marked) or a list -- so a row needn't represent its whole experiment.

Per arm, paper and column, the distinct values each side has (a value on any row counts):
  HAND   PaperDataTemplate (the hand dataset; its old column names converted by current_column_name). Recall counts
         only hand values the paper PRINTS at their precision (as printed, or x/÷ 1000 or 100 for a unit change);
         values from figures or calculated are counted as 'not printed', not scored. Agreement: the run's values that
         match any hand value of that column, over the run's values, where the hand dataset fills the column.
  MS     a checked model-standard run where there is one (same measures, every value counted).
Numbers match within 1 % ('match') or 10 % ('close'), or within the reference's rounding; a column's range column
(initial_pH_range 4:5) counts as its values; text when at least half the reference's words appear (the
accuracy evaluation's `words`, with its equivalent names).

Usage: python score_columns.py config.json  -> <out>/per_column.csv, per_paper_column.csv, summary.md
config: {"hand_csv": "...", "batch": "P1" (papers and hand ids from ../accuracy_2026-11/batches.json),
         "papers": [keys] (optional: only these), "columns": [...] or "must_answer_pack": "<pack id>",
         "arms": {"A": {"label": "...", "folders": [queue or run folders]}}, "model_standard": [folders], "out": "..."}
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "accuracy_2026-11"))
import score as acc  # noqa: E402 -- the accuracy evaluation's helpers (runs_of, rows_of, words, num, close, ...)
from parameter_extractor.ingestion.flatten_to_template import current_column_name  # noqa: E402

MATCH, CLOSE = (0.01, 0.0), (0.10, 0.0)
PRINTED = (0.005, 0.0)
FACTORS = (1, 1000, 0.001, 100, 0.01)
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?(?:[eE]-?\d+)?")


def chosen_columns(config: dict) -> list:
    if config.get("columns"):
        return list(config["columns"])
    from parameter_extractor import packs
    from parameter_extractor.parameter_checks import marked
    return sorted(marked(packs.available()[config["must_answer_pack"]]))


def values(series) -> tuple:
    """(numbers, texts) of a column: ranges 'a:b' give both ends. Zeros are left out: the hand dataset writes 0 for
    a compound a paper doesn't use (as the accuracy evaluation's scorer does)."""
    nums, texts = set(), set()
    for v in series.dropna():
        s = str(v).strip()
        if not s:
            continue
        parts = s.split(":") if re.fullmatch(r"\s*-?[\d.eE+-]+\s*:\s*-?[\d.eE+-]+\s*", s) else [s]
        xs = [acc.num(p) for p in parts]
        if all(x is not None for x in xs):
            nums |= {round(x, 9) for x in xs if x != 0}
        else:
            texts.add(s)
    return nums, texts


def _half_unit(text: str) -> float:
    """Half a unit of a number's last printed decimal: '2.6' -> 0.05, '24' -> 0.5."""
    text = text.lower().split("e")[0]
    return 0.5 * 10 ** -(len(text.split(".")[1]) if "." in text else 0)


def text_numbers(text: str) -> list:
    """(value, half a unit of its last printed decimal) of each number in the text."""
    out = []
    for m in _NUMBER.findall(text):
        m = m.replace(",", ".")
        x = acc.num(m)
        if x is not None:
            out.append((x, _half_unit(m)))
    return out


def printed(v: float, numbers: list) -> bool:
    """The paper prints v (or v x/÷ 1000 or 100, a unit change) AT ITS PRECISION: 7.2177 read off a figure isn't
    printed because the text has a '7' somewhere."""
    own = _half_unit(repr(v))
    return any(abs(v * f - t) <= min(half, own * f) + 1e-9 for f in FACTORS for t, half in numbers)


def same(ref: float, run: float, tol) -> bool:
    """Within tol, or within the reference's own rounding (0.08 h and 0.0833 h)."""
    return acc.close(ref, run, tol) or abs(ref - run) <= _half_unit(repr(ref)) + 1e-12


def _covers(a: str, b: str) -> bool:
    """At least half of a's words are in b."""
    w = acc.words(a)
    return len(w & acc.words(b)) >= max(1, 0.5 * len(w)) if w else a == b


def text_hit(ref: str, pool: set) -> bool:
    """The same name either way round: 'CdOCMo' and 'CdOCMo (Cd2[Mo(CN)8]·6H2O)', 'goethite' and 'goethite
    (alpha-FeOOH)'."""
    return any(_covers(ref, r) or _covers(r, ref) for r in pool)


def compare(ref: tuple, run: tuple, only_printed=None) -> dict:
    """ref / run: (numbers, texts). only_printed: the paper's numbers (hand reference) or None (count all)."""
    rn, rt = ref
    un, ut = run
    scored = {v for v in rn if only_printed is None or printed(v, only_printed)}
    out = {"ref_values": len(scored) + len(rt), "not_printed": len(rn) - len(scored),
           "found": sum(any(same(v, u, MATCH) for u in un) for v in scored) + sum(text_hit(t, ut) for t in rt),
           "found_close": sum(any(same(v, u, CLOSE) for u in un) for v in scored)
           + sum(text_hit(t, ut) for t in rt),
           "run_values": len(un) + len(ut)}
    if rn or rt:                                          # agreement only where the reference fills the column
        out["run_agree"] = sum(any(same(v, u, MATCH) for v in rn) for u in un) + sum(text_hit(t, rt) for t in ut)
        out["run_compared"] = len(un) + len(ut)
    return out


def hand_frame(path: str) -> pd.DataFrame:
    hand = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False).replace("", None)
    hand["_paper"] = hand.full_id.str[:3]
    hand = hand.rename(columns={c: current_column_name(c) for c in hand.columns if c != "_paper"})
    # the hand dataset often copied a final pH into initial_pH (Mickey 2026-11-25: the app keeps a final pH in
    # sampled_pH only, which is better): a row's initial_pH equal to its sampled_pH isn't scored as an initial pH
    if {"initial_pH", "sampled_pH"} <= set(hand.columns):
        copy = hand.initial_pH.notna() & (hand.initial_pH == hand.sampled_pH)
        hand.loc[copy, "initial_pH"] = None
    return hand


def score(config: dict) -> pd.DataFrame:
    columns = chosen_columns(config)
    batch = config.get("batch", "P1")
    meta = acc.BATCHES[batch]
    keys = config.get("papers") or sorted(meta)
    hand = hand_frame(config["hand_csv"])
    ms = acc.runs_of(config.get("model_standard", []), batch)
    texts, ms_rows, out = {}, {}, []
    for arm_id, arm in config["arms"].items():
        runs = acc.runs_of(arm["folders"], batch)
        for key in keys:
            if key not in runs:
                out.append({"arm": arm_id, "paper": key, "column": "", "missing_run": True})
                continue
            run = acc.rows_of(runs[key])
            m = meta.get(key, {})
            hd = hand[hand._paper == m["hand_id"]] if m.get("hand_id") else None
            if hd is not None and key not in texts:
                texts[key] = text_numbers(acc.paper_text(Path(m["pdf"])))
            if key in ms and key not in ms_rows:
                ms_rows[key] = acc.rows_of(ms[key])
            for col in columns:
                rv = values(run[col]) if col in run else (set(), set())
                rng = col.rsplit("_", 1)[0] + "_range_" + col.rsplit("_", 1)[1] if "_" in col else ""
                for extra in (col + "_range", rng):                # 'initial_pH_range' 4:5 holds pH 4 and 5
                    if extra in run:
                        en, et = values(run[extra])
                        rv = (rv[0] | en, rv[1] | et)
                rec = {"arm": arm_id, "paper": key, "column": col}
                if hd is not None and col in hd:
                    rec.update({f"hand_{k}": v for k, v in compare(values(hd[col]), rv, texts[key]).items()})
                if key in ms_rows:
                    ref = values(ms_rows[key][col]) if col in ms_rows[key] else (set(), set())
                    rec.update({f"ms_{k}": v for k, v in compare(ref, rv).items()})
                rec["run_values"] = len(rv[0]) + len(rv[1])
                out.append(rec)
    return pd.DataFrame(out)


def _r(a, b):
    return round(a / b, 3) if b else None


def summary(df: pd.DataFrame, labels: dict) -> tuple:
    df = df[df.column != ""].fillna(0)
    by_col = []
    for (arm, col), g in df.groupby(["arm", "column"]):
        rec = {"arm": arm, "column": col}
        for ref in ("hand", "ms"):
            if f"{ref}_ref_values" not in g:
                continue
            n = g[f"{ref}_ref_values"].sum()
            rec[f"{ref}_values"] = int(n)
            rec[f"{ref}_recall"] = _r(g[f"{ref}_found"].sum(), n)
            rec[f"{ref}_recall_close"] = _r(g[f"{ref}_found_close"].sum(), n)
            if f"{ref}_run_compared" in g:
                rec[f"{ref}_agreement"] = _r(g[f"{ref}_run_agree"].sum(), g[f"{ref}_run_compared"].sum())
            if ref == "hand":
                rec["hand_not_printed"] = int(g["hand_not_printed"].sum())
        by_col.append(rec)
    by_col = pd.DataFrame(by_col)
    lines = ["# Controlled test: the chosen columns only", ""]
    for arm, g in by_col.groupby("arm"):
        d = df[df.arm == arm]
        tot = lambda c: d[c].sum() if c in d else 0       # noqa: E731
        lines += [f"## {arm}: {labels.get(arm, arm)}", "",
                  f"Hand: {int(tot('hand_ref_values'))} printed values in {d[d.get('hand_ref_values', 0) > 0].paper.nunique() if 'hand_ref_values' in d else 0} papers; "
                  f"recall {_r(tot('hand_found'), tot('hand_ref_values'))} (close {_r(tot('hand_found_close'), tot('hand_ref_values'))}); "
                  f"agreement {_r(tot('hand_run_agree'), tot('hand_run_compared'))}; "
                  f"{int(tot('hand_not_printed'))} hand values not printed (figures, calculated) not scored.",
                  f"Model standard: {int(tot('ms_ref_values'))} values in {d[d.get('ms_ref_values', 0) > 0].paper.nunique() if 'ms_ref_values' in d else 0} papers; "
                  f"recall {_r(tot('ms_found'), tot('ms_ref_values'))} (close {_r(tot('ms_found_close'), tot('ms_ref_values'))}); "
                  f"agreement {_r(tot('ms_run_agree'), tot('ms_run_compared'))}.", "",
                  "| Column | Hand values | Hand recall | Agreement | MS values | MS recall | MS agreement |",
                  "|---|---|---|---|---|---|---|"]
        for _, r in g.sort_values("hand_values" if "hand_values" in g else "column", ascending=False).iterrows():
            lines.append(f"| `{r.column}` | {r.get('hand_values', '–')} | {r.get('hand_recall', '–')} | "
                         f"{r.get('hand_agreement', '–')} | {r.get('ms_values', '–')} | {r.get('ms_recall', '–')} | "
                         f"{r.get('ms_agreement', '–')} |")
        lines.append("")
    return by_col, "\n".join(lines).replace("| nan ", "| – ").replace("| None ", "| – ")


if __name__ == "__main__":
    config = json.loads(Path(sys.argv[1]).read_text())
    out_dir = Path(config.get("out", HERE / "results"))
    out_dir.mkdir(parents=True, exist_ok=True)
    df = score(config)
    df.to_csv(out_dir / "per_paper_column.csv", index=False)
    by_col, md = summary(df, {a: v.get("label", a) for a, v in config["arms"].items()})
    by_col.to_csv(out_dir / "per_column.csv", index=False)
    (out_dir / "summary.md").write_text(md)
    print(md)
