"""
Optional per-figure stage, run only when the user chooses to digitize a
figure: suggests what each axis means (as template columns), which series
are plotted and their experimental conditions. The user edits these freely;
nothing here is written to the dataset without their clicks.

Context is kept small: the figure image, its caption, the experiment
structure, and only the passages of text that mention this figure -- not the
whole paper (that was ~10K of the ~28K input tokens per figure).
"""
import json
import re
from pathlib import Path
from typing import List

from parameter_extractor.api_client import call_structured
from parameter_extractor.run_context import RunContext
from parameter_extractor.schemas.figures import FigureCandidate, FigurePlan
from parameter_extractor.schemas.structure_plan import StructurePlan
from .prompt_loader import load_prompt

PASSAGE_WINDOW = 4        # lines of context either side of a mention
MAX_PASSAGE_CHARS = 8000


def figure_passages(page_texts: List[str], number: int) -> str:
    """Lines around every mention of Fig./Figure <number> (including lists like
    'Figs. 1 and 2'), matched with whitespace removed so OCR letter-spacing
    doesn't hide them."""
    mention = re.compile(rf"fig(?:ure)?s?\.?(?:\d+(?:,|and|&|-|–))*{number}(?![\d])", re.IGNORECASE)
    chunks = []
    for page_no, text in enumerate(page_texts, start=1):
        lines = text.splitlines()
        hits = [i for i, ln in enumerate(lines) if mention.search(re.sub(r"\s+", "", ln))]
        spans = []
        for i in hits:
            lo, hi = max(0, i - PASSAGE_WINDOW), min(len(lines), i + PASSAGE_WINDOW + 1)
            if spans and lo <= spans[-1][1]:
                spans[-1] = (spans[-1][0], hi)
            else:
                spans.append((lo, hi))
        for lo, hi in spans:
            chunks.append(f"[page {page_no}]\n" + "\n".join(l.rstrip() for l in lines[lo:hi]))
    text = "\n...\n".join(chunks)
    return text[:MAX_PASSAGE_CHARS] if text else "(the text doesn't mention this figure)"


MAX_COMPOSITION_CHARS = 5000
_CONCENTRATION = re.compile(r"\d\s*(?:mol\s*(?:dm|L|l)|[mµμu]?M\b|mmol|µmol|mg\s*(?:/|per)?\s*m?L|g\s*(?:/|per)\s*L"
                            r"|%\s*\(?(?:w|v|wt))", re.IGNORECASE)


def composition_passages(page_texts: List[str], exclude: str = "") -> str:
    """Lines stating a concentration anywhere in the paper (usually Methods), with two
    lines before and after for context -- starting compositions are rarely next to the
    figure that plots them (alargov2002: glycine 0.065 M / 0.22 M in Methods only, and
    which injection system each was for two lines earlier).
    Lines already in the figure passages and the reference list are left out."""
    chunks, seen = [], set(exclude.splitlines())
    for page_no, text in enumerate(page_texts, start=1):
        if re.search(r"^\s*(References|REFERENCES|Bibliography)\s*$", text, re.MULTILINE):
            text = re.split(r"^\s*(?:References|REFERENCES|Bibliography)\s*$", text, flags=re.MULTILINE)[0]
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if _CONCENTRATION.search(ln) and ln.rstrip() not in seen:
                block = [l.rstrip() for l in lines[max(0, i - 2):i + 3] if l.rstrip() not in seen]
                seen.update(block)
                if block:
                    chunks.append(f"[page {page_no}] " + "\n".join(block))
    text = "\n...\n".join(chunks)
    return text[:MAX_COMPOSITION_CHARS] if text else "(no concentrations stated in the text)"


def run_figure_planner(
    ctx: RunContext, figure: FigureCandidate, page_texts: List[str], structure_plan: StructurePlan,
    controlled_vocab: List[str], template_columns: List[str],
) -> FigurePlan:
    prompt = load_prompt(
        "figure_planner",
        FIGURE_ID=figure.figure_id,
        PAGE=str(figure.page),
        CAPTION=figure.caption,
        STRUCTURE_PLAN_JSON=structure_plan.model_dump_json(indent=2),
        CONTROLLED_VOCAB_JSON=json.dumps(controlled_vocab),
        TEMPLATE_COLUMNS_JSON=json.dumps(template_columns),
        FIGURE_PASSAGES=(passages := figure_passages(page_texts, figure.number)),
        COMPOSITION_PASSAGES=composition_passages(page_texts, exclude=passages),
    )
    return call_structured(
        ctx,
        stage="figure_planner",
        audit_name=f"figure_planner.fig{figure.number}",
        system_prompt="You help a scientist digitize plots from a paper. Describe only what "
                      "the figure and text support; never invent series or conditions.",
        user_content=prompt,
        response_model=FigurePlan,
        image_paths=[Path(figure.crop_image)],
    )
