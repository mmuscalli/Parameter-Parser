"""PaperDataTemplate_parse_clean_v3.csv from v2 (Mickey, 2026-11-15):
1. analysis_method -> analysis_technique, with the Analysis methods module's technique names (analysis_vocab.json)
   instead of the broad groups (HPLC, LC-MS, LC-UV, Ion Exchange, ...).
2. A new analysis_instrument column after it: the module's `instrument` setting (make and model as printed).

Source: the study runs' analysis step (four packs per paper, pack_study_20261114/*/analysis.output.json), checked
against the papers' methods; the four papers without study runs (006-009) read from the papers.

What a row gets: the techniques that measured or identified the products recorded in that row, the measuring one
first. Left out: characterisation of minerals / catalysts, pH and redox measurement, and techniques for species the
row doesn't record. Several techniques: joined with '; ' (the app's separator for several values in one cell).
Instruments: one technique -> the instrument alone; several -> 'technique: instrument' for each technique whose
instrument is stated, so each instrument stays tied to its technique. Blank when the paper names none.
Same file format as v2: BOM, CRLF, no line break after the last row.
"""
import csv
import io
from pathlib import Path

DIR = Path("/Users/mickeymuscalli/Documents/EORE Data Project/PaperDataTemplate Archive")
SRC, OUT, LOG = (DIR / "PaperDataTemplate_parse_clean_v2.csv", DIR / "PaperDataTemplate_parse_clean_v3.csv",
                 DIR / "PaperDataTemplate_parse_clean_v3_changes.csv")

HP1090 = "Hewlett-Packard HP-1090M"
HITACHI_IMAI = "Hitachi L-6300 / L-4200 / D-2500 HPLC"
ESQUIRE = "Bruker Esquire 4000 ion trap"
RANK = "Chromaspeak Rank Hilger amino acid analyser"
SAKATA = "TOA DKK ICA-2000 with Jasco UV-2075 detector"
RUNS = "study runs (all four packs)"

