"""
Optional stage: transcribe the labelled equations found by
ingestion/equation_finder.py into LaTeX, from their cropped images, in ONE
call for the whole paper. Off unless the user turns it on (RunConfig.
equations_to_latex); finding and cropping the equations costs nothing.

Chosen over local formula-OCR packages after testing on the 13 labelled
equations in the test papers (2026-10-15): pix2tex got about half wrong (O
read as G, delta as 4) and pix2text was accurate except for the per-mille
sign, but both need PyTorch (1-2 GB) -- too heavy for the desktop app. A
batched call is a few thousand tokens per paper.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import List

from parameter_extractor.api_client import call_structured
from parameter_extractor.run_context import RunContext
from parameter_extractor.schemas.equations import EquationCandidate, EquationTranscription
from .prompt_loader import load_prompt


_SPACING = r"(?:\\q?quad|\\hfill|\\[,;! ]|~|\s)"


def clean_latex(latex: str) -> str:
    """Tidy a transcription: no surrounding $ or \\[ \\], no trailing equation number
    (only one set apart by spacing -- 'f(2)' at the end is kept)."""
    t = latex.strip()
    t = re.sub(r"^\$+|\$+$", "", t)
    t = re.sub(r"^\\\[|\\\]$", "", t).strip()
    t = re.sub(r"\\(?:tag\*?|eqno)\s*\{?\(?\s*[A-Z]?\d{1,3}[a-z]?\s*\)?\}?\s*$", "", t)
    t = re.sub(_SPACING + r"+\(\s*[A-Z]?\d{1,3}[a-z]?\s*\)\s*$", "", t)
    t = re.sub(_SPACING + r"+$", "", t)
    return t.strip()


def transcribe_equations(ctx: RunContext, equations: List[EquationCandidate]) -> List[EquationCandidate]:
    if not equations:
        return equations
    listing = "\n".join(f"- Image {i}: equation ({e.label}), page {e.page}" for i, e in enumerate(equations, 1))
    result = call_structured(
        ctx,
        stage="equations",
        system_prompt="You transcribe equations from images of scientific papers into LaTeX, exactly as "
                      "printed.",
        user_content=load_prompt("equations", EQUATION_LIST=listing),
        response_model=EquationTranscription,
        image_paths=[Path(e.image) for e in equations],
    )
    by_label = {}
    for item in result.equations:
        by_label.setdefault(item.label.strip("() "), item)
    for e in equations:
        item = by_label.get(e.label)
        if item is not None:
            e.latex = clean_latex(item.latex)
            e.latex_note = item.note
    return equations
