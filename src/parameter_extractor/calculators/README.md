# Calculators

Deterministic, non-LLM math only. Nothing in this folder ever calls the API --
that's the whole point of separating it from stages/.

**This prototype only implements the two calculators the eder1994 demo
actually needs**: unit conversion (mol/dm3 -> mM) and peptide-yield <-> mM
conversion. It deliberately does NOT reimplement your existing ionic-strength,
pKa-delta, or WORM-balance calculators -- those already exist, are presumably
already correct, and live in `../../Calculators/` (R) in the main project
folder. When this pipeline is ready to compute those fields, wrap the
existing R scripts (e.g. via `subprocess` calling `Rscript`, or a port if you
'd rather keep everything in Python) rather than re-deriving the math here.
