"""Pack study, scoring v2 (Mickey, 2026-11-14): compare only what the app is meant to extract, and only values the
paper prints.

Scope (Mickey): metadata, experimental methodology, and the solution / solid chemistry -- starting concentrations
(inputs) and products (outputs). Left out: the hand dataset's internal columns (filters, flags, ids) and its calculated
ones (ion speciation, pKa, totals, ratios, computed pH, ...).

Printed values only: the hand dataset doesn't say where a value came from, and many were digitized from figures by hand
(which an unattended run can't do) or calculated. A hand value counts only when the paper's text layer prints it WITH a
unit of its quantity right after it, in any common unit (25 °C or 298 K; 2 h or 120 min; 100 mM or 0.1 M; 12 %). Values found nowhere in the text
are left out of recall (counted separately as 'not printed').

Per paper and group: recall = share of the printed hand values the run has (any column of the group, within
tolerance); precision = share of the run's values the hand data has (all hand values of the group, printed or not).
Text fields (metadata, methodology names) are matched on their words.

Usage: python evaluate_v2.py STUDY_DIR HAND_PKL [PAPERS_DIR]  -> per_paper_v2.csv, summary_v2.json next to this file
"""
import csv
import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY, HAND = Path(sys.argv[1]), Path(sys.argv[2])
PACKS = ["peptide_pack_5", "peptide_pack_25", "peptide_pack_56", "prebiotic_chemistry"]
hand = pd.read_pickle(HAND)
hand_map = json.loads((HERE / "hand_map.json").read_text())
samples = json.loads((HERE / "samples.json").read_text())

# ---- what is compared -------------------------------------------------------------------------------------------
# numeric groups: hand columns, run columns (regex), unit alternatives for 'printed' (factors on the value), tolerance
CHARGED = re.compile(r"[+-]\d*_(?:WORMadd_)?mM$")          # ion speciation (initial_Na+_mM, initial_HPO4-2_mM): calculated
NUMERIC = {
    "temperature": (r"^initial_temperature_C$", r"^initial_temperature_C$", [1], (0.0, 1.0)),
    "duration": (r"^duration_hr$", r"^duration_hr$", [1, 60, 1 / 24, 3600, 1 / 168], (0.02, 0.01)),
    "pH": (r"^initial_pH$", r"^initial_pH$", [1], (0.0, 0.15)),
    "pressure": (r"^initial_pressure_bar$", r"^initial_pressure_bar$",
                 [1, 0.1, 100, 14.5038, 1 / 1.01325, 750.06, 1e5], (0.03, 0.05)),
    "volume": (r"^(solvent_volume_mL|loading_volume_mL)$", r"(^|_)volume_mL$", [1, 1e-3, 1e3], (0.02, 0.0)),
    "solid_mass": (r"^solid_material_mass_g$", r"(^|_)mass_g$", [1, 1e3, 1e6], (0.02, 0.0)),
    "flow_rate": (r"^flow_rate_mL_min$", r"^flow_rate_mL_min$", [1, 60, 1 / 60], (0.02, 0.0)),
    "cycles": (r"^(cycle_number|cycle_duration_hr)$", r"^(cycle_number|cycle_duration_hr)$", [1, 60, 1 / 24],
               (0.02, 0.0)),
    "inputs_mM": (r"^initial_.+_mM$", r"^(initial|stock)_.+_mM$", [1, 1e-3, 1e3], (0.03, 0.0)),
    "outputs_mM": (r"^(sampled_.+_mM|mixedPeptide_.+_mM)$", r"^sampled_.+_mM$", [1, 1e-3, 1e3], (0.03, 0.0)),
    "outputs_pct": (r"^sampled_.+_%yield$", r"^sampled_.+_%(yield|recovered)$", [1], (0.03, 0.05)),
}
HAND_EXCLUDE = re.compile(r"total_monomers|^calc_|_WORMadd_|^initial_(Cys-|Phe\+)_mM$")
RUN_EXCLUDE = re.compile(r"_(err_plus|err_minus|range|log10|ln)(_|$)|^analysis_")
TEXT = {      # hand column -> run column, both one value per paper or set (word overlap)
    "title": ("paper_title", "paper_title"), "journal": ("journal_published", "journal_published"),
    "experiment_type": ("experiment_type", "experiment_type"), "solution_type": ("solution_type", "solution_type"),
    "solvent": ("solvent_name", "solvent_name"), "vessel": ("vessel_material", "vessel_material"),
    "analysis": ("analysis_method", "analysis_method"), "headspace_gas": ("headspace_gas_name", "headspace_gas_name"),
    "solid_material": ("solid_material_name", "solid_material_name"),
}
EXACT = {"year": ("year_published", "year_published"), "doi": ("paper_DOI", "paper_DOI")}
GROUPS = {"metadata": ["title", "journal", "year", "doi"],
          "methodology": ["experiment_type", "solution_type", "solvent", "vessel", "analysis", "headspace_gas",
                          "solid_material", "temperature", "duration", "pH", "pressure", "volume", "solid_mass",
                          "flow_rate", "cycles"],
          "chemistry_in": ["inputs_mM"], "chemistry_out": ["outputs_mM", "outputs_pct"]}


