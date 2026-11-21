"""Accuracy evaluation, November 2026 (Mickey, 2026-11-20): one scorer for every batch and arm.

Every arm's runs are scored against two references, as far as each paper has them:

1. HAND (prebiotic, P1): PaperDataTemplate_Nov15_2026.csv, scored exactly as the pack study's evaluate_v3.py does --
   recall of the values the paper PRINTS (at the precision it prints them, any common unit), so values taken from
   figures or calculated for the hand dataset aren't misses; two tiers, 'match' (the study's tolerances) and 'close'
   (within 10 %); agreement on the columns both fill; values in columns the hand dataset doesn't fill counted as new.
   ARCHIVE (exoplanets, E1): the Exoplanet Archive's parameter sets for the paper's own reference
   (E1/archive/<key>.json), compared with the app's own archive comparison (exoplanet_archive.compare: within 0.5 % or
   the archive's printed precision); 'close' = within 10 %. A quantity the archive gives in two units (Earth and
   Jupiter radii and masses) counts once; limit flags and the archive's bookkeeping are left out, as are star and
   system values the archive took from another reference.
2. MODEL STANDARD (MS): a validated run of the paper (developer handoff, checked against the PDF). Per quantity, the
   distinct values each side has: recall = MS values the arm has, precision = arm values the MS has (match / close).
   Cells: arm rows paired with MS rows by their conditions, then each cell in a column both have is right, wrong or
   missing; a value on another row of the same quantity is 'elsewhere'.
   A value the hand dataset doesn't have is checked against the MS where there is one: 'confirmed' or
   'unsupported', never a miss; papers without an MS report such values as 'unverified', unscored.

Figures: rows waiting for a figure to be digitized and hand values that aren't printed (from figures, or calculated)
are counted per paper, not scored. Two modes: 'written' (as the unattended run wrote it) and 'reviewed' (plus the
values it held back for review, as if accepted).

Usage: python score.py [arms.json]   -> results/per_paper.csv, results/summary.json, results/summary.md
arms.json: {"hand_csv": "...", "arms": {"A": {"label": "...", "pack": "...", "drafted_from": [keys],
            "batches": {"P1": [queue folder, ...]}}}, "model_standard": {"P1": [queue folder or run folder, ...]}}
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from parameter_extractor.ingestion.flatten_to_template import current_column_name  # noqa: E402
from parameter_extractor.validation import exoplanet_archive as xa  # noqa: E402

STUDY_EVAL = HERE.parent / "pack_drafting_study_2026-11-14"
ROOT = HERE.parents[2]
TESTS = ROOT / "Paper Files/Accuracy Test 2026-11"
BATCHES = json.loads((HERE / "batches.json").read_text())

# ---- the study's definitions (evaluate_v2 via evaluate_v3), unchanged so the numbers stay comparable ---------------
_v2 = {"re": re, "math": math}
_src = (STUDY_EVAL / "evaluate_v2.py").read_text()
exec(_src[_src.index("# ---- what is compared"):_src.index("def paper_text")], _v2)
NUMERIC, UNIT_AFTER, GROUPS, EXACT = _v2["NUMERIC"], _v2["UNIT_AFTER"], _v2["GROUPS"], _v2["EXACT"]
num, _study_words = _v2["num"], _v2["words"]
# names that mean the same compound (Mickey 2026-11-20: differences in wording aren't misses): a common name and its
# formula. Exact equivalents only -- a mineral (quartz, corundum) is not the same as its oxide's name.
SAME_NAMES = [("silica", "sio2"), ("alumina", "al2o3"), ("titania", "tio2"), ("zirconia", "zro2"),
              ("magnesia", "mgo"), ("deuterium", "d2o"), ("argon", "ar"), ("nitrogen", "n2"), ("helium", "he")]


def words(v):
    """The study's word set (words of 3+ letters), plus a short name's own token ('Ar', 'N2', 'CO': the study's
    words leave it out, so 'Ar' never matched 'Ar'), plus each name's equivalent (SAME_NAMES)."""
    w = set(_study_words(v))
    w |= {t for t in re.findall(r"[a-z0-9]+", str(v).lower()) if len(t) == 2 and any(c.isalpha() for c in t)}
    for a, b in SAME_NAMES:
        if a in w:
            w.add(b)
        if b in w:
            w.add(a)
    return w
