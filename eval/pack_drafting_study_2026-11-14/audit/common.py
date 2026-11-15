"""Shared loading for the PaperDataTemplate audit: the hand rows, the study runs and the papers' text."""
import csv, json, re
from pathlib import Path
import pandas as pd
ROOT = Path("/Users/mickeymuscalli/Documents/EORE Data Project")
SRC = ROOT / "PaperDataTemplate Archive/PaperDataTemplate_Nov14_2026.csv"
STUDY = Path.home() / "Documents/Parameter Extractor/pack_study_20261114"
hand = pd.read_csv(SRC, encoding="utf-8-sig", dtype=str, keep_default_na=False)
hand["paper"] = hand.full_id.str[:3]
hand_map = json.load(open(ROOT / "extraction_pipeline/eval/pack_drafting_study_2026-11-14/hand_map.json"))
items = {Path(l).parent.name: Path(l) for l in (STUDY / "papers_all.txt").read_text().splitlines()}

def run_folder(pack, name):
    """The paper's run folder in a pack's (last) queue -- the scanned papers' reruns for those three."""
    stem = items[name].stem
    roots = [STUDY / f"scanned_{pack}", STUDY / f"runs_{pack}"]
    for r in roots:
        for q in sorted(r.glob("queue_*"), reverse=True):
            for d in q.iterdir():
                if d.is_dir() and d.name.rsplit("_", 1)[0] == stem and (d / "run_summary.json").is_file():
                    return d
    return None

def run_rows(pack, name):
    d = run_folder(pack, name)
    if d is None: return pd.DataFrame()
    f = next(d.glob("*_extracted.csv"), None)
    return pd.read_csv(f, dtype=str, keep_default_na=False) if f else pd.DataFrame()

_TEXT = {}
def paper_text(name):
    if name not in _TEXT:
        import sys; sys.path.insert(0, str(ROOT / "extraction_pipeline/src"))
        from parameter_extractor.ingestion.pdf_parser import parse_pdf
        _TEXT[name] = parse_pdf(str(items[name])).text
    return _TEXT[name]
