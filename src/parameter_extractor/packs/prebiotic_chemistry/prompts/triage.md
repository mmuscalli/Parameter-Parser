You are screening a published paper for inclusion in a curated literature
database of prebiotic peptide-synthesis experiments. The database is built on
the POLO ontology, which currently only models aqueous-solution systems.

Apply these inclusion criteria exactly as a human curator would:

- The system must be aqueous solution (not wet-dry cycling, not solid-state/
  mineral-surface-only, not melt/solvent-free).
- Only one type of amino acid may be polymerized per experiment (mixed/
  heteropolymer-only systems are excluded; a paper that ALSO reports
  single-amino-acid experiments alongside mixed ones can still be included
  for the single-amino-acid portion -- note that in `excluded_experiment_note`).
- A quantifiable result for peptide yield must be reported (not just "peptides
  were detected").
- Conditions should be plausible for early Earth, not industrial/pharmaceutical
  synthesis relying on condensation agents or protecting groups that push
  yields well above what unaided prebiotic chemistry could achieve (often >90%).
- If any experiments in the paper use `set_type` "Evaporation Cycle" (wet-dry
  evaporation cycling), note that those specific experiments should be
  excluded even if the rest of the paper is included -- POLO cannot currently
  describe them.

Read the paper text below and return a TriageResult. Be specific in
`reasoning` -- cite what in the paper supports each boolean judgment.

---
PAPER TEXT:

{{PAPER_TEXT}}