TEXT = {k: v for k, v in _v2["TEXT"].items() if k != "analysis"}
GROUPS = {g: [k for k in ks if k != "analysis"] for g, ks in GROUPS.items()}
GROUPS["methodology"].append("analysis")
NUMERIC["pH"] = (r"^(initial|sampled)_pH$", r"^(initial|sampled)_pH$", [1], NUMERIC["pH"][3])
_v3 = (STUDY_EVAL / "evaluate_v3.py").read_text()
_v3_ns = {"re": re, "math": math, "pd": pd, "json": json, "csv": csv, "Path": Path, "Counter": Counter,
          "num": num, "NUMERIC": NUMERIC, "current_column_name": current_column_name, "GROUPS": GROUPS}
exec(_v3[_v3.index("_PRINTED = re.compile"):_v3.index("\nrows, new_cols = ")], _v3_ns)   # definitions only
printed_with_decimals, is_printed_exact = _v3_ns["printed_with_decimals"], _v3_ns["is_printed_exact"]
range_values, THERMO, CHARGED = _v3_ns["range_values"], _v3_ns["THERMO"], _v3_ns["CHARGED"]
RUN_EXCLUDE, CLOSE, close = _v3_ns["RUN_EXCLUDE"], _v3_ns["CLOSE"], _v3_ns["close"]
group_of, numeric_values, hand_columns = _v3_ns["group_of"], _v3_ns["numeric_values"], _v3_ns["hand_columns"]
techniques_hand, techniques_run, with_review = (_v3_ns["techniques_hand"], _v3_ns["techniques_run"],
                                                _v3_ns["with_review"])
MATCH_OTHER = (0.01, 0.0)              # quantities outside the study's list: within 1 %, or 10 % for 'close'


def paper_text(pdf: Path) -> str:
    import pdfplumber
    with pdfplumber.open(pdf) as d:
        return "\n".join(p.extract_text() or "" for p in d.pages)


# ---- finding the runs ----------------------------------------------------------------------------------------------
def _key_of(item: str, batch: str) -> str:
    """A queue item (a PDF in the batch's folder, or an arXiv id of E1) -> the batch's paper key."""
    if item.lower().endswith(".pdf"):
        p = Path(item)
        if p.parent.parent.name == batch:
            return p.parent.name
        for key, m in BATCHES.get(batch, {}).items():           # older queues: the original file
            if m.get("source") == item or m.get("pdf") == item:
                return key
        return p.parent.name
    aid = item.split(":")[-1].split("v")[0]
    return next((k for k, m in BATCHES.get(batch, {}).items() if m.get("arxiv") == aid), item)


def runs_of(folders, batch: str) -> dict:
    """{paper key: run folder}: queue folders (papers.csv) or single run folders; later folders win."""
    out = {}
    for f in folders:
        f = Path(f)
        if (f / "papers.csv").is_file():
            for p in csv.DictReader(open(f / "papers.csv", encoding="utf-8")):
                if p.get("run_folder") and Path(p["run_folder"]).is_dir():
                    out[_key_of(p["item"], batch)] = Path(p["run_folder"])
        elif (f / "run_config.json").is_file():
            cfg = json.loads((f / "run_config.json").read_text())
            out[_key_of(str(cfg.get("item") or cfg.get("paper", "")), batch)] = f
    return out


def rows_of(run_dir: Path) -> pd.DataFrame:
    hits = sorted(p for p in run_dir.glob("*_extracted.csv") if not p.name.startswith("combined"))
    if not hits:
        return pd.DataFrame()
    df = pd.read_csv(hits[0], dtype=str, keep_default_na=False, low_memory=False).replace("", None)
    return df.dropna(axis=1, how="all")


def cost_of(run_dir: Path) -> tuple:
    f = run_dir / "run_summary.json"
    if not f.is_file():
        return None, None
    s = json.loads(f.read_text())
    return (s.get("estimated_cost_total_usd") or s.get("estimated_cost_usd"),
            s.get("elapsed_seconds") or s.get("elapsed_sec"))


# ---- row counts: what the rows are, and what the figures still hold --------------------------------------------------
def row_counts(run: pd.DataFrame) -> dict:
    outcome = [c for c in run.columns if re.match(r"^sampled_.+_(mM|%yield|%recovered|mmol)$", c)
               and not RUN_EXCLUDE.search(c)]
    has_out = (run[outcome].apply(pd.to_numeric, errors="coerce").notna().any(axis=1) if outcome and len(run)
               else pd.Series(False, index=run.index))
    loc = run.get("data_location", pd.Series("", index=run.index)).fillna("").astype(str)
    fig = loc.str.startswith("Fig")
    return {"rows": len(run), "rows_with_results": int(has_out.sum()),
            "figure_rows_waiting": int((fig & ~has_out).sum()),
            "sets": int(run.full_id.str[:6].nunique()) if len(run) and "full_id" in run else 0}


