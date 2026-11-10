"""
Wet-dry cycling conditions -- now defined declaratively by the Wet-dry module's step (modules/wet_dry/stages/
wet_dry.json; stages/optional.py builds the models). Kept so existing imports keep working; read from the module itself,
so it doesn't depend on which data pack is active or whether that pack links the module.
"""
from parameter_extractor import modules
from parameter_extractor.stages.optional import StageSpec


def _spec() -> StageSpec:
    path = next(f for f in modules.available()["wet_dry"].stage_files() if f.stem == "wet_dry")
    return StageSpec.model_validate_json(path.read_text())


CycleParameter, WetDryConditions = _spec().models()