# paper -> (name, [(technique, instrument)], source of the techniques / instruments)
P = {
    "001": ("Alargov2002", [("RP-HPLC", "Shimadzu HPLC with auto-injector"), ("TLC", "")],
            "'Identification and quantification of glycine, diketopiperazine, diglycine and triglycine were made by "
            "HPLC'; ion-pair on a Shodex Asahipak ODP-50 column; 'confirmed' by TLC. (The Hitachi L-8500 amino acid "
            "analyser was for the formaldehyde/ammonia runs, not these rows.)"),
    "002": ("Sakata2010", [("RP-HPLC", SAKATA)], "'determined by a liquid chromatograph (ICA-2000; TOA DKK) equipped "
            "with a UV detector (UV-2075; Jasco)', reverse-phase column"),
    "003": ("Islam2003", [("RP-HPLC", "TOSOH DP 8020 pump with TOSOH UV-8020 detector"),
                          ("CEX-HPLC", "Shimadzu LC-6A with Shimadzu RF-535 fluorescence detector")],
            "peptides by 'Ion-pair-HPLC system (pump: TOSOH DP 8020)' on Inertsil ODS-80A with 'UV-detector (TOSOH "
            "UV-8020)'; glycine by 'cation-exchange HPLC system (pumps: Shimadzu LC-6A)' with 'Shimadzu RF-535 "
            "spectrofluorometric detector'"),
    "004": ("Eder1994", [("RP-HPLC", "Hewlett-Packard 1090M")], RUNS),
    "005": ("Rode1990", [("RP-HPLC", HP1090), ("FTIR", "")],
            "'analyzed by a Hewlett-Packard HP-1090M HPLC apparatus', diode array at 195 nm; isolated diglycine "
            "identified by IR"),
    "006": ("Grégoire2018", [("RP-HPLC", "Waters 600s with diode array detector")],
            "'reverse-phase ion-pairing chromatography on a Waters 600s system, equipped with a diode array "
            "detector', Waters ODS column, 200 nm"),
    "007": ("Rodriguez-Garcia2015", [("RP-HPLC", "Agilent 1100"), ("SEC-MS", "Agilent 1100"),
                                     ("nESI-MS", "Thermo LTQ Orbitrap XL")],
            "'IP-HPLC analysis was performed using an Agilent 1100 HPLC system fitted with a reversed-phase C18 "
            "column'; identity by 'SEC-MS analyses ... (also with an Agilent 1100)' and direct-infusion MS/MS on an "
            "'LTQ Orbitrap XL' (SI Figs 29-35, NSI). SEC-MS isn't in the module's vocabulary: the paper's name, as "
            "the step would write it. (MALDI was of the insoluble fraction, not these rows.)"),
    "008": ("Imai1999", [("RP-HPLC", HITACHI_IMAI), ("LC-MS", "")],
            "'All samples were analyzed with a Hitachi (L-6300, L-4200, and D-2500) HPLC apparatus with a Shodex "
            "Asahipak column (ODP-50)'; 'We also identified these species with LC mass spectroscopy'"),
    "009": ("Cleaves2009", [("RP-HPLC", ""), ("HPLC", "")],
            "oligomers 'using RP-HPLC with UV detection at 210 nm with a Phenomenex 150x4.6 mm C-18(2) column'; "
            "glycine 'according to the method of Zhao and Bada (1995) after derivatization with o-phthaldialdehyde "
            "N-acetyl-L-cysteine' (HPLC, mode not stated). No instrument named."),
    "010": ("Imai1998", [("RP-HPLC", HITACHI_IMAI), ("LC-MS", "")], RUNS + "; 'Hitachi (L-6300, L-4200 and "
            "D-2500) HPLC apparatus', Shodex Asahipak ODP-50"),
    "011": ("Bujdak1996", [("RP-HPLC", HP1090)], "'Hewlett-Packard HP-1090M HPLC apparatus', Hypersil ODS"),
    "012": ("fuchida2014", [("RP-HPLC", "")], RUNS + "; no HPLC instrument named (the named Rigaku XRD and "
            "Shimadzu FT-IR characterised the clay)"),
    "013": ("lemke2009", [("RP-HPLC", "Waters 490E")], "'Waters 490E HPLC apparatus', Hypersil ODP column"),
    "014": ("Matrajt2003", [("amino-acid-analyzer", "Biotronik LC2000"), ("RP-HPLC", "")],
            "glycine / alanine 'with the Biotronik LC2000 analyser'; dipeptides 'by HPLC on a Hyperchrome SC18 "
            "column' (no instrument named)"),
    "015": ("iqubal2017", [("RP-HPLC", "Waters 2489 binary system"), ("ESI-MS", ESQUIRE)],
            RUNS + "; XRD, FTIR, SEM, TEM, BET and VSM characterised the ferrites"),
    "016": ("shanker2012", [("RP-HPLC", "Waters 2489 binary system"), ("ESI-MS", ESQUIRE)],
            RUNS + "; XRD, SEM and TEM characterised the iron oxides"),
    "017": ("kumar2012", [("RP-HPLC", "Waters 2489 binary system"), ("ESI-MS", ESQUIRE)],
            RUNS + "; elemental analysis, AAS, TGA, SEM, FTIR and BET characterised the catalysts"),
    "018": ("mitsuzawa2004", [("RP-HPLC", "JASCO HPLC")], RUNS),
    "019": ("Yoshiaki2000", [("RP-HPLC", HITACHI_IMAI), ("LC-MS", "")],
            "'All samples were analyzed by a Hitachi (L-6300, L-4200 and D-2500) HPLC apparatus', Shodex Asahipak "
            "ODP-50; oligomers identified by LC-MS. (UV-Vis measured ferrous ions, not these rows.)"),
    "020": ("faisal2005", [("amino-acid-analyzer", "Shimadzu LC-10A"), ("IC", "Dionex DX-100")],
            RUNS + "; Gly, Gly-Gly and cyclo(Gly-Gly) on the amino acid analyser, ammonia and methylamine (also in "
            "these rows) by ion chromatography. (HPLC of organic acids and TOC / TN aren't in the rows.)"),
    "021": ("Schwendinger1991", [("RP-HPLC", "Hewlett-Packard 1090M")], RUNS),
    "022": ("Huber1998", [("RP-HPLC", "Merck-Hitachi L-7100 pump with L-7400 UV detector"),
                          ("LC-MS", "Hewlett-Packard Series 1100 HPLC with Finnigan LCQ")],
            "yields 'using Merck-Hitachi Pump L-7100, with the columns Nucleosil 10C18', 'ultraviolet detector "
            "Merck-Hitachi L-7400'; identity 'by HPLC-MS-ESI, using Hewlett-Packard Series 1100 (HPLC) and LCQ "
            "Finnigan Mat'"),
    "023": ("Yamanaka1987", [("CEX-HPLC", "Hitachi Model 638-50")],
            "'HPLC system which is similar to amino acid analyzing system by ninhydrin reaction [Hitachi Model "
            "638-50; Column: Hitachi gel No. 2619 (cation exchange porous polymer)]'. (31P NMR and anion-exchange "
            "HPLC were for the phosphates, not these rows.)"),
    "024": ("Flores1973", [("amino-acid-analyzer", ""), ("GC", "")],
            "'analysed for linear glycine peptides on an automatic amino acid analyser' (not named); diglycine "
            "confirmed by GC"),
    "025": ("Nagayama1989", [("HPLC", ""), ("RP-HPLC", "")],
            "oligoglycines by 'HPLC with a ninhydrin reaction system' (the method of Yamanaka et al. 1988, mode not "
            "stated here); 'DKP (glycine anhydride) was analyzed by HPLC (ODS column ...)'. No instrument named."),
    "026": ("Chang1969", [("amino-acid-analyzer", "modified Phoenix automatic analyzer"), ("paper-electrophoresis", ""),
                          ("GC-MS", "Varian 1520 gas chromatograph with Consolidated Electrodynamics 21-110 mass "
                                    "spectrograph")],
            RUNS + "; diglycine yields on the analyser, isolated by paper electrophoresis and confirmed by GC-MS. "
            "(UV-Vis followed the tetramer, not these rows.)"),
    "027": ("Rabinowitz1969", [("amino-acid-analyzer", "Phoenix K-8000 VG-B"), ("TLC", "")],
            "'comparing the peak on the chromatogram (Phoenix amino-acid analyser model K-8000 VG-B)'; diglycine "
            "also identified by TLC"),
    "028": ("Leman2015", [("LC-MS", "Hitachi 7000 series HPLC with Hitachi M-8000 mass spectrometer")],
            "'HPLC-MS with a Hitachi 7000 series HPLC system coupled to a Hitachi M-8000 mass spectrometer', "
            "Agilent Zorbax SB-C18 column. (NMR, HRMS and UV-Vis were for isolated compounds and stock solutions.)"),
    "029": ("Mizutani1981", [("amino-acid-analyzer", "Durrum D-500")],
            "'analyzed for the reaction products by a Durrum D-500 amino acid analyzer'. (UV-Vis measured the "
            "polynucleotides, not these rows.)"),
    "030": ("Eder1992", [("RP-HPLC", "Hewlett-Packard 1090M with diode array detector")],
            RUNS + "; (the ABB-GOERZ recorder logged pH and redox potential, not these rows)"),
    "031": ("Halmann1968", [("paper-electrophoresis", ""), ("radiolabel", "")],
            "'Results, based on paper electrophoretic analysis' of 14C-labelled glycine products (Table II). No "
            "instrument named. (UV-Vis measured cyanamide.)"),
    "032": ("Steinman1966", [("paper-electrophoresis", ""), ("radiolabel", ""), ("paper-chromatography", "")],
            "'The low voltage horizontal paper electrophoretic method ... was the principal analytical procedure'; "
            "'Yields of radioactive products were determined by counting the activity'; identities by paper "
            "co-chromatography. No instrument named."),
    "033": ("Leman2004", [("RP-HPLC", ""), ("LC-MS", ""), ("NMR-1H", "")],
            "'Reaction yields were determined by reversed-phase HPLC analysis'; products identified 'by liquid "
            "chromatography-mass spectrometry (LC-MS) and 1H-nuclear magnetic resonance (NMR)'. No instrument named."),
    "034": ("Gao2011", [("NMR-31P", "Bruker 400 MHz"), ("HPLC", ""),
                        ("LC-MS", "Bruker Esquire 3000 plus ion trap with Agilent 1100 binary pump")],
            "phosphate yields 'determined by integration of the 31P NMR spectra' ('Bruker 400 MHz NMR "
            "spectrometer'); 'Peptide yields were determined ... by HPLC' after OPA/MPA derivatisation (instrument "
            "not named); peptides identified by LC-MS ('Bruker Esquire 3000 plus' ion trap 'coupled to an Agilent "
            "1100 binary pumping system')"),
    "035": ("Chung1971", [("paper-electrophoresis", ""),
                          ("radiolabel", "Baird-Atomic RSC-363 scanner; Beckman IS-200 liquid scintillation counter"),
                          ("amino-acid-analyzer", "")],
            RUNS + "; yields of the labelled products by paper electrophoresis and counting, confirmed on an amino "
            "acid analyser. 'IS-200' is as printed (probably the LS-200)."),
    "036": ("Zamaraev1996", [("RP-HPLC", "Waters 600E with Model 484 tunable absorbance detector (Millipore)")],
            "'HPLC analyses were performed using a Waters 600E controller ... and a Model 484 tunable absorbance "
            "detector (Millipore, USA)', after dansylation. (NMR / FTIR detected piperazinedione, which these rows "
            "don't record; EPR, pH, thermal analysis and XRD were of the silicates.)"),
    "037": ("Sakata2014", [("RP-HPLC", SAKATA)], RUNS),
    "038": ("Fuchida2016", [("RP-HPLC", "GL Science GL-7450 UV detector")],
            "'InertSustain C18 column ... and analyzed using UV detector (GL-7450, GL Science) at 195 nm'"),
    "039": ("Takaoka1991", [("amino-acid-analyzer", "Hitachi L-8500")],
            "'computer controlled amino acid analyzer with a ninhydrin reaction system (Hitachi L-8500 ...)'"),
    "040": ("Kawamura2009", [("AEX-HPLC", "Shimadzu LC10A")],
            "'on a LC10A HPLC system (Shimadzu, Japan) with a DNA-NPR anion-exchange column'. (Reversed-phase HPLC "
            "was for the alanine runs, not these Asp rows.)"),
    "041": ("Shen1990", [("RP-HPLC", "LDC/Milton Roy HPLC (ConstaMetric I and III pumps, SpectroMonitor 3000 "
                                    "detector)"), ("TLC", "")],
            "'The system consisted of an LDC/Milton Roy HPLC, a ConstaMetric I pump and a ConstaMetric III pump, a "
            "SpectroMonitor 3000 variable wavelength detector, and a Waters uBondapak C18' column; His-His "
            "identified by TLC"),
    "042": ("Chen2007", [("RP-HPLC", ""), ("LC-MS", "Finnigan SpectraSYSTEM P4000 HPLC with Finnigan MAT Navigator")],
            "yields 'quantified using the internal standard' by HPLC on an 'Alltima ... reverse-phase C18' column "
            "(instrument not named); 'also confirmed by using Finnigan HPLC-MS with a SpectraSYSTEM P4000 series "
            "HPLC system coupled to a Finnigan MAT Navigator mass detector'. (1H NMR was for the amide couplings, "
            "Tables 1-2, not these rows.)"),
    "043": ("Inoue1993", [("CE", "Waters Quanta-4000; Applied Biosystems Model 270A")],
            RUNS + "; the dipeptides by capillary electrophoresis. (Anion-exchange HPLC and 31P NMR were for the "
            "phosphorylated products.)"),
    "044": ("Inoue1994", [("AEX-HPLC", "JASCO Tri-rotar VI with JASCO FIU-300 flow injection system"),
                          ("CE", "Waters Quanta-4000; Applied Biosystems Model 270A")], RUNS),
    "045": ("Rabinowitz1985", [("amino-acid-analyzer", RANK)], RUNS),
    "046": ("Bujdak2000", [("RP-HPLC", HP1090)], RUNS + "; (DTA / TG characterised the alumina mixtures)"),
    "047": ("Yamagata1997", [("CEX-HPLC", "")],
            "'detected by the absorption at 570 nm of the solution separated with HPLC followed by ninhydrin reaction "
            "[column: Hitachi gel no. 2619 (cation exchange porous polymer ...)]'; instrument not named"),
    "048": ("Nooner1977", [("TLC", ""), ("radiolabel", "Berthold LB 2760 TLC radioscanner"),
                           ("GC", "Varian 1200"), ("GC-MS", "LKB 9000 or Hewlett-Packard 5930A")],
            RUNS + "; yields of the 14C-labelled products on TLC plates (radioscanner), dipeptides identified by GC "
            "and GC-MS"),
    "049": ("Ying2019", [("LC-MS", "")], "'The produced dipeptides were confirmed and quantified ... by HPLC-MS'; "
            "no instrument named in the paper (supporting information not in the folder)"),
    "050": ("Rabinowitz1978", [("amino-acid-analyzer", RANK)], RUNS),
}
# sets analysed differently from the rest of their paper
SETS = {s: ([("NMR-1H", "")], "Ying2019 Table 1, footnote b: 'The amount of Ala2 was quantified by 1H NMR.'")
        for s in ("049011", "049012")}