# ---- 1a. against the hand dataset (prebiotic) ------------------------------------------------------------------------
def hand_scores(run: pd.DataFrame, hd: pd.DataFrame, numbers: dict, arm_columns: set) -> tuple:
    """The study's v3 measures for one paper -> (record, {column: values the hand dataset lacks})."""
    rec = {"hand_rows": len(hd)}
    not_printed = 0
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
        not_printed += len(hv) - len(printed)
        rec[f"h_{key}_printed"] = len(printed)
        rec[f"h_{key}_found"] = sum(any(close(h, r, tol) for r in rv) for h in printed)
        rec[f"h_{key}_found_close"] = sum(any(close(h, r, CLOSE) for r in rv) for h in printed)
    for key, (hc, rc) in TEXT.items():
        hv = [str(v) for v in hd[hc].unique() if str(v).strip()] if hc in hd else []
        rv = [str(v) for v in run[rc].dropna().unique() if str(v).strip()] if rc in run else []
        inpack = rc in arm_columns
        rec[f"h_{key}_printed"] = len(hv) if inpack else 0
        rec[f"h_{key}_found"] = rec[f"h_{key}_found_close"] = sum(
            any(len(words(h) & words(r)) >= max(1, 0.5 * len(words(h))) for r in rv) for h in hv) if inpack else 0
    th, tr = techniques_hand(hd), techniques_run(run)
    rec["h_analysis_printed"], rec["h_analysis_found"] = len(th), len(th & tr)
    rec["h_analysis_found_close"] = rec["h_analysis_found"]
    for key, (hc, rc) in EXACT.items():
        hv = {str(v).strip().lower().removesuffix(".0") for v in hd[hc] if str(v).strip()}
        rv = {str(v).strip().lower().removesuffix(".0") for v in run[rc].dropna()} if rc in run else set()
        rec[f"h_{key}_printed"] = len(hv)
        rec[f"h_{key}_found"] = rec[f"h_{key}_found_close"] = len(hv & rv)
    rec["h_not_printed"] = not_printed                    # from figures or calculated: not scored
    hc = hand_columns(hd)
    agree, new = Counter(), {}
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
            agree[f"h_{g}_shared"] += len(rv)
            agree[f"h_{g}_match"] += sum(any(close(r, h, tol) for h in hc[c]) for r in rv)
            agree[f"h_{g}_close"] += sum(any(close(r, h, CLOSE) for h in hc[c]) for r in rv)
        else:
            new[c] = rv
            agree["h_new_values"] += len(rv)
            agree["h_new_columns"] += 1
    rec.update(agree)
    return rec, new


# ---- 1b. against the Exoplanet Archive -------------------------------------------------------------------------------
UNIT_PAIRS = {"pl_radj": "pl_rade", "pl_massj": "pl_masse", "pl_bmassj": "pl_bmasse", "pl_msinij": "pl_msinie"}


def _quantity(column: str) -> str:
    for j, e in UNIT_PAIRS.items():
        if column.startswith(j):
            return e + column[len(j):]
    return column


def _archive_group(q: str) -> str:
    if q.endswith(("err1", "err2")):
        return "uncertainty"
    if q.startswith("st_"):
        return "star"
    if q.startswith(("disc_", "discoverymethod")):
        return "discovery"
    if q.startswith("sy_"):
        return "system"
    return "planet"


def _expected(aset: dict, reference: str) -> set:
    """The quantities an archive parameter set holds from this paper (as compare() reads them)."""
    out = set()
    for column, archived in aset.items():
        if (column in xa.SKIP or column.endswith(("str", "reflink", "lim")) or archived in ("", None)
                or column in xa.ARCHIVE_ONLY):
            continue
        ref_col = "disc_refname" if column == "discoverymethod" else next(
            (c for prefix, c in xa.REFERENCE_OF.items() if column.startswith(prefix)), None)
        if ref_col and aset.get(ref_col) and not xa._same_reference(aset[ref_col], reference):
            continue                                       # the archive took it from another paper
        if not column.startswith(("pl_", "st_", "sy_", "disc_", "discoverymethod")):
            continue
        out.add(_quantity(column))
    return out


