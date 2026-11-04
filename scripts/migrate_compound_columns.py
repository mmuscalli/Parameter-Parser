"""
One format for every compound column (Mickey, 2026-11-04): '<role>_<name>_<phase>_<measure>', peptides named by
their sequence ('Gly-Gly', '(Gly)4', 'cyclo_Gly-Gly') instead of '<n>peptide_<AA>' / 'DKP_<AA>'.

Rewrites the prebiotic pack's template_vocab.json (columns via flatten_to_template.current_column_name, species
names via names.match_species) and species_cids.json (keys). Idempotent: running it again changes nothing.
PaperDataTemplate.xlsx itself is never touched.

Run with: python scripts/migrate_compound_columns.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parameter_extractor import packs
from parameter_extractor.ingestion.flatten_to_template import current_column_name
from parameter_extractor.names import _oligomer, cyclic_codes, cyclic_name

pack = packs.activate("prebiotic_chemistry")


def new_species_name(name: str) -> str:
    m = re.fullmatch(r"(\d+)peptide_([A-Z][a-z]{2})", name)
    if m:
        return _oligomer(int(m.group(1)), m.group(2))
    if re.fullmatch(r"DKP_[A-Z][a-z]{2}", name):
        return cyclic_name(cyclic_codes(name))
    return name


vocab_path = pack.folder / "template_vocab.json"
vocab = json.loads(vocab_path.read_text())
renamed = {c: current_column_name(c) for c in vocab["all_columns"] if current_column_name(c) != c}
vocab["all_columns"] = [current_column_name(c) for c in vocab["all_columns"]]
vocab["species_names"] = sorted({new_species_name(n) for n in vocab["species_names"]})
vocab_path.write_text(json.dumps(vocab, indent=2, ensure_ascii=False) + "\n")
print(f"{len(renamed)} columns renamed in {vocab_path.name}")

cids_path = pack.species_cids_path
cids = json.loads(cids_path.read_text())
cids["species"] = {new_species_name(n): v for n, v in cids["species"].items()}
cids_path.write_text(json.dumps(cids, indent=1, ensure_ascii=False) + "\n")
print(f"species keys updated in {cids_path.name}")
for old, new in list(renamed.items())[:12]:
    print(f"  {old} -> {new}")