def num(v):
    if isinstance(v, bool):
        return None
    try:
        x = float(str(v).replace(",", "").strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


_NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?:\s*[×x]\s*10\s*[-−–]?\s*(\d+)|[eE]([-+]?\d+))?")
# the unit a printed number must carry to count for a quantity (a bare '2' is in every paper)
UNIT_AFTER = {
    "temperature": r"\s*(?:°|º|o)?\s*[CK]\b", "duration": r"\s*(?:h|hr|hrs|hours?|min|mins|minutes?|d|days?|s|sec|weeks?)\b",
    "pH": None, "pressure": r"\s*(?:bar|MPa|kPa|Pa|psi|atm|mm\s*Hg|torr)\b",
    "volume": r"\s*(?:mL|ml|L|l|µL|μL|uL|cm3|cm\s*3)\b", "solid_mass": r"\s*(?:g|mg|µg|μg|kg)\b",
    "flow_rate": r"\s*(?:mL|ml)\s*/?\s*(?:min|h|s)", "cycles": None,
    "inputs_mM": r"\s*(?:mM|M|µM|μM|mol|mmol|µmol|μmol|nmol|mol\s*/\s*[lL]|mol\s*dm|N)\b",
    "outputs_mM": r"\s*(?:mM|M|µM|μM|mol|mmol|µmol|μmol|nmol|mol\s*/\s*[lL]|mol\s*dm)\b", "outputs_pct": r"\s*%",
}


def printed_numbers(text, unit=None):
    out = []
    for m in _NUM.finditer(text):
        if unit and not re.match(unit, text[m.end():m.end() + 16]):
            continue
        v = float(m.group(1))
        if m.group(2):
            neg = "-" in m.group(0) or "−" in m.group(0) or "–" in m.group(0)
            v *= 10 ** (-int(m.group(2)) if neg else int(m.group(2)))
        elif m.group(3):
            v *= 10 ** int(m.group(3))
        out.append(v)
    return out


def is_printed(value, factors, numbers):
    for f in factors:
        target = value * f
        if target == 0:
            continue
        if any(abs(n - target) <= 0.01 * abs(target) + 1e-12 for n in numbers):
            return True
    return False


def close(a, b, tol):
    rel, ab = tol
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), ab)


def column_values(df, pattern, exclude):
    out = set()
    for c in df.columns:
        if re.search(pattern, c) and not exclude.search(c) and not (exclude is HAND_EXCLUDE and CHARGED.search(c)):
            for v in df[c]:
                x = num(v)
                if x is not None and x != 0:
                    out.add(round(x, 9))
    return out


def words(v):
    return {w for w in re.findall(r"[a-z0-9]{3,}", str(v).lower())} - {"the", "and", "with", "for"}


def text_values(df, col):
    if col not in df.columns:
        return []
    return [str(v) for v in df[col].dropna().unique() if str(v).strip() and str(v).lower() != "nan"]


def paper_text(pdf):
    import pdfplumber
    with pdfplumber.open(pdf) as d:
        return "\n".join(p.extract_text() or "" for p in d.pages)