# a drafted exoplanet pack names its own columns (Phase 1, unit_system "astronomy"): the archive column each stands for,
# and how its value becomes the archive's (Myr -> Gyr; L_sun -> the archive's log10 L_sun). Uncertainties follow
# (_err_plus -> err1, _err_minus -> err2, negative).
DRAFT_TO_ARCHIVE = {
    "orbital_period_d": ("pl_orbper", None), "semi_major_axis_au": ("pl_orbsmax", None), "eccentricity": ("pl_orbeccen", None),
    "orbital_inclination_deg": ("pl_orbincl", None), "impact_parameter": ("pl_imppar", None),
    "argument_of_periastron_deg": ("pl_orblper", None), "rv_semi_amplitude_m_per_s": ("pl_rvamp", None),
    "time_of_conjunction_BJD": ("pl_tranmid", None), "transit_duration_h": ("pl_trandur", None), "radius_ratio": ("pl_ratror", None),
    "planet_mass_M_E": ("pl_bmasse", None), "planet_radius_R_E": ("pl_rade", None), "planet_density_g_per_cm3": ("pl_dens", None),
    "equilibrium_temperature_K": ("pl_eqt", None), "insolation_S_E": ("pl_insol", None),
    "stellar_effective_temperature_K": ("st_teff", None), "stellar_log_g_dex": ("st_logg", None), "stellar_metallicity_dex": ("st_met", None),
    "stellar_mass_M_sun": ("st_mass", None), "stellar_radius_R_sun": ("st_rad", None), "stellar_luminosity_L_sun": ("st_lum", "log10"),
    "stellar_density_g_per_cm3": ("st_dens", None), "stellar_age_Myr": ("st_age", 1e-3), "stellar_rotation_period_d": ("st_rotp", None),
    "vsini_km_per_s": ("st_vsin", None), "stellar_distance_pc": ("sy_dist", None), "detection_method": ("discoverymethod", None),
    "discovery_facility": ("disc_facility", None)}


def row_labels(run_dir: Path) -> dict:
    """{full_id: (set label, sample label)} from the run's record (<paper>_record.json)."""
    out = {}
    for f in Path(run_dir).glob("*_record.json"):
        def walk(node, set_label=""):
            if node.get("level") == "set":
                set_label = node.get("label", "")
            if not node.get("children") and node.get("level") not in ("paper", "set"):
                out[node["id"]] = (set_label, node.get("label", ""))
            for c in node.get("children", []):
                walk(c, set_label)
        walk(json.loads(f.read_text())["paper"])
    return out


def as_archive_columns(run: pd.DataFrame, run_dir: Path) -> pd.DataFrame:
    """A drafted pack's rows in the archive's column names (DRAFT_TO_ARCHIVE), the planet named by its row label."""
    if "pl_name" in run.columns or not any(c in run.columns for c in DRAFT_TO_ARCHIVE):
        return run
    labels = row_labels(run_dir)
    out = pd.DataFrame(index=run.index)
    out["pl_name"] = run.full_id.map(lambda i: re.sub(r"\s*[\(\[].*$", "", labels.get(i, ("", ""))[1]).strip())
    for col, (arch, how) in DRAFT_TO_ARCHIVE.items():
        for suffix, asuf, sign in (("", "", 1), ("_err_plus", "err1", 1), ("_err_minus", "err2", -1)):
            c = col + suffix
            if c not in run.columns:
                continue
            def conv(v, how=how, sign=sign, err=bool(suffix)):
                x = num(v)
                if x is None:
                    return v
                if how == "log10":
                    return None if err or x <= 0 else math.log10(x)       # a linear uncertainty has no log equivalent here
                x = x * how if how else x
                return -abs(x) if sign < 0 else x
            out[arch + asuf] = run[c].map(conv)
    return out


