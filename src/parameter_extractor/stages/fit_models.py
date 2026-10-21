"""
Exoplanet pack stage `fit_models`: how the paper obtained its values -- models,
data (facility, instrument, bands), joint fits, software, priors, assumptions
(schemas/fit_models.py). One call; table pages go along as images, since priors
are often tabulated. calculators/exoplanet_fits.py writes the columns.
"""
from pathlib import Path
from typing import List, Optional

from parameter_extractor.api_client import call_structured
from parameter_extractor.run_context import RunContext
from parameter_extractor.schemas.fit_models import FitModels
from parameter_extractor.schemas.structure_plan import StructurePlan
from .prompt_loader import load_prompt

LABEL = "Fitting models"
DESCRIPTION = ("How the values were obtained: the models fit, the data in each (facility, instrument, "
               "filters), joint fits, software (EXOFAST version), priors and key assumptions. One API call.")


def run_fit_models(ctx: RunContext, paper_text: str, structure: StructurePlan,
                   table_images: Optional[List[Path]] = None) -> FitModels:
    return call_structured(
        ctx,
        stage="fit_models",
        system_prompt="You record how an astronomy paper derived its reported parameters: models, data, "
                      "priors and assumptions. Report only what the paper states.",
        user_content=load_prompt("fit_models", STRUCTURE_PLAN_JSON=structure.model_dump_json(indent=2),
                                 PAPER_TEXT=paper_text),
        response_model=FitModels,
        image_paths=table_images,
    )