rows = []
texts = {}
for pack in PACKS:
    q = sorted((STUDY / f"runs_{pack}").glob("queue_*"))[-1]
    papers = list(csv.DictReader(open(q / "papers.csv", encoding="utf-8")))
    combined = pd.read_csv(q / "combined_extracted.csv", dtype=str)
    for p in papers:
        name = Path(p["item"]).parent.name
        hid = hand_map.get(name)
        if not hid:
            continue
        hd = hand[hand.paper == hid]
        run = combined[combined.full_id.str[:3] == p["prefix"]]
        if name not in texts:
            raw = paper_text(Path(p["item"]))
            texts[name] = {k: printed_numbers(raw, UNIT_AFTER.get(k)) for k in NUMERIC} | {"any": printed_numbers(raw)}
        numbers = texts[name]
        rec = {"pack": pack, "paper": name, "rows": len(run), "hand_rows": len(hd), "scanned": not numbers["any"],
               "in_5": name in samples["pack_5"], "in_25": name in samples["pack_25"]}
        for key, (hpat, rpat, factors, tol) in NUMERIC.items():
            src = hd[hd.experiment_type.astype(str).str.lower() == "flowthrough"] if key == "pressure" else hd
            hv = column_values(src, hpat, HAND_EXCLUDE)
            rv = column_values(run, rpat, RUN_EXCLUDE) if len(run) else set()
            printed = {v for v in hv if is_printed(v, factors, numbers[key])}
            rec[f"{key}_printed"], rec[f"{key}_not_printed"] = len(printed), len(hv) - len(printed)
            rec[f"{key}_found"] = sum(any(close(h, r, tol) for r in rv) for h in printed)
            rec[f"{key}_run"] = len(rv)
            rec[f"{key}_run_ok"] = sum(any(close(r, h, tol) for h in hv) for r in rv)
        for key, (hc, rc) in TEXT.items():
            hv = text_values(hd, hc)
            missing = rc not in combined.columns              # the pack has no such column: not scored
            rv = text_values(run, rc) if len(run) else []
            rec[f"{key}_printed"] = 0 if missing else len(hv)
            rec[f"{key}_found"] = 0 if missing else sum(
                any(len(words(h) & words(r)) >= max(1, 0.5 * len(words(h))) for r in rv) for h in hv)
            rec[f"{key}_run"] = rec[f"{key}_run_ok"] = 0        # text fields: recall only
            rec[f"{key}_not_printed"] = 0
            rec[f"{key}_not_in_pack"] = int(missing)
        for key, (hc, rc) in EXACT.items():
            hv = {str(v).strip().lower().removesuffix(".0") for v in text_values(hd, hc)}
            rv = {str(v).strip().lower().removesuffix(".0") for v in text_values(run, rc)} if len(run) else set()
            rec[f"{key}_printed"], rec[f"{key}_found"] = len(hv), len(hv & rv)
            rec[f"{key}_run"], rec[f"{key}_run_ok"], rec[f"{key}_not_printed"] = len(rv), len(hv & rv), 0
        rows.append(rec)

df = pd.DataFrame(rows)
df.to_csv(HERE / "per_paper_v2.csv", index=False)


def pooled(sub, keys):
    """Recall and precision pooled over the papers (each printed hand value counts once)."""
    printed = sum(sub[f"{k}_printed"].sum() for k in keys)
    found = sum(sub[f"{k}_found"].sum() for k in keys)
    run = sum(sub[f"{k}_run"].sum() for k in keys)
    ok = sum(sub[f"{k}_run_ok"].sum() for k in keys)
    return {"recall": round(found / printed, 3) if printed else None, "precision": round(ok / run, 3) if run else None,
            "values": int(printed), "not_printed": int(sum(sub[f"{k}_not_printed"].sum() for k in keys))}


def per_paper_mean(sub, keys):
    vals = []
    for _, r in sub.iterrows():
        printed = sum(r[f"{k}_printed"] for k in keys)
        if printed:
            vals.append(sum(r[f"{k}_found"] for k in keys) / printed)
    return round(sum(vals) / len(vals), 3) if vals else None


summary = {}
def view(sub):
    out = {"papers": int(len(sub))}
    for g, keys in GROUPS.items():
        out[g] = {**pooled(sub, keys), "paper_mean_recall": per_paper_mean(sub, keys)}
    for k in [k for ks in GROUPS.values() for k in ks]:
        out[k] = pooled(sub, [k])
    allk = [k for ks in GROUPS.values() for k in ks]
    out["overall"] = {**pooled(sub, allk), "paper_mean_recall": per_paper_mean(sub, allk)}
    for label, mask in (("in_25", sub.in_25), ("not_in_25", ~sub.in_25), ("in_5", sub.in_5), ("not_in_5", ~sub.in_5)):
        out[label] = {g: per_paper_mean(sub[mask], keys) for g, keys in GROUPS.items()}
        out[label]["overall"] = per_paper_mean(sub[mask], allk)
    out["not_in_pack"] = [k for k in TEXT if f"{k}_not_in_pack" in sub and sub[f"{k}_not_in_pack"].all()]
    return out


for pack in PACKS:
    sub = df[(df.pack == pack) & ~df.scanned]
    summary[pack] = {"all": view(sub), "with_rows": view(sub[sub.rows > 0])}
(HERE / "summary_v2.json").write_text(json.dumps(summary, indent=1))
print("done")