def archive_scores(run: pd.DataFrame, archive_rows: list) -> dict:
    refs = Counter(xa._strip_html(a.get("pl_refname", "")) for a in archive_rows)
    reference = refs.most_common(1)[0][0] if refs else ""
    mine = [a for a in archive_rows if xa._same_reference(a.get("pl_refname", ""), reference)]
    records = [{k: v for k, v in r.items() if v is not None} for r in run.to_dict("records")] if len(run) else []
    report = xa.compare(records, archive_rows, reference) if records else []
    best = {}                                             # (planet, quantity) -> 2 match, 1 close, 0 differs
    for e in report:
        if e.get("status") != "compared":
            continue
        planet = xa._key(e.get("archive_name") or e["pl_name"])
        for c in e.get("matches", []):
            k = (planet, _quantity(c))
            best[k] = 2
        for d in e.get("differs", []) + e.get("minor", []):
            k = (planet, _quantity(d["column"]))
            a, b = xa._number(d.get("extracted")), xa._number(d.get("archive"))
            level = 1 if (a is not None and b is not None and close(a, b, CLOSE)) or d.get("why") else 0
            best[k] = max(best.get(k, -1), level)
    rec = Counter()
    planets_found = {xa._key(e.get("archive_name") or e["pl_name"]) for e in report if e.get("status") == "compared"}
    for aset in mine:
        planet = xa._key(aset["pl_name"])
        for q in _expected(aset, reference):
            g = _archive_group(q)
            rec[f"x_{g}_expected"] += 1
            level = best.get((planet, q), -1)
            rec[f"x_{g}_found"] += level == 2
            rec[f"x_{g}_found_close"] += level >= 1
            rec[f"x_{g}_differs"] += level == 0
    out = dict(rec)
    out.update(x_archive_planets=len({xa._key(a["pl_name"]) for a in mine}),
               x_planets_found=len(planets_found & {xa._key(a["pl_name"]) for a in mine}), x_reference=reference)
    return out


# ---- 2. against the model standard -----------------------------------------------------------------------------------
ID_COLUMNS = re.compile(r"^(full_id|set_id|sample_id|entry_number|data_location|original_data_reference|paper_|"
                        r"author_list|year_published|journal|set_type|set_label|sample_label|notes?$|.*_note$|"
                        r".*_quote$|.*_source$|set_independent_variable)")
# calculated locally, not extracted (as the study leaves calculated hand columns out): flags, totals, what a set varies
CALCULATED = re.compile(r"^(is_|total_|set_independent_value$)")


def family(column: str) -> tuple:
    """(quantity key, tolerance) a column's values are compared under: the study's quantities, an exoplanet column
    (Earth / Jupiter units as one), else the column's own current name."""
    key, tol = group_of(column)
    if key:
        return key, tol
    return _quantity(current_column_name(column)), MATCH_OTHER


def _values(df: pd.DataFrame) -> dict:
    """{family: (tolerance, {numbers}, {texts})}"""
    out = {}
    for c in df.columns:
        if (ID_COLUMNS.match(c) or CALCULATED.match(c) or THERMO.search(c) or CHARGED.search(c)
                or RUN_EXCLUDE.search(c) and not c.startswith(("pl_", "st_", "sy_"))):
            continue
        key, tol = family(c)
        nums, texts = out.setdefault(key, (tol, set(), set()))[1:]
        for v in df[c].dropna():
            x = num(v)
            if x is not None:
                if x != 0:
                    nums.add(round(x, 9))
            elif str(v).strip():
                texts.add(str(v).strip())
    return out


_RANGE = re.compile(r"^\s*(-?[\d.]+(?:[eE]-?\d+)?)\s*:\s*(-?[\d.]+(?:[eE]-?\d+)?)\s*$")


def _same_text(t: str, p: str) -> bool:
    """The same text: equal ignoring case and spacing; ranges ('80:90') end by end; else half the words shared
    (the study's rule for names and titles)."""
    a, b = " ".join(str(t).lower().split()), " ".join(str(p).lower().split())
    if a == b:
        return True
    ra, rb = _RANGE.match(a), _RANGE.match(b)
    if ra and rb:
        return all(close(float(x), float(y), MATCH_OTHER) for x, y in zip(ra.groups(), rb.groups()))
    w = words(t)
    return bool(w) and len(w & words(p)) >= max(1, 0.5 * len(w))


def _text_hit(t: str, pool: set) -> bool:
    return any(_same_text(t, p) for p in pool)