def cells(pairs):
    tech = "; ".join(t for t, _ in pairs)
    named = [(t, i) for t, i in pairs if i]
    if len(pairs) == 1:
        inst = pairs[0][1]
    else:
        inst = "; ".join(f"{t}: {i}" for t, i in named)
    return tech, inst


raw = SRC.read_bytes()
rows = list(csv.reader(io.StringIO(raw[3:].decode("utf-8"), newline="")))
header, body = rows[0], rows[1:]
i = header.index("analysis_method")
header[i] = "analysis_technique"
header.insert(i + 1, "analysis_instrument")
groups = {}                                  # (paper or set, before, after, instrument) -> [full_id]
for r in body:
    pid, sid = r[0][:3], r[0][:6]
    name, pairs, why = P[pid]
    if sid in SETS:
        pairs, why = SETS[sid]
    tech, inst = cells(pairs)
    before = r[i]
    r[i] = tech
    r.insert(i + 1, inst)
    groups.setdefault((pid, name, before, tech, inst, why), []).append(r[0])

buf = io.StringIO(newline="")
csv.writer(buf, lineterminator="\r\n").writerows([header] + body)
OUT.write_bytes(b"\xef\xbb\xbf" + buf.getvalue()[:-2].encode("utf-8"))

with open(LOG, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["full_id", "paper", "column", "before", "after", "confidence", "justification"])
    w.writerow(["(header)", "", "analysis_technique", "analysis_method", "analysis_technique", "high",
                "Mickey: renamed; values are the Analysis methods module's technique names (analysis_vocab.json)."])
    w.writerow(["(header)", "", "analysis_instrument", "", "analysis_instrument", "high",
                "Mickey: new column after analysis_technique, the module's 'instrument' setting (make and model as "
                "printed). One technique: the instrument; several: 'technique: instrument' for each one named."])
    for (pid, name, before, tech, inst, why), ids in groups.items():
        ids_txt = ids[0] if len(ids) == 1 else f"{ids[0]}-{ids[-1]} ({len(ids)} rows)"
        w.writerow([ids_txt, name, "analysis_technique", before, tech, "high", why])
        w.writerow([ids_txt, name, "analysis_instrument", "", inst, "high" if inst else "",
                    why if inst else "No instrument named in the paper for these techniques."])
print(f"{len(header)} columns, {len(body)} rows; {len(groups)} paper/set groups")
