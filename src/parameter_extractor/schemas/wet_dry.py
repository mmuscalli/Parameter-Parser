"""
Wet-dry cycling conditions -- now defined declaratively in packs/prebiotic_chemistry/stages/wet_dry.json
(stages/optional.py builds the models). Kept so existing imports keep working.
"""
from parameter_extractor.stages.optional import load_specs

CycleParameter, WetDryConditions = load_specs()["wet_dry"].models()