def _pair_rows(run: pd.DataFrame, ms: pd.DataFrame) -> dict:
    """arm row index -> MS row index, one to one where it can be: scored by the values both give in the columns that
    tell the MS rows apart (+1 same, -1 different), the best pairs taken first, ties broken by the rows' order; arm
    rows left over (more rows than the MS) go to their best MS row."""
    shared = [c for c in run.columns if c in ms.columns and not ID_COLUMNS.match(c) and not CALCULATED.match(c)]
    telling = [c for c in shared if ms[c].nunique(dropna=True) > 1] or shared
    nr, nm = max(len(run) - 1, 1), max(len(ms) - 1, 1)
    scored = []
    for ri, (i, r) in enumerate(run.iterrows()):
        cands = ms.index
        if "pl_name" in ms.columns and r.get("pl_name"):
            same = ms.index[ms.pl_name.fillna("").map(xa._key) == xa._key(r["pl_name"])]
            cands = same if len(same) else cands
        for j in cands:
            s = 0
            for c in telling:
                a, b = r.get(c), ms.at[j, c]
                if a is None or b is None or (isinstance(b, float) and math.isnan(b)):
                    continue
                x, y = num(a), num(b)
                same = close(x, y, family(c)[1]) if x is not None and y is not None else _text_hit(str(a), {str(b)})
                s += 1 if same else -1
            if s > 0:
                order = abs(ri / nr - ms.index.get_loc(j) / nm)
                scored.append((s, -order, i, j))
    scored.sort(reverse=True)
    pairs, taken = {}, set()
    for s, _o, i, j in scored:
        if i not in pairs and j not in taken:
            pairs[i] = j
            taken.add(j)
    for s, _o, i, j in scored:                             # leftovers: their best MS row
        pairs.setdefault(i, j)
    return pairs


def ms_scores(run: pd.DataFrame, ms: pd.DataFrame) -> dict:
    rec = Counter()
    av, mv = _values(run), _values(ms)
    for key, (tol, mnums, mtexts) in mv.items():
        _t, anums, atexts = av.get(key, (tol, set(), set()))
        rec["m_ms_values"] += len(mnums) + len(mtexts)
        rec["m_found"] += sum(any(close(m, a, tol) for a in anums) for m in mnums) + sum(
            _text_hit(t, atexts) for t in mtexts)
        rec["m_found_close"] += sum(any(close(m, a, CLOSE) for a in anums) for m in mnums) + sum(
            _text_hit(t, atexts) for t in mtexts)
    for key, (tol, anums, atexts) in av.items():
        _t, mnums, mtexts = mv.get(key, (tol, set(), set()))
        rec["m_arm_values"] += len(anums) + len(atexts)
        rec["m_supported"] += sum(any(close(a, m, tol) for m in mnums) for a in anums) + sum(
            _text_hit(t, mtexts) for t in atexts)
        rec["m_supported_close"] += sum(any(close(a, m, CLOSE) for m in mnums) for a in anums) + sum(
            _text_hit(t, mtexts) for t in atexts)
    # cells: paired rows, columns both have
    pairs = _pair_rows(run, ms) if len(run) and len(ms) else {}
    rec["m_rows_paired"], rec["m_ms_rows"] = len(set(pairs.values())), len(ms)
    shared = [c for c in run.columns if c in ms.columns and not ID_COLUMNS.match(c) and not CALCULATED.match(c)]
    for i, j in pairs.items():
        for c in shared:
            a, b = run.at[i, c], ms.at[j, c]
            if b is None or (isinstance(b, float) and math.isnan(b)):
                continue
            rec["m_cells"] += 1
            if a is None:
                rec["m_cells_missing"] += 1
                continue
            x, y = num(a), num(b)
            right = close(x, y, family(c)[1]) if x is not None and y is not None else _text_hit(str(b), {str(a)})
            if right:
                rec["m_cells_right"] += 1
            elif x is not None and any(close(x, num(v), family(c)[1]) for v in ms[c].dropna() if num(v) is not None):
                rec["m_cells_elsewhere"] += 1                  # the value is the MS's, on another row
            else:
                rec["m_cells_wrong"] += 1
    return dict(rec)


def new_checked(new: dict, ms: pd.DataFrame) -> dict:
    """Values in columns the hand dataset lacks, checked against the MS (same column or quantity)."""
    mv = _values(ms)
    rec = Counter()
    for c, vals in new.items():
        key, tol = family(c)
        mnums = mv.get(key, (tol, set(), set()))[1]
        for v in vals:
            rec["h_new_confirmed" if any(close(v, m, tol) for m in mnums) else "h_new_unsupported"] += 1
    return dict(rec)


