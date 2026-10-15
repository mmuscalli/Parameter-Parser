"""
Figures: detected plot images, the model's suggested reading of a plot
(FigurePlan), and what the user digitized by hand (DigitizedFigure).

Flow: ingestion/figure_finder.py finds FigureCandidates while the PDF is
parsed -> the user chooses Skip or Digitize per figure -> for Digitize, the
figure_planner stage returns a FigurePlan (axis meanings, series, conditions)
as editable suggestions -> the user calibrates axes and clicks points ->
DigitizedFigure -> ingestion/figure_rows.py turns each series into a set of
rows. Skipped figures never reach the dataset.

Coordinates: pixel positions (px, py) are in the rendered page image, whose
resolution is FigureCandidate.render_scale pixels per PDF point.
"""
from __future__ import annotations
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

BBox = Tuple[float, float, float, float]   # x0, top, x1, bottom in PDF points


class FigureCandidate(BaseModel):
    figure_id: str                 # "Fig. 3"
    number: int
    page: int                      # 1-based
    caption: str                   # best-effort text; OCR can garble it (the image is authoritative)
    figure_bbox: BBox              # estimated plot area, above the caption
    caption_bbox: BBox
    page_image: str                # path to the rendered page (PNG)
    crop_image: str                # path to figure + caption crop, as shown to the model
    render_scale: float            # page image pixels per PDF point


# ---- the model's suggestions (structured output of the figure_planner stage) ----

class SpeciesAmount(BaseModel):
    name: str = Field(description="Species name from the controlled vocabulary, e.g. 'NaCl', 'Gly'.")
    concentration_mM: Optional[float] = Field(description="Initial concentration in mM (mol dm-3 x 1000).")


class AxisVariable(BaseModel):
    label: str = Field(description="Axis title exactly as printed, e.g. 't/h' or '% Gly-Gly'.")
    column: Optional[str] = Field(
        description="The template column this axis's values belong in (e.g. 'duration_hr', "
                    "'sampled_2peptide_Gly_%yield'), chosen from the provided column list; null "
                    "if no column fits (e.g. a derived rate or a hydration enthalpy).")
    multiplier: float = Field(
        default=1.0,
        description="Factor that converts a value read off the axis into the column's unit, e.g. "
                    "1000 for an axis in mol dm-3 going into an _mM column, 0.001 for an axis "
                    "labelled '10^3 x (% yield)'.")
    scale: Literal["linear", "log"] = "linear"
    note: Optional[str] = None


class PlannedSeries(BaseModel):
    label: str = Field(description="How the series is identified, e.g. 'pH 1.93' or 'Na+'.")
    marker: Optional[str] = Field(default=None, description="Marker/line style, e.g. 'open diamond', 'dashed line'.")
    set_label: Optional[str] = Field(
        default=None, description="Exact structure-plan set_label if this series is the same "
                                  "experiment as a tabulated set, else null.")
    initial_species: List[SpeciesAmount] = Field(
        default_factory=list, description="COMPLETE initial composition of this series, including "
                                          "components common to all series.")
    initial_temperature_C: Optional[float] = None
    initial_pH: Optional[float] = None
    notes: Optional[str] = None


class PlannedPanel(BaseModel):
    name: str = Field(description="'main', or e.g. '(a)', '(b)', 'right y-axis' when a figure "
                                  "has several panels or a second axis.")
    x: AxisVariable
    y: AxisVariable
    series: List[PlannedSeries] = Field(default_factory=list)


class FigurePlan(BaseModel):
    figure_id: str
    is_data_plot: bool = Field(description="True if the figure plots numeric data on calibrated axes.")
    plot_kind: Literal["scatter", "line", "scatter_with_fit", "bar", "other"]
    panels: List[PlannedPanel] = Field(default_factory=list)
    duplicates_tabulated_data: bool = Field(
        description="True if the plotted points appear to be the same values already given in a table.")
    data_source: str = Field(
        default="", description="'' if the plotted data was measured in this paper; otherwise the original "
                                "reference (e.g. a figure 'redrawn from ref. 12' -> that reference as the "
                                "reference list gives it).")
    duplicate_note: Optional[str] = None
    notes: Optional[str] = None


# ---- what the user digitized -------------------------------------------------

class CalibrationPoint(BaseModel):
    px: float
    py: float
    value: Optional[float] = None


class AxisCalibration(BaseModel):
    p1: Optional[CalibrationPoint] = None
    p2: Optional[CalibrationPoint] = None
    log: bool = False

    def complete(self) -> bool:
        return (self.p1 is not None and self.p2 is not None and self.p1.value is not None
                and self.p2.value is not None and self.p1.value != self.p2.value
                and (not self.log or (self.p1.value > 0 and self.p2.value > 0)))


class DigitizedPanel(BaseModel):
    name: str = "main"
    x_cal: AxisCalibration = Field(default_factory=AxisCalibration)
    y_cal: AxisCalibration = Field(default_factory=AxisCalibration)
    x: AxisVariable = Field(default_factory=lambda: AxisVariable(label="x", column=None))
    y: AxisVariable = Field(default_factory=lambda: AxisVariable(label="y", column=None))


class DigitizedPoint(BaseModel):
    px: float
    py: float


class DigitizedSeries(BaseModel):
    label: str
    panel: int = 0                                  # index into DigitizedFigure.panels
    points: List[DigitizedPoint] = Field(default_factory=list)
    initial_species: List[SpeciesAmount] = Field(default_factory=list)
    initial_temperature_C: Optional[float] = None
    initial_pH: Optional[float] = None
    notes: Optional[str] = None


class DigitizedFigure(BaseModel):
    figure_id: str
    number: int
    page: int
    caption: str
    render_scale: float
    page_image: str
    figure_bbox: Optional[BBox] = None              # the detected area, PDF points (for the audit image)
    data_source: str = ""                           # original reference if the plotted data is cited
    panels: List[DigitizedPanel] = Field(default_factory=lambda: [DigitizedPanel()])
    series: List[DigitizedSeries] = Field(default_factory=list)
    plan: Optional[FigurePlan] = None               # the suggestions it started from, for the audit trail
