"""
The 'analysis' step (Mickey, 2026-11-07): every analytical technique a paper used and its instrument settings
(schemas/analysis.py), named from the pack's vocabulary (analysis_vocab.json). One call; table images go along,
since instrument settings are often tabulated (Riggi2023 Table 2). calculators/analysis_columns.py writes the
analysis_<technique>_<setting>[_<unit>] columns.
"""
from pathlib import Path
from typing import List, Optional

from parameter_extractor.analysis_vocab import prompt_listing, vocabulary
from parameter_extractor.api_client import call_structured
from parameter_extractor.run_context import RunContext
from parameter_extractor.schemas.analysis import AnalysisResult
from parameter_extractor.schemas.structure_plan import StructurePlan
from .prompt_loader import load_prompt

LABEL = "Analysis methods"
DESCRIPTION = ("How the products were analysed: every technique (HPLC, MS, NMR, PAGE, ...) and its instrument "
               "settings (column, mobile phase, flow rate, wavelength, matrix, laser, voltages, ...). One API call.")


def output_budget(structure: StructurePlan) -> int:
    """Settings are mostly paper-wide; sets analysed differently repeat a technique."""
    return 6000 + 400 * len(structure.experiment_sets)


def run_analysis(ctx: RunContext, paper_text: str, structure: StructurePlan,
                 table_images: Optional[List[Path]] = None) -> AnalysisResult:
    vocab = vocabulary()
    return call_structured(
        ctx,
        stage="analysis",
        system_prompt="You record how a chemistry paper analysed its products: the analytical techniques and "
                      "their instrument settings. Report only what the paper states.",
        user_content=load_prompt("analysis", STRUCTURE_PLAN_JSON=structure.model_dump_json(indent=2),
                                 ANALYSIS_VOCABULARY=prompt_listing(vocab) if vocab else "",
                                 PAPER_TEXT=paper_text),
        response_model=AnalysisResult,
        paper_text=paper_text,
        image_paths=table_images,
        max_tokens=output_budget(structure),
    )
