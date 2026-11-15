"""PaperDataTemplate_parse_clean_v2.csv from v1 (Mickey's answers, 2026-11-14):
1. author1-author7 -> one `author_list` in author1's place, joined like the app ('; ').
2. Nooner1977: 90 °C and 24 h (the paper's stated conditions).
3. Huber1998's gases as the paper reports them: initial_CO_gas_mmol (4 mmol), initial_H2S_gas_mmol / initial_CH3SH_gas_mmol
   (0.5 mmol, Table 1) -- columns renamed in place (only Huber1998 uses them).
4. The four papers added to the folder: Cleaves2009's Fig. 3 time series is 10^-2 M glycine; Grégoire2018's mineral
   experiments are at pH 9-9.5.
Same file format as v1: BOM, CRLF, no line break after the last row, QUOTE_MINIMAL.
"""
import csv
import io
from pathlib import Path

DIR = Path("/Users/mickeymuscalli/Documents/EORE Data Project/PaperDataTemplate Archive")
SRC, OUT, LOG = (DIR / "PaperDataTemplate_parse_clean_v1.csv", DIR / "PaperDataTemplate_parse_clean_v2.csv",
                 DIR / "PaperDataTemplate_parse_clean_v2_changes.csv")
raw = SRC.read_bytes()
rows = list(csv.reader(io.StringIO(raw[3:].decode("utf-8"), newline="")))
header, body = rows[0], rows[1:]
col = {n: i for i, n in enumerate(header) if n}
log = []


def fmt(x):
    return x if isinstance(x, str) else f"{x:.6g}"


def setv(r, column, after, confidence, why):
    before = r[col[column]]
    after = fmt(after)
    if before != after:
        log.append((r[0], column, before, after, confidence, why))
        r[col[column]] = after


paper = lambda r: r[0][:3]

# ---- 2. Nooner1977 (048) --------------------------------------------------------------------------------------
why = ("Mickey: use the paper's stated conditions. Nooner1977: 'aqueous solutions of glycine, isoleucine or "
       "phenylalanine were dried and heated for 24 h at 90°C'; 'The presumed peptides from the glycine containing "
       "reaction (temperature = 90°C, time = 24 h)'.")
for r in body:
    if paper(r) == "048":
        setv(r, "initial_temperature_C", 90, "high", why)
        setv(r, "duration_hr", 24, "high", why)

# ---- 3. Huber1998 (022): the gases as reported -----------------------------------------------------------------
gas_why = ("Mickey: record the gases in the unit the paper reports. Huber1998: 'in 10 ml of water with 4 mmol of CO "
           "gas (1 bar) in the presence of 500 [u]mol of hydrogen sulfide (H2S) or methanethiol (CH3SH)'; Table 1 lists "
           "H2S / CH3SH per run as 0.5 (mmol).")
for old, new, value in (("initial_CO_gas_mM", "initial_CO_gas_mmol", 4), ("initial_H2S_aq_mM", "initial_H2S_gas_mmol", 0.5),
                        ("initial_CH3SH_aq_mM", "initial_CH3SH_gas_mmol", 0.5)):
    i = col.pop(old)
    header[i] = new
    col[new] = i
    log.append(("(header)", new, old, new, "high", f"Column renamed (used only by Huber1998): a gas amount, not a "
                                                    f"concentration in solution. {gas_why}"))
    for r in body:
        if r[i].strip():
            assert paper(r) == "022", (old, r[0])
            setv(r, new, value, "high", gas_why)

# ---- 4a. Cleaves2009 (009): Fig. 3 is 10^-2 M glycine ---------------------------------------------------------------
fig3 = ("Cleaves2009 Fig. 3: 'Peptide yield and glycine recovery versus time at 2400 psi (165 bar) at 200°C from 10-2 M "
        "initial glycine' -- 10 mM, not 100 (the 100 mM experiments are Fig. 2A, at fixed 20 min).")
derived = (" The row's product concentrations are its % yields (and % recovery) times the initial glycine "
           "(0.157 % DKP x 100 mM / 2 = 0.0786 mM), so they scale with it (x 0.1); the yields, read from the "
           "figure, are unchanged.")
for r in body:
    if paper(r) == "009":
        setv(r, "initial_Gly_mM", 10, "high", fig3)
        for c in ("sampled_Gly_mM", "sampled_DKP_Gly_mM", "sampled_2peptide_Gly_mM", "sampled_3peptide_Gly_mM",
                  "sampled_4peptide_Gly_mM"):
            if r[col[c]].strip():
                setv(r, c, float(r[col[c]]) / 10, "high", fig3 + derived)

# ---- 4b. Grégoire2018 (006): pH of the mineral experiments ----------------------------------------------------------
why = ("Grégoire2018: 'the pH of the starting solution in contact with the solid catalyst was very similar in each case, "
       "because of the strong buffering capacity of these carbonate materials, with values ranging from pH 9 to pH 9.5' "
       "(and 'alkaline with pH values of 9-9.5'). 9.8 isn't stated; the middle of the stated range is used.")
for r in body:
    if paper(r) == "006" and r[col["initial_pH"]] == "9.8":
        setv(r, "initial_pH", 9.25, "medium", why)

# ---- 1. one author list (last: it moves the columns) ----------------------------------------------------------------
authors = [col[f"author{i}"] for i in range(1, 8)]
assert authors == list(range(authors[0], authors[0] + 7))
first = authors[0]
for r in body:
    names = [r[i].strip() for i in authors if r[i].strip()]
    r[first:first + 7] = ["; ".join(names)]
header[first:first + 7] = ["author_list"]
log.append(("(header)", "author_list", "author1 ... author7", "author_list", "high",
            "Mickey: one author field in the parser app's format -- the names in order, joined with '; ' "
            "(flatten_to_template.AUTHOR_SEPARATOR). No name contains ';'. Rodriguez-Garcia2015 and Ying2019 filled all "
            "seven columns: both papers have exactly seven authors, so no list was cut short."))

buf = io.StringIO(newline="")
csv.writer(buf, lineterminator="\r\n").writerows([header] + body)
text = buf.getvalue()
OUT.write_bytes(b"\xef\xbb\xbf" + text[:-2].encode("utf-8"))           # v1 has no line break after the last row
names = {"048": "Nooner1977", "022": "Huber1998", "009": "Cleaves2009", "006": "Grégoire2018"}
with open(LOG, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["full_id", "paper", "column", "before", "after", "confidence", "justification"])
    for fid, c, before, after, conf, why in log:
        w.writerow([fid, names.get(fid[:3], "") if fid[0].isdigit() else "", c, before, after, conf, why])
print(f"{len(log)} changes (incl. {sum(1 for x in log if x[0] == '(header)')} column changes); "
      f"{len(header)} columns, {len(body)} rows -> {OUT.name}")
