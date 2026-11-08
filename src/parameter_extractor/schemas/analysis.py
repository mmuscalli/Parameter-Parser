"""
How the products were analysed (Mickey, 2026-11-07): the analytical techniques a paper used and each one's
instrument settings -- the 'analysis' step (stages/analysis.py). One AnalysisMethod per technique (per set, when
a set was analysed differently), with its settings as name + value + unit as printed; the app matches them to
the pack's vocabulary (analysis_vocab.py) and writes analysis_<technique>_<setting>[_<unit>] columns
(calculators/analysis_columns.py).

Compact like the other extraction steps: short field names (aliases), only the core fields required, the rest
left out when empty; no Optional fields (structured-output grammar size).
"""
from __future__ import annotations
from typing import List

from pydantic import BaseModel, ConfigDict, Field

from parameter_extractor.schemas.common import NOTE_DESC, QUOTE_DESC, SOURCE_DESC, Confidence


def _required(names):
    def extra(schema: dict) -> None:
        schema["required"] = [n for n in names if n in schema.get("properties", {})]
    return extra


class AnalysisSetting(BaseModel):
    model_config = ConfigDict(populate_by_name=True, json_schema_extra=_required(["par", "q", "src", "c"]))
    setting: str = Field(alias="par", description=(
        "The setting's name from the vocabulary for this technique's families (e.g. 'flow-rate', "
        "'laser-intensity', 'matrix'); a setting the vocabulary lacks: a short hyphenated name of your own "
        "('ion-source-1-voltage')."))
    value: float = Field(0.0, alias="v", description="The number, for a setting with a unit (0 with `txt` for text).")
    high: float = Field(0.0, alias="hi", description="Upper end when the paper gives a range ('75-85%': v 75, hi 85); "
                                                     "0 otherwise.")
    unit: str = Field("", alias="u", description="The unit as printed ('mL/min', 'kV', '%', 'nm', 'Å'); '' for text.")
    text: str = Field("", alias="txt", description="The value as printed, for a text setting (column, matrix, "
                                                   "mobile phase, ion polarity).")
    quote: str = Field("", alias="q", description=QUOTE_DESC)
    source: str = Field("", alias="src", description=SOURCE_DESC)
    confidence: Confidence = Field("medium", alias="c")
    note: str = Field("", alias="n", description=NOTE_DESC)


class AnalysisMethod(BaseModel):
    model_config = ConfigDict(populate_by_name=True, json_schema_extra=_required(
        ["tech", "nm", "set", "settings"]))
    technique: str = Field(alias="tech", description=(
        "The technique's name from the vocabulary ('RP-HPLC', 'MALDI-TOF-MS', 'NMR-31P'); one it lacks: the "
        "paper's usual abbreviation, hyphenated ('DOSY-NMR')."))
    name: str = Field(alias="nm", description="The technique as the paper names it ('reversed-phase HPLC').")
    set_label: str = Field(alias="set", description=(
        "'' when this technique and these settings were used for every experiment; else the exact set label "
        "of the structure plan (repeat the technique per set when sets were analysed differently)."))
    sample_label: str = Field("", alias="sample", description="A sample label of that set, only when one sample "
                                                              "was analysed differently; else ''.")
    settings: List[AnalysisSetting] = Field(alias="settings", description=(
        "Every setting the paper states for this technique, one entry each -- including `measured` (what it "
        "measured) and `instrument` when given."))
    # optional: each setting has its own quote (eder1994: the model left these out, and the answer failed)
    quote: str = Field("", alias="q", description="Where the paper describes this technique (optional).")
    source: str = Field("", alias="src", description=SOURCE_DESC)
    confidence: Confidence = Field("high", alias="c")


class AnalysisResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, json_schema_extra=_required(["methods", "notes"]))
    methods: List[AnalysisMethod] = Field(default_factory=list, alias="methods", description=(
        "Every analytical technique used on the experiments' products or solutions, one entry each (per set "
        "when sets differ). [] when the paper describes no analysis."))
    notes: str = Field("", alias="notes", description=NOTE_DESC)
