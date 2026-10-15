"""Equations the authors label explicitly ("(1)", "Eq. 2"), found by
ingestion/equation_finder.py and optionally converted to LaTeX
(stages/equations.py)."""
from __future__ import annotations
from typing import List

from pydantic import BaseModel, Field


class EquationCandidate(BaseModel):
    label: str                       # as printed, without brackets: "1", "3a", "S2"
    page: int                        # 1-indexed
    bbox: List[float]                # x0, top, x1, bottom in PDF points
    text: str = ""                   # the PDF's text for it (sub/superscripts often lost)
    image: str = ""                  # cropped render
    latex: str = ""                  # filled by the optional conversion
    latex_note: str = ""             # e.g. "unreadable" or a remark from the conversion


# ---- what the model returns for the optional LaTeX conversion ---------------------

class EquationLatex(BaseModel):
    label: str = Field(description="The equation's label exactly as given in the request, e.g. '1'.")
    latex: str = Field(description="The equation in LaTeX (math mode content only, no $ or \\\\[ \\\\]), "
                                   "transcribed from the image exactly -- don't simplify or fix it. Leave "
                                   "out the equation's number label. '' if the image isn't an equation.")
    note: str = Field(default="", description="Anything uncertain, e.g. 'subscript unclear'; '' if none.")


class EquationTranscription(BaseModel):
    equations: List[EquationLatex]
