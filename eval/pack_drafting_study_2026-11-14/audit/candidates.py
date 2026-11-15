import sys, re, math, json
sys.path.insert(0, sys.argv[1]); from common import *
PACKS = ["peptide_pack_5", "peptide_pack_25", "peptide_pack_56", "prebiotic_chemistry"]
_NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?:\s*[×x]\s*10\s*[-−–]?\s*(\d+)|[eE]([-+]?\d+))?")
UNITS = {"temp": r"\s*(?:°|º|o)?\s*[CK]\b", "time": r"\s*(?:h|hr|hrs|hours?|min|mins|minutes?|d|days?|s|sec|weeks?)\b",
         "pH": None, "vol": r"\s*(?:mL|ml|L|l|µL|μL|uL|cm3)\b", "mass": r"\s*(?:g|mg|µg|μg|kg)\b",
         "flow": r"\s*(?:mL|ml)\s*/?\s*(?:min|h|s)", "conc": r"\s*(?:mM|M|µM|μM|mol|mmol|µmol|μmol|N)\b",
         "pres": r"\s*(?:bar|MPa|kPa|Pa|psi|atm|torr)\b", "count": None}
FACTORS = {"temp": [1], "time": [1, 60, 1 / 24, 3600], "pH": [1], "vol": [1, 1e-3, 1e3], "mass": [1, 1e3, 1e6],
           "flow": [1, 60, 1 / 60], "conc": [1, 1e-3, 1e3], "pres": [1, 0.1, 100, 14.5038, 1 / 1.01325], "count": [1]}
COLS = {"initial_temperature_C": "temp", "initial_pH": "pH", "solvent_volume_mL": "vol", "loading_volume_mL": "vol",
        "solid_material_mass_g": "mass", "flow_rate_mL_min": "flow", "cycle_number": "count",
        "cycle_duration_hr": "time", "duration_hr": "time"}
CHARGED = re.compile(r"[+-]\d*_mM$")
def printed(text, kind):
    out = []
    for m in _NUM.finditer(text):
        if UNITS[kind] and not re.match(UNITS[kind], text[m.end():m.end() + 14]): continue
        v = float(m.group(1))
        if m.group(2): v *= 10 ** (-int(m.group(2)) if re.search("[-−–]", m.group(0)) else int(m.group(2)))
        elif m.group(3): v *= 10 ** int(m.group(3))
        out.append(v)
    return out
def is_pr(v, kind, nums): return any(abs(n - v * f) <= 0.01 * abs(v * f) + 1e-12 for f in FACTORS[kind] for n in nums if v * f)
def close(a, b): return abs(a - b) <= max(0.02 * max(abs(a), abs(b)), 0.01)
def vals(df, col):
    out = set()
    if col in df.columns:
        for x in df[col]:
            try:
                f = float(x)
                if math.isfinite(f): out.add(round(f, 6))
            except ValueError: pass
    return out
cands = []
for name, hid in hand_map.items():
    if not hid: continue
    h = hand[hand.paper == hid]
    text = paper_text(name)
    runs = {p: run_rows(p, name) for p in PACKS}
    cols = dict(COLS)
    for c in h.columns:
        if c.startswith("initial_") and c.endswith("_mM") and not (CHARGED.search(c) and "_aq_" not in c) and "total" not in c:
            cols[c] = "conc"
    for col, kind in cols.items():
        hv = vals(h, col)
        if not hv: continue
        nums = printed(text, kind)
        rcol = col if not col.startswith("initial_") or col in COLS else None
        rv = set()
        for p, r in runs.items():
            if rcol: rv |= vals(r, col)
            else:              # starting compounds: the parse's column names may differ ('initial_Gly_aq_mM')
                stem = col[len("initial_"):].replace("_aq_mM", "").replace("_mM", "")
                for c2 in r.columns:
                    if c2.startswith("initial_") and c2.endswith("_mM") and c2.replace("_aq", "") in (f"initial_{stem}_mM",):
                        rv |= vals(r, c2)
        for v in sorted(hv):
            if v == 0 and kind in ("conc",): continue
            pr = is_pr(v, kind, nums)
            in_run = any(close(v, x) for x in rv)
            if not pr and not in_run and rv:
                alt = sorted(x for x in rv if is_pr(x, kind, nums) and not any(close(x, y) for y in hv))
                if alt:
                    n = int((pd.to_numeric(h[col], errors="coerce").round(6) == v).sum())
                    cands.append({"paper": name, "id": hid, "column": col, "hand_value": v, "hand_rows": n,
                                  "parse_values_printed": alt[:6]})
c = pd.DataFrame(cands)
c.to_csv(Path(sys.argv[1]) / "candidates.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
print(len(c), "candidates"); print(c.to_string())
