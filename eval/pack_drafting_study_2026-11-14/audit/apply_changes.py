"""PaperDataTemplate audit (2026-11-14): apply the reviewed changes to PaperDataTemplate_Nov14_2026.csv.

Writes, next to the source:
- PaperDataTemplate_parse_clean_v1.csv -- the same file (header, rows, order, encoding, line endings); rows without a
  change are copied byte for byte, changed rows re-written in the same CSV dialect;
- PaperDataTemplate_parse_clean_v1_changes.csv -- one line per changed cell: full_id, paper, column, before, after,
  confidence, justification (with the paper's words).
"""
import csv
import io
from pathlib import Path

SRC = Path("/Users/mickeymuscalli/Documents/EORE Data Project/PaperDataTemplate Archive/PaperDataTemplate_Nov14_2026.csv")
OUT = SRC.with_name("PaperDataTemplate_parse_clean_v1.csv")
LOG = SRC.with_name("PaperDataTemplate_parse_clean_v1_changes.csv")

raw = SRC.read_bytes()
assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
lines = raw[3:].decode("utf-8").split("\r\n")
header = next(csv.reader([lines[0]]))
col = {name: i for i, name in enumerate(header) if name}
rows = {}                                    # full_id -> (line index, parsed row)
for k, line in enumerate(lines[1:], start=1):
    if line:
        r = next(csv.reader([line]))
        rows[r[0]] = (k, r)

changes = []                                 # (full_id, column, after, confidence, justification)


def fmt(x):
    if isinstance(x, str):
        return x
    return f"{x:.6g}" if abs(x) < 1e6 else f"{x:.0f}"


def change(fid, column, after, confidence, why, expect=None):
    k, r = rows[fid]
    before = r[col[column]]
    if expect is not None:
        assert before == expect, (fid, column, before, expect)
    after = fmt(after)
    if before != after:
        changes.append((fid, column, before, after, confidence, why))
        r[col[column]] = after


def ids(prefix):
    return sorted(f for f in rows if f.startswith(prefix))


# ---- Sakata2014 (037): heating times are in DAYS -----------------------------------------------------------------
why = ("Sakata2014 Table 1 gives 'Heating time (days)' (74, 14, 14, ...); the abstract: 'heated for 1-74 days at "
       "140°C'. The hand values are the day counts entered as hours; converted to hours (x 24).")
for fid in ids("037"):
    days = float(rows[fid][1][col["duration_hr"]])
    change(fid, "duration_hr", days * 24, "high", why)

# ---- Alargov2002 (001): reaction time is the ~10 s residence time ---------------------------------------------------
why = ("Alargov2002: 'The residence time of the injection solution for reaction at high temperature ... was "
       "calculated to be about 10 sec.' 0.02 h is the 12 mL injection at 10 mL/min (1.2 min), not the reaction time; "
       "the other flowthrough papers (faisal2005, Islam2003) record the residence time as duration_hr.")
for fid in ids("001"):
    change(fid, "duration_hr", 10 / 3600, "medium", why, expect="0.02")

# ---- Steinman1966 (032): 5 min, and dicyanamide in every Table I mixture -------------------------------------------
for fid in ids("032"):
    change(fid, "duration_hr", 5 / 60, "high", "Steinman1966: 'After 5 min of reaction the solutions were analyzed "
           "... The results are summarized in Table I.' (the four rows are Table I's 8.9 / 3.8 / 13.9 / 9.8 %)",
           expect="0.167")
    change(fid, "initial_C2N3Na_aq_mM", 100, "high", "Steinman1966, Table I experiments: 'Two pairs of reaction "
           "mixtures were prepared, each containing glycine (0.01 M), diglycine (0.01 M) and sodium dicyanamide "
           "(0.1 M)' -- filled on the rows that lacked it (the set's first row had 100 mM).")

# ---- Eder1992 (030): [Asp]/[Cu2+] = 2:1 in Table 1's first two blocks -----------------------------------------------
why = ("Eder1992 Table 1: the block is '[L-Asp]/[Cu2+] = 2:1' (resp. '[DL-Asp]/[Cu2+] = 2:1'), so Cu2+ is half "
       "the row's Asp; 330 mM is only right for the 0.66 M rows. Row's Asp: {asp} M -> Cu2+ {cu} mM.")
for fid, asp in (("030001002", 0.95), ("030002001", 0.24), ("030002005", 0.75)):
    change(fid, "initial_CuCl2_aq_mM", asp * 1000 / 2, "high", why.format(asp=asp, cu=fmt(asp * 500)), expect="330")

# ---- Gao2011 (034): Mg2+ 0.02 / 0.05 / 0.1 M; pD of entries 4-6 --------------------------------------------------
for fid, mg in (("034001004", 0.02), ("034001005", 0.05), ("034001006", 0.1)):
    change(fid, "initial_MgCl2_aq_mM", mg * 1000, "high",
           f"Gao2011 Table 1 (concentrations in m = mol/L): 'MMP-Gly (0.2) + Mg2+ ({mg})' -> {fmt(mg * 1000)} mM. "
           "0.025 is the amount (mol) of acetyl chloride in a synthesis procedure.", expect="0.025")
    change(fid, "initial_pH", 4, "medium",
           "Gao2011 Experimental, entries 4-6: 'The pD of the solution was adjusted to 4.0-...'; the set's other "
           "entries are recorded as pH 4 for the same procedure.", expect="")

