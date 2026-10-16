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
    # numbers in the PDF's text layer inside the figure (vector plots' tick labels):
    # (centre x, centre y, value) in page-image pixels; empty for plots that are images
    tick_numbers: List[Tuple[float, float, float]] = Field(default_factory=list)


# ---- the model's suggestions (structured output of the figure_planner stage) ----

class SpeciesAmount(BaseModel):
    name: str = Field(description="Species name from the controlled vocabulary, e.g. 'NaCl', 'Gly'.")
    concentration_mM: Optional[float] = Field(description="Initial concentration in mM (mol dm-3 x 1000).")
    basis: Literal["stated", "indirect"] = Field(
        default="stated",
        description="'stated': the paper gives this as the starting concentration. 'indirect': the paper "
                    "gives it another way -- e.g. measured in a control run without reaction, or for the feed "
                    "or injected solution -- and it's the best available value (say what in `source`).")
    source: str = Field(default="", description="Where and how the paper gives it, e.g. 'Methods: outlet "
                                                "concentration in the 27 C control run, hand-operated system'.")


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
    tick_labels: List[float] = Field(
        default_factory=list,
        description="The numbers printed at this axis's labelled ticks, in order from the low end of the "
                    "axis (left / bottom) to the high end, exactly as printed, e.g. [200, 250, 300, 350, "
                    "400, 450]. Used to place the calibration markers automatically.")
    note: Optional[str] = None


class SeriesCondition(BaseModel):
    """Any other experimental condition of a series (pressure, flow rate, volume,
    atmosphere, residence time, ...): the column it belongs in and the value AS PRINTED,
    with its unit -- converted to the column's unit by the app (units.py), not the model.
    Flat, no Optional fields (structured-output grammar size)."""
    column: str = Field(description="The column this condition belongs in, chosen from the column list, e.g. "
                                    "'initial_pressure_bar', 'flow_rate_mL_min', 'headspace_gas_name'. If no "
                                    "column fits, a short snake_case name for a new one.")
    value: str = Field(description="As printed, with its unit, e.g. '22.2 MPa', '10 mL min-1', 'N2'.")
    source: str = Field(default="", description="Where it's stated, e.g. 'caption', 'Methods', 'legend'.")


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
    conditions: List[SeriesCondition] = Field(
        default_factory=list,
        description="Every OTHER stated condition of this series (pressure, flow rate, volumes, gas, "
                    "residence time, ...), including ones shared by the whole panel or figure.")
    y_column: str = Field(
        default="",
        description="Only when this series' y values belong in a DIFFERENT column than its panel's y-axis "
                    "column -- an axis shared by several quantities (e.g. 'Concentration of Gly-Gly and "
                    "diketopiperazine': the diketopiperazine series -> its own column). '' otherwise.")
    notes: Optional[str] = None


class PlannedPanel(BaseModel):
    name: str = Field(description="'main', or e.g. '(a)', '(b)', 'right y-axis' when a figure "
                                  "has several panels or a second axis.")
    x: AxisVariable
    y: AxisVariable
    series: List[PlannedSeries] = Field(default_factory=list)


class ConcentrationFound(BaseModel):
    """A concentration the paper gives for a species in this figure's experiments, as
    printed; the app converts it and fills it into the series it applies to (only where
    the series has no concentration for that species yet). Flat, no Optional fields."""
    species: str = Field(description="Species name as in the series' initial_species, e.g. 'Gly'.")
    value: str = Field(description="As printed, with its unit, e.g. '0.065 M', '1.0 mol dm-3', '50 mM'.")
    series: List[str] = Field(default_factory=list,
                              description="Exact labels of the series it applies to; [] = all series.")
    basis: Literal["stated", "indirect"] = Field(
        default="stated", description="'indirect' when the paper gives it another way than as the starting "
                                      "concentration (control run without reaction, feed/injected solution).")
    source: str = Field(default="", description="Where and how it's given, e.g. 'Methods: outlet concentration "
                                                "in the control run, hand-operated injection system'.")


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
    concentrations: List[ConcentrationFound] = Field(
        default_factory=list,
        description="EVERY concentration the paper gives (anywhere: caption, passages, concentration "
                    "passages) for the species of these series, with the series each applies to.")
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
    conditions: List[SeriesCondition] = Field(default_factory=list)   # pressure, flow rate, ... (editable)
    y_column: str = ""                              # overrides the panel's y column for this series ('' = use it)
    notes: Optional[str] = None


class DigitizedFigure(BaseModel):
    figure_id: str
    number: int
    page: int
    caption: str
    render_scale: float
    page_image: str
    figure_bbox: Optional[BBox] = None              # the detected area, PDF points (for the audit image)
    tick_numbers: List[Tuple[float, float, float]] = Field(default_factory=list)   # see FigureCandidate
    data_source: str = ""                           # original reference if the plotted data is cited
    panels: List[DigitizedPanel] = Field(default_factory=lambda: [DigitizedPanel()])
    series: List[DigitizedSeries] = Field(default_factory=list)
    plan: Optional[FigurePlan] = None               # the suggestions it started from, for the audit trail