# ---- the scoring run --------------------------------------------------------------------------------------------------
def score(config: dict) -> pd.DataFrame:
    hand = pd.read_csv(config["hand_csv"], encoding="utf-8-sig", dtype=str, keep_default_na=False)
    hand["paper"] = hand.full_id.str[:3]
    ms_runs = {b: runs_of(fs, b) for b, fs in config.get("model_standard", {}).items()}
    ms_rows = {}
    texts = {}
    out = []
    for arm_id, arm in config["arms"].items():
        for batch, folders in arm["batches"].items():
            runs = runs_of(folders, batch)
            loaded = {k: rows_of(f) for k, f in runs.items()}
            arm_columns = set().union(*(set(r.columns) for r in loaded.values())) if loaded else set()
            for key, folder in sorted(runs.items()):
                meta = BATCHES.get(batch, {}).get(key, {})
                cost, seconds = cost_of(folder)
                for mode in ("written", "reviewed"):
                    run = loaded[key] if mode == "written" else with_review(loaded[key], folder)
                    run = as_archive_columns(run, folder)          # a drafted exoplanet pack's names -> the archive's
                    rec = {"arm": arm_id, "arm_label": arm.get("label", arm_id), "batch": batch, "paper": key,
                           "mode": mode, "cost_usd": cost, "seconds": seconds, "run_folder": str(folder),
                           "drafted_from": key in set(arm.get("drafted_from", [])), **row_counts(run)}
                    new = {}
                    if meta.get("hand_id"):
                        hd = hand[hand.paper == meta["hand_id"]]
                        if key not in texts:
                            raw = paper_text(Path(meta["pdf"]))
                            texts[key] = {k: printed_with_decimals(raw, UNIT_AFTER.get(k)) for k in NUMERIC}
                        h, new = hand_scores(run, hd, texts[key], arm_columns)
                        rec.update(h)
                    archive = TESTS / batch / "archive" / f"{key}.json"
                    if archive.is_file():
                        rec.update(archive_scores(run, json.loads(archive.read_text())))
                    if key in ms_runs.get(batch, {}):
                        if (batch, key) not in ms_rows:
                            ms_rows[(batch, key)] = rows_of(ms_runs[batch][key])
                        ms = ms_rows[(batch, key)]
                        if mode == "reviewed":                     # the standard's held-back values too
                            ms = with_review(ms, ms_runs[batch][key])
                        rec["has_ms"] = True
                        rec.update(ms_scores(run, ms))
                        if new:
                            rec.update(new_checked(new, ms))
                    else:
                        rec["has_ms"] = False
                        rec["h_new_unverified"] = sum(len(v) for v in new.values())
                    out.append(rec)
    return pd.DataFrame(out)


def _ratio(sub, num_cols, den_cols):
    n = sum(sub[c].sum() for c in num_cols if c in sub)
    d = sum(sub[c].sum() for c in den_cols if c in sub)
    return round(n / d, 3) if d else None


def _paper_mean(sub, num_cols, den_cols):
    vals = []
    for _, r in sub.iterrows():
        d = sum(r.get(c, 0) or 0 for c in den_cols)
        if d:
            vals.append(sum(r.get(c, 0) or 0 for c in num_cols) / d)
    return round(sum(vals) / len(vals), 3) if vals else None


