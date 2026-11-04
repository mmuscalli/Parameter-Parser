"""
Adds PubChem synonyms to packs/prebiotic_chemistry/species_cids.json (Mickey, 2026-11-03): for each template species
with a confirmed CID, its useful names (pubchem.useful_synonyms: no registry numbers or database codes), so a
compound can be shown under another name in the output (the Remembered variables window's Compounds tab) and a
paper's name for it matched offline. Network: one PUG REST request per CID (~30 s).

Run with: python scripts/add_species_synonyms.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parameter_extractor import packs
from parameter_extractor.pubchem import PubChem

path = packs.activate("prebiotic_chemistry").species_cids_path
data = json.loads(path.read_text())
pc = PubChem(None)
for name, entry in data["species"].items():
    names = pc.synonyms(entry["cid"])
    if pc.unavailable_reason:
        sys.exit(pc.unavailable_reason)
    entry["synonyms"] = names
    print(f"{name:28s} {entry['cid']:>10}  {', '.join(names[:5])}")
path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
print("written", path)