# ---- Chen2007 (042): amounts (mmol) entered as mM -------------------------------------------------------------
so2 = ("Chen2007 (SO2 as sulfur source): 'L-phenylalanine (1 mmol) and potassium ferricyanide (10 mmol) in aqueous "
       "buffer (10 mmol of Na2CO3 or 40 mmol of NaHCO3 in 10 mL of water)'. The hand values are the amounts in mmol; "
       "concentration = mmol / 0.010 L.")
bis = ("Chen2007 (NaHSO3 as sulfur source): 'L-phenylalanine (1 mmol) and potassium ferricyanide (5 mmol) in aqueous "
       "buffer (10 mmol of Na2CO3 or 40 mmol of NaHCO3 in 5 mL of water) was added a solution of NaHSO3 (6 mmol) in "
       "water (5 mL)' -- 10 mL in all. The hand values are the amounts in mmol; concentration = mmol / 0.010 L.")
for fid in ids("042"):
    r = rows[fid][1]
    is_so2 = r[col["initial_SO2_gas_mL"]] != ""
    why = so2 if is_so2 else bis
    for c in ("initial_K3[Fe(CN)6]_aq_mM", "initial_Na2CO3_aq_mM", "initial_NaHCO3_aq_mM", "initial_NaHSO3_aq_mM",
              "initial_Phe_mM"):
        if r[col[c]].strip():
            change(fid, c, float(r[col[c]]) * 100, "high", why)
    if not is_so2:
        change(fid, "solvent_volume_mL", 10, "high", "Chen2007 (NaHSO3 procedure): 5 mL of buffered solution plus "
               "NaHSO3 in 5 mL of water -- 10 mL in all (the concentrations above use it).", expect="5")

# ---- Huber1998 (022): amounts entered as concentrations ------------------------------------------------------------
why = ("Huber1998: '500 [u]mol of the amino acid were reacted in a slurry of 1 mmol of FeS and 1 mmol of NiS in 10 ml "
       "of water with 4 mmol of CO gas ... in the presence of 500 [u]mol of hydrogen sulfide (H2S) or methanethiol "
       "(CH3SH) ... In some of the runs 500 [u]mol of Na2HPO4 were added.' ('500 mmol' in the PDF's text has lost its "
       "micro sign: 500 mmol of glycine in 10 mL would be 50 M.) Concentration = amount / 0.010 L.")
for fid in ids("022"):
    r = rows[fid][1]
    for c, conc in (("initial_Gly_mM", 50), ("initial_CH3SH_aq_mM", 50), ("initial_H2S_aq_mM", 50),
                    ("initial_Na2HPO4_aq_mM", 50), ("initial_FeS_aq_mM", 100), ("initial_NiS_aq_mM", 100)):
        if r[col[c]].strip():
            change(fid, c, conc, "high", why)

# ---- Nooner1977 (048): dried and heated; amounts entered as concentrations ----------------------------------------
for fid in ids("048"):
    r = rows[fid][1]
    change(fid, "solution_type", "Drydown", "high",
           "Nooner1977: 'aqueous solutions of glycine, isoleucine or phenylalanine were dried and heated for 24 h at "
           "90°C'; 'cyanamide as a condensing agent under dehydrating conditions'; heated 'in open glass vials'. "
           "(Shen1990, the same cyanamide/AICA system dried and heated, is recorded as Drydown.)", expect="Wet")
    for c, mmol in (("initial_ATP_aq_mM", 0.555), ("initial_cyanamide_aq_mM", 0.25), ("initial_AICA_aq_mM", 0.25),
                    ("initial_Phe_mM", 0.75)):
        if r[col[c]].strip():
            change(fid, c, round(mmol / 0.0009, 1), "medium",
                   "Nooner1977: 'Typical unlabeled reaction mixtures consisted of aqueous solutions (0.8-1.0 ml) of "
                   "ATP (0.555 mmole), cyanamide (0.25 mmole), AICA (0.25 mmole) and amino acid (0.75 mmole).' The "
                   "hand values are the amounts; concentration = mmol / 0.0009 L (the middle of 0.8-1.0 mL, so "
                   "+/- 11 %).")

# ---- one spelling for the solvent ---------------------------------------------------------------------------------
for fid, (k, r) in rows.items():
    if r[col["solvent_name"]] == "Water":
        change(fid, "solvent_name", "water", "high", "Consistency: every other row writes 'water' (1,297 rows); the "
               "capitalised form split one solvent into two values.")

# ---- write ----------------------------------------------------------------------------------------------------------
changed_rows = {fid for fid, *_ in changes}
for fid in changed_rows:
    k, r = rows[fid]
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(r)
    lines[k] = buf.getvalue()
OUT.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8"))
paper = {"001": "Alargov2002", "022": "Huber1998", "030": "Eder1992", "032": "Steinman1966", "034": "Gao2011",
         "037": "Sakata2014", "042": "Chen2007", "048": "Nooner1977", "002": "Sakata2010", "003": "Islam2003"}
with open(LOG, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["full_id", "paper", "column", "before", "after", "confidence", "justification"])
    for fid, c, before, after, conf, why in changes:
        w.writerow([fid, paper.get(fid[:3], fid[:3]), c, before, after, conf, why])
print(f"{len(changes)} cells changed in {len(changed_rows)} rows -> {OUT.name}; log {LOG.name}")
