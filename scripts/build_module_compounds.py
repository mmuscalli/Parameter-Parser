"""The compound vocabularies two app modules carry (2026-11-22, Mickey: bundle the built-in pack's vocabulary into the
shared modules): the prebiotic pack's species split by subject -- amino acids, peptides, nucleotides and condensing
agents to peptides_oligomers; salts, ions, phosphates, buffers and gases to solution_chemistry -- each with its dataset
columns and its PubChem identities. A pack linking the module gets the species it lacks (packs.Pack.species_names);
the prebiotic pack has all of them, so nothing changes for it.

Usage: python scripts/build_module_compounds.py   (rewrites modules/<id>/compounds.json and species_cids.json)
"""
import json
import re
from pathlib import Path

PE = Path(__file__).resolve().parents[1] / "src" / "parameter_extractor"
PREBIOTIC = PE / "packs" / "prebiotic_chemistry"

AMINO = {"Ala", "Asp", "Cys", "Gly", "His", "Met", "Phe", "Ser", "Trp", "Val", "Glu", "Leu", "Ile", "Thr", "Lys", "Arg",
         "Pro", "Tyr", "Asn", "Gln"}
OLIGOMER_OTHERS = {"AMP", "ATP", "UMP", "poly(A)", "poly(C)", "poly(G)", "poly(U)", "glycinamide", "total_monomers",
                   "EDC", "cyanamide", "imidazole", "urea", "diaminomaleonitrile", "AICA", "124_triazole"}


def is_oligomer_species(name: str) -> bool:
    parts = set(re.findall(r"[A-Z][a-z]{2}", name))
    return name in OLIGOMER_OTHERS or (bool(parts) and parts <= AMINO and not re.search(r"Cl|PO|SO", name))


def columns_for(species: str, columns) -> list:
    return [c for c in columns if any(c.startswith(f"{role}_{species}_") for role in
                                      ("initial", "sampled", "stock", "calculated"))]


def main() -> None:
    vocab = json.loads((PREBIOTIC / "template_vocab.json").read_text())
    cids = json.loads((PREBIOTIC / "species_cids.json").read_text())
    split = {"peptides_oligomers": [], "solution_chemistry": []}
    for s in vocab["species_names"]:
        split["peptides_oligomers" if is_oligomer_species(s) else "solution_chemistry"].append(s)
    for module, species in split.items():
        folder = PE / "modules" / module
        out = {"_about": "Compounds this module brings to a pack that links it, with their dataset columns (built by "
                         "scripts/build_module_compounds.py from the prebiotic pack's vocabulary).",
               "species_names": species,
               "all_columns": [c for s in species for c in columns_for(s, vocab["all_columns"])]}
        (folder / "compounds.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        mine = {n: v for n, v in cids.get("species", {}).items() if n in set(species)}
        (folder / "species_cids.json").write_text(json.dumps({"species": mine}, indent=2, ensure_ascii=False) + "\n")
        print(f"{module}: {len(species)} species, {len(out['all_columns'])} columns, {len(mine)} identities")


if __name__ == "__main__":
    main()
