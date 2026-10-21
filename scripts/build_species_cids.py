"""
Builds src/parameter_extractor/packs/prebiotic_chemistry/species_cids.json: PubChem CIDs for the
template's species names, so a paper's name for one of them ("2'-cytidylic
acid", "calcium dichloride") can be matched by identity (pubchem.py).

Each template name is looked up under the forms PubChem knows (full amino-acid
names, oligopeptide names, ion names, underscores as spaces). Results were
checked by hand (2026-10-15); names in SKIP are pseudo-species or mixtures
with no single compound, and OVERRIDES pins forms whose first PubChem hit is
the wrong compound. Re-run only when the template's species change, and check
the printed titles again.

Run with: python scripts/build_species_cids.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parameter_extractor.names import AMINO_ACIDS, vocabulary
from parameter_extractor import packs
from parameter_extractor.pubchem import PubChem

SPECIES_CIDS = packs.activate("prebiotic_chemistry").species_cids_path

SKIP = {"H+_constituents", "Na+_WORMadd", "total_monomers", "poly(A)", "poly(C)", "poly(G)", "poly(U)",
        "polyvinylpyrrolidone", "sodium_polyphosphate", "sodium_polyphosphate_n26", "ammonium_polyphosphate",
        "sodium_borate", "N(CH3)4_trimetaphosphate",
        "C4H5O4-"}          # formula only: hydrogen succinate? maleate? -- ambiguous
OVERRIDES = {      # template name -> query that gives the right compound (first hit was wrong or missing)
    "CO": "carbon monoxide",            # 'CO' -> cobalt
    "CO3-2": "carbonate",               # 'CO3-2' -> bicarbonate
    "NiS": "nickel sulfide",            # 'NiS' -> N-iodosuccinimide
    "3peptide_Phe": "Phe-Phe-Phe",      # 'triphenylalanine' -> an unrelated compound
    "CH3COO-": "acetate", "PO4-3": "phosphate", "P2O7-4": "pyrophosphate", "citrate-3": "citrate",
    "124_triazole": "1,2,4-triazole", "EDC": "1-ethyl-3-(3-dimethylaminopropyl)carbodiimide",
    "K3[Fe(CN)6]": "potassium ferricyanide", "FeS": "iron(II) sulfide", "CH3NH3+": "methylammonium",
    "sodium_triMP": "sodium trimetaphosphate", "sodium_tripolyphosphate": "sodium tripolyphosphate",
    "Ca(H2PO4)2.H2O": "monocalcium phosphate monohydrate",
}
_NUM = {2: "di", 3: "tri", 4: "tetra", 5: "penta", 6: "hexa", 7: "hepta", 8: "octa", 9: "nona", 10: "deca",
        11: "undeca", 12: "dodeca", 13: "trideca"}
_ION = {"Na": "sodium", "K": "potassium", "Cs": "cesium", "Ca": "calcium", "Mg": "magnesium", "Ba": "barium",
        "Cu": "copper", "Fe": "iron", "Ni": "nickel", "Cd": "cadmium", "Pb": "lead", "Zn": "zinc"}


def queries(name):
    if name in OVERRIDES:
        return [OVERRIDES[name]]
    out = []
    if name in AMINO_ACIDS:
        out.append(AMINO_ACIDS[name])
    m = re.fullmatch(r"(\d+)peptide_([A-Z][a-z]{2})", name)
    if m:
        n, aa = int(m.group(1)), m.group(2)
        full = AMINO_ACIDS[aa]
        out += [f"{_NUM[n]}{full}", "-".join([aa] * n)]
        if n == 2:
            out.append(f"{full.removesuffix('ine').removesuffix('ic acid')}yl{full}")
    m = re.fullmatch(r"([A-Z][a-z]?)\+(\d?)", name)
    if m and m.group(1) in _ION:
        out += [f"{_ION[m.group(1)]}({m.group(2) or 1}+)", f"{_ION[m.group(1)]} ion"]
    m = re.fullmatch(r"DKP_([A-Z][a-z]{2})", name)
    if m:
        out.append(f"cyclo({m.group(1)}-{m.group(1)})")
    out.append(name.replace("_", " "))
    return out


def main():
    pc = PubChem(ROOT / "scripts" / ".pubchem_build_cache.json")
    result, missing = {}, []
    for name in vocabulary():
        if name in SKIP:
            continue
        for q in queries(name):
            c = pc.lookup(q)
            if c:
                result[name] = {"cid": c.cid, "title": c.title, "formula": c.formula, "query": q}
                print(f"{name:32} {q:28} -> {c.cid:>9} {c.title} [{c.formula}]")
                break
        else:
            missing.append(name)
    pc.save()
    print("\nnot found:", ", ".join(missing))
    if "--write" in sys.argv:
        SPECIES_CIDS.write_text(json.dumps({"built_by": "scripts/build_species_cids.py", "species": result},
                                           indent=1, ensure_ascii=False))
        print(f"wrote {len(result)} -> {SPECIES_CIDS}")


if __name__ == "__main__":
    main()