def summarize(df: pd.DataFrame) -> dict:
    df = df.infer_objects().fillna(0)
    hand_keys = [k for ks in GROUPS.values() for k in ks]
    xg = ["planet", "star", "uncertainty", "discovery", "system"]
    summary = {}
    for (arm, batch, mode), sub in df.groupby(["arm", "batch", "mode"]):
        s = {"label": sub.arm_label.iloc[0], "papers": len(sub), "papers_with_rows": int((sub.rows > 0).sum()),
             "cost_usd": round(float(pd.to_numeric(sub.cost_usd, errors="coerce").sum()), 2),
             "rows": int(sub.rows.sum()), "figure_rows_waiting": int(sub.figure_rows_waiting.sum())}
        if any(f"h_{k}_printed" in sub for k in hand_keys):
            h = sub[(sub.get("hand_rows", 0) > 0) & (sub.rows > 0)]
            s["hand"] = {"papers": len(h), "hand_values_not_printed": int(h.get("h_not_printed", pd.Series([0])).sum())}
            for g, keys in list(GROUPS.items()) + [("overall", hand_keys)]:
                den = [f"h_{k}_printed" for k in keys]
                s["hand"][g] = {"recall": _paper_mean(h, [f"h_{k}_found" for k in keys], den),
                                "recall_close": _paper_mean(h, [f"h_{k}_found_close" for k in keys], den),
                                "printed": int(sum(h[c].sum() for c in den if c in h))}
            # every paper with hand data, a paper without rows counting 0 (coverage; the 'with rows' mean hides it)
            ha = sub[sub.get("hand_rows", 0) > 0]
            den = [f"h_{k}_printed" for k in hand_keys]
            s["hand"]["all_papers"] = {"papers": len(ha), "recall": _paper_mean(ha, [f"h_{k}_found" for k in hand_keys], den),
                                       "recall_close": _paper_mean(ha, [f"h_{k}_found_close" for k in hand_keys], den)}
            s["hand"]["new_values"] = int(h.get("h_new_values", pd.Series([0])).sum())
            for k in ("h_new_confirmed", "h_new_unsupported", "h_new_unverified"):
                s["hand"][k[2:]] = int(h.get(k, pd.Series([0])).sum())
            for d, part in (("drafted_from", h[h.drafted_from == True]), ("held_out", h[h.drafted_from == False])):  # noqa: E712
                if len(part) and len(part) < len(h):
                    den = [f"h_{k}_printed" for k in hand_keys]
                    s["hand"][d] = {"papers": len(part), "recall": _paper_mean(
                        part, [f"h_{k}_found" for k in hand_keys], den)}
        if any(f"x_{g}_expected" in sub for g in xg):
            x = sub[sub.get("x_archive_planets", 0) > 0]
            s["archive"] = {"papers": len(x), "planets": int(x.x_archive_planets.sum()),
                            "planets_found": int(x.x_planets_found.sum())}
            for g in xg + ["overall"]:
                gs = xg if g == "overall" else [g]
                den = [f"x_{q}_expected" for q in gs]
                s["archive"][g] = {"recall": _paper_mean(x, [f"x_{q}_found" for q in gs], den),
                                   "recall_close": _paper_mean(x, [f"x_{q}_found_close" for q in gs], den),
                                   "differs": int(sum(x[c].sum() for c in [f"x_{q}_differs" for q in gs] if c in x)),
                                   "expected": int(sum(x[c].sum() for c in den if c in x))}
        m = sub[sub.get("has_ms", False) == True]  # noqa: E712
        if len(m):
            s["model_standard"] = {
                "papers": len(m),
                "recall": _paper_mean(m, ["m_found"], ["m_ms_values"]),
                "recall_close": _paper_mean(m, ["m_found_close"], ["m_ms_values"]),
                "precision": _paper_mean(m, ["m_supported"], ["m_arm_values"]),
                "precision_close": _paper_mean(m, ["m_supported_close"], ["m_arm_values"]),
                "cells_right": _ratio(m, ["m_cells_right"], ["m_cells"]),
                "cells_elsewhere": _ratio(m, ["m_cells_elsewhere"], ["m_cells"]),
                "cells_wrong": _ratio(m, ["m_cells_wrong"], ["m_cells"]),
                "cells_missing": _ratio(m, ["m_cells_missing"], ["m_cells"]),
                "rows_paired": _ratio(m, ["m_rows_paired"], ["m_ms_rows"])}
        summary.setdefault(mode, {}).setdefault(batch, {})[arm] = s
    return summary


def markdown(summary: dict) -> str:
    lines = ["# Accuracy evaluation, November 2026: results", ""]
    for mode in ("written", "reviewed"):
        for batch, arms in sorted(summary.get(mode, {}).items()):
            lines += [f"## {batch} ({mode})", "",
                      "| Arm | Papers (with rows) | Cost | Hand recall, papers with rows (close) | Hand recall, all hand papers "
                      "| Archive recall (close) | MS recall | MS precision | Cells right | Figure rows waiting |", "|" + "---|" * 10]
            for arm, s in sorted(arms.items()):
                h, x, m = s.get("hand", {}), s.get("archive", {}), s.get("model_standard", {})
                ho, xo = h.get("overall", {}), x.get("overall", {})
                lines.append(
                    f"| {arm} {s['label']} | {s['papers']} ({s['papers_with_rows']}) | ${s['cost_usd']} | "
                    f"{ho.get('recall', '–')} ({ho.get('recall_close', '–')}) | {h.get('all_papers', {}).get('recall', '–')} | "
                    f"{xo.get('recall', '–')} ({xo.get('recall_close', '–')}) | {m.get('recall', '–')} | "
                    f"{m.get('precision', '–')} | {m.get('cells_right', '–')} | {s['figure_rows_waiting']} |")
            lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "arms.json"
    config = json.loads(cfg_path.read_text())
    out_dir = Path(config.get("out", HERE / "results"))
    out_dir.mkdir(exist_ok=True)
    df = score(config)
    df.to_csv(out_dir / "per_paper.csv", index=False)
    summary = summarize(df)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    (out_dir / "summary.md").write_text(markdown(summary))
    print(markdown(summary))
