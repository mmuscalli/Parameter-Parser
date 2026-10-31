"""
Supplementary information (SI) that comes with a paper (Mickey, 2026-10-31: pulletikurti2022.pdf +
pulletikurti2022_SI.pdf). A PDF next to the paper whose name is the paper's plus an SI marker --
'<paper>_SI.pdf', '<paper> SI.pdf', '<paper>-ESI.pdf', '<paper>_supplementary.pdf',
'<paper>_supporting information.pdf', '<paper>_SI2.pdf' -- is read WITH the paper: its text is
appended after the paper's (marked), its table pages are rendered too, quotes found in it get pages
'S1', 'S2', ..., and everything is reported under the original paper. In a list of papers an SI file
is folded into its paper instead of being run on its own.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import List, Optional

_MARKER = r"(?:si|esi|supp(?:l(?:ement(?:ary|al)?)?)?|supporting(?:[\s_\-]*info(?:rmation)?)?)(?:[\s_\-]*\d+)?"
_SEP = r"[\s_\-.]+"


def is_supplement_name(stem: str, main_stem: str) -> bool:
    return bool(re.fullmatch(rf"{re.escape(main_stem)}{_SEP}{_MARKER}", stem, re.IGNORECASE))


def find_supplements(pdf: Path) -> List[Path]:
    """The SI PDFs next to `pdf`, in name order."""
    pdf = Path(pdf)
    if not pdf.parent.is_dir():
        return []
    return sorted(p for p in pdf.parent.iterdir()
                  if p.suffix.lower() == ".pdf" and p != pdf and is_supplement_name(p.stem, pdf.stem))


def main_paper_for(pdf: Path) -> Optional[Path]:
    """The paper an SI PDF belongs to, if it's next to it ('x_SI.pdf' -> 'x.pdf'), else None."""
    pdf = Path(pdf)
    m = re.fullmatch(rf"(.+?){_SEP}{_MARKER}", pdf.stem, re.IGNORECASE)
    if not m:
        return None
    main = pdf.with_name(m.group(1) + pdf.suffix)
    return main if main.is_file() and is_supplement_name(pdf.stem, main.stem) else None


def drop_supplements(items: list) -> tuple:
    """(items without SI PDFs whose paper is in the list or next to them, the SI files folded away)."""
    paths = {Path(i).resolve() for i in items if isinstance(i, (str, Path)) and str(i).lower().endswith(".pdf")}
    kept, folded = [], []
    for item in items:
        if isinstance(item, (str, Path)) and str(item).lower().endswith(".pdf"):
            main = main_paper_for(Path(item))
            if main is not None and (main.resolve() in paths or main.is_file()):
                folded.append(item)
                continue
        kept.append(item)
    return kept, folded
