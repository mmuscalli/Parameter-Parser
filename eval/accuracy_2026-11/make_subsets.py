"""Accuracy evaluation, November 2026 (Mickey, 2026-11-20): the prebiotic test batches as copies of the papers.

Each paper goes to `Paper Files/Accuracy Test 2026-11/<batch>/<key>/<key>.pdf`, its supplement (if any) next to it as
`<key>_SI.pdf` so the app reads it with the paper. Writes `<batch>/papers.txt` (the queue list) and, here,
`batches.json` (batch -> key -> {pdf, source, hand_id}). The originals are never touched.

Usage: python make_subsets.py   (E1, the exoplanet papers, is made by make_exoplanet_subset.py)
"""
import json
import shutil
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]                                    # EORE Data Project
PAPERS = ROOT / "Paper Files"
OUT = PAPERS / "Accuracy Test 2026-11"
STUDY = Path.home() / "Documents/Parameter Extractor/pack_study_20261114"
HAND_MAP = json.loads((HERE.parent / "pack_drafting_study_2026-11-14/hand_map.json").read_text())

def one(folder: Path, start: str) -> Path:
    def plain(t):                                         # NFC, and any space (no-break ones too) as a space
        return " ".join(unicodedata.normalize("NFC", t).split())
    hits = [p for p in folder.glob("*.pdf") if plain(p.name).startswith(start)]
    assert len(hits) == 1, (folder, start, hits)
    return hits[0]


# the four papers added to the hand dataset on 2026-11-14 (ids from PaperDataTemplate_Nov15_2026.csv)
ADDED = {"Gregoire2018": "006", "Rodriguez-Garcia2015": "007", "Imai1999": "008", "Cleaves2009": "009"}
IEP = PAPERS / "Paper Lists/Initial Easy Papers"
ADDED_FILES = {
    "Gregoire2018": (one(IEP, "Grégoire et al. - 2018"), None),
    "Imai1999": (IEP / "Imai et al. - 1999 - Elongation of Oligopeptides in a Simulated Submarine Hydrothermal System.pdf",
                 None),
    "Cleaves2009": (IEP / "Rodriguez-Garcia2015/Cleaves et al. - 2009 - An Evaluation of the Critical Parameters for "
                          "Abiotic Peptide Synthesis in Submarine Hydrothermal Sys.pdf", None),
    "Rodriguez-Garcia2015": (IEP / "Rodriguez-Garcia2015/Rodriguez-Garcia et al. - 2015 - Formation of oligopeptides in "
                                   "high yield under simple programmable conditions.pdf",
                             IEP / "Rodriguez-Garcia2015/Rodriguez-Garcia2015_Supplemental.pdf"),
}

SAM, MALDI, TPL, PL = (PAPERS / "Test Paper List/Sam Papers", PAPERS / "Test Paper List/Oligonucleotides_MALDI_papers",
                       PAPERS / "Test Paper List", PAPERS / "Paper Lists")
ORG = PAPERS / "Test Paper List/Organics in target/files"


P2 = {  # prebiotic papers without hand data: nucleotides, wet-dry and heat-flow setups, minerals, peptides
    "Caimi2024": (one(SAM, "Caimi"), None),
    "CalacaSerrao2024": (one(SAM, "Calaça"), None),
    "FerrisErtem1993": (one(SAM, "Ferris and Ertem"), None),
    "Matreux2024": (one(SAM, "Matreux"), None),
    "Song2024": (one(SAM, "Song"), None),
    "Hirakawa2025": (one(SAM, "Hirakawa"), None),
    "Burcar2013": (one(MALDI, "Burcar"), None),
    "Coari2017": (one(MALDI, "Coari"), None),
    "Costanzo2012": (one(MALDI, "Costanzo"), None),
    "Riggi2023": (TPL / "Riggi2023.pdf", None),
    "Mizuuchi2019": (TPL / "mizuuchi2019.pdf", None),
    "Pulletikurti2022": (TPL / "pulletikurti2022.pdf", TPL / "pulletikurti2022_SI.pdf"),
    "Tapiero1971": (TPL / "tapiero1971.pdf", None),
    "Cleaves2008": (PL / "cleaves2008.pdf", None),
    "FrenkelPinter2020": (PL / "frenkel-pinter2020.pdf", None),
    "Otake2011": (PL / "otake2011.pdf", None),
}
P3 = {  # organics in impacts, shocks and radiation: outside the prebiotic pack's focus
    "Takeuchi2020": (one(ORG / "1001", "Takeuchi"), None),
    "Muchowska2019": (ORG / "1037/s41586-019-1151-1.pdf", None),
    "McKay1997": (one(ORG / "1129", "McKay"), None),
    "Tingle1991": (ORG / "1103/tingle1991.pdf", None),
    "Kazemi2021": (ORG / "1126/kazemi2021.pdf", None),
    "DeLuca2022": (one(ORG / "937", "JGR Planets"), None),
    "daCosta2022": (one(ORG / "1093", "da Costa"), None),
    "Mukhin1989": (ORG / "1113/mukhin1989.pdf", None),
    "Parnell2007": (one(ORG / "1131", "Parnell"), None),
    "Burchell2020": (one(ORG / "1130", "Burchell"), None),
}


def p1() -> dict:
    out = {}
    for line in (STUDY / "papers_all.txt").read_text().splitlines():
        pdf = Path(line.strip())
        if not line.strip():
            continue
        key = pdf.parent.name
        sis = [p for p in pdf.parent.glob("*.pdf") if p != pdf and "supplement" in p.name.lower()]
        out[key] = (pdf, sis[0] if sis else None, HAND_MAP.get(key))
    for key, (pdf, si) in ADDED_FILES.items():
        out[key] = (pdf, si, ADDED[key])
    return out


def copy_batch(name: str, papers: dict) -> dict:
    manifest = {}
    for key, entry in sorted(papers.items()):
        pdf, si = entry[0], entry[1]
        hand_id = entry[2] if len(entry) > 2 else None
        assert pdf.is_file(), pdf
        dest = OUT / name / key
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / f"{key}.pdf"
        if not target.exists():
            shutil.copy2(pdf, target)
        if si is not None:
            assert si.is_file(), si
            if not (dest / f"{key}_SI.pdf").exists():
                shutil.copy2(si, dest / f"{key}_SI.pdf")
        manifest[key] = {"pdf": str(target), "source": str(pdf), "si": str(si) if si else "", "hand_id": hand_id}
    (OUT / name / "papers.txt").write_text("".join(f"{m['pdf']}\n" for m in manifest.values()))
    return manifest


if __name__ == "__main__":
    f = HERE / "batches.json"
    batches = json.loads(f.read_text()) if f.is_file() else {}
    for name, papers in (("P1", p1()), ("P2", P2), ("P3", P3)):
        batches[name] = copy_batch(name, papers)
        hand = sum(1 for m in batches[name].values() if m["hand_id"])
        print(f"{name}: {len(batches[name])} papers ({hand} in the hand dataset) -> {OUT / name}")
    f.write_text(json.dumps(batches, indent=1, ensure_ascii=False))
