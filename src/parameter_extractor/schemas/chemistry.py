"""Stage 3c: chemical species and concentrations.

Deliberately modeled as a LIST of (name, concentration) pairs rather than one
field per compound. This mirrors how POLO's own variable mapping treats it:
every initial_<X>_aq_mM / sampled_<X>_aq_mM column in the wide template maps
to the SAME ontology pattern (status == 'pattern_direct' in
POLO_variable_mapping.csv) -- a repeated soluteName/soluteConcentration pair
on a LiquidPhase node, not 150 distinct ontology properties. Extracting into
that shape first, then mapping names onto the wide template's columns as a
separate flattening step, keeps the schema handed to the model small
regardless of how many species the full template happens to track.
"""
from __future__ import annotations
import re
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from parameter_extractor.schemas.common import QUOTE_DESC, SOURCE_DESC
from pydantic.json_schema import SkipJsonSchema

Phase = Literal["aq", "gas", "solid"]
Role = Literal["initial", "sampled"]
ConcentrationBasis = Literal["mixture", "stock"]


class AddedSolution(BaseModel):
    """One solution (or pure solvent) combined to make a reaction mixture, with
    the volume added -- what calculators/mixing.py needs to turn stock
    concentrations into mixture concentrations. Flat, no Optional fields
    (structured-output grammar size)."""
    set_label: str = Field(default="", description="The structure-plan set_label this applies to, or '' if "
                                                   "the same in every set.")
    # kim2017 live run (2026-10-29): one set whose samples differ by the volume of one stock added
    sample_label: str = Field(default="", description="Exact sample_label when this volume differs between the "
                                                      "samples of one set; else ''.")
    solution: str = Field(description="Short label, e.g. 'ribose 1,2-cyclic phosphate stock', 'nucleobase "
                                      "solution', 'water'. Species entries refer to it in `stock_solution`.")
    volume: str = Field(description="Volume added, exactly as printed with its unit, e.g. '5 µL', '0.2 mL'.")
    quote: str = Field(default="", description=QUOTE_DESC)
    source: str = Field(default="", description=SOURCE_DESC)


class MolarRatio(BaseModel):
    """A molar ratio between two species that the paper gives instead of (some of)
    their concentrations, e.g. kim2019's "3 : cytosine = 1:2". calculators/mixing.py
    uses it to calculate the missing concentration. Flat, no Optional fields."""
    set_label: str = Field(default="", description="The structure-plan set_label this ratio applies to, or '' "
                                                   "if it's the same in every set.")
    species: str = Field(description="The species whose amount is `species_parts`, named as in `solutes`.")
    reference_species: str = Field(description="The other species (amount `reference_parts`), named as in "
                                               "`solutes`.")
    species_parts: float
    reference_parts: float
    ratio_text: str = Field(description="The ratio exactly as printed, e.g. '3 : cytosine = 1:2'.")
    quote: str = Field(default="", description=QUOTE_DESC)
    source: str = Field(default="", description=SOURCE_DESC)


class TotalPart(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(alias="nm", description="Species name, as in the species entries' `nm`.")
    share: float = Field(alias="n", description="Its parts in the ratio (1 for '1:1'; for 'A:B = 1:3', "
                                                "A 1 and B 3).")


def _strict_parts(schema: dict) -> None:
    schema["required"] = list(schema.get("properties", {}))


class MixtureTotal(BaseModel):
    """A combined amount or concentration of several species with their ratio (Chen2007:
    'amino acids and/or peptides (1:1 ratio of each component, total 1 mmol)') -- split
    into each species' value by calculators/amounts.py, not by the model."""
    model_config = ConfigDict(populate_by_name=True, json_schema_extra=_strict_parts)
    set_label: str = Field(default="", alias="set", description="Exact structure-plan set_label; '' if the "
                                                                "same in every set.")
    sample_label: str = Field(default="", alias="sample", description="Exact sample_label when the "
                                                                      "components differ by sample; else ''.")
    total: str = Field(description="The combined amount or concentration exactly as printed, e.g. '1 mmol', "
                                   "'10 mM'.")
    parts: List[TotalPart] = Field(description="Every species the total is shared between, with its share. A "
                                               "single species gets the whole total.")
    quote: str = Field(default="", alias="q", description=QUOTE_DESC)
    source: str = Field(default="", alias="src", description=SOURCE_DESC)


def _required(names):
    def extra(schema: dict) -> None:
        schema["required"] = [n for n in names if n in schema.get("properties", {})]
    return extra


class SoluteEntry(BaseModel):
    """One species' concentration. The model's answer format is compact (2026-10-22, like the
    exoplanet stages): short field-name ALIASES, entries grouped per set/sample (SoluteGroup),
    optional fields left out when they don't apply. The code reads the long names; answers
    recorded in the old flat format still load (populate_by_name)."""
    model_config = ConfigDict(populate_by_name=True,
                              json_schema_extra=_required(["nm", "r", "ph", "v", "u", "q", "src", "c"]))

    name: str = Field(alias="nm", description="Species name: the controlled-vocabulary name when it's there "
                                              "(e.g. 'NaCl', 'Gly'), else as the paper writes it.")
    # not asked of the model (nothing reads it); kept for older recordings and calculators/mixing.py
    in_controlled_vocab: SkipJsonSchema[bool] = False
    phase: Phase = Field(alias="ph")
    role: Role = Field(alias="r")
    # from the group (SoluteGroup) -- or, in older recordings, from the entry itself
    set_label: SkipJsonSchema[Optional[str]] = None
    sample_label: SkipJsonSchema[Optional[str]] = None
    concentration_value: Optional[float] = Field(alias="v", description="Numeric value in the ORIGINAL reported "
                                                                        "unit; null if the paper gives none.")
    concentration_unit_raw: Optional[str] = Field(alias="u", description="Unit exactly as stated, e.g. 'mol dm-3', "
                                                                         "'%'.")
    concentration_basis: ConcentrationBasis = Field(
        default="mixture", alias="b",
        description="Leave out for the concentration in the reaction mixture itself; 'stock' for a solution "
                    "BEFORE it was combined with others ('5 µL of a 15 mM solution was added'). Never convert a "
                    "stock value yourself -- the pipeline does it from `added_solutions`.")
    stock_solution: str = Field(default="", alias="stk", description="For a 'stock' value: the `solution` label "
                                                                     "(in added_solutions) it was added in.")
    concentration_mM: Optional[float] = Field(
        default=None, alias="mM",
        description="Converted to mM, only when unambiguous; leave out otherwise (and say why in `cn` if an "
                    "assumption such as a molecular weight would be needed).")
    conversion_note: Optional[str] = Field(default=None, alias="cn", description="Why there's no mM value; "
                                                                                 "at most 15 words.")
    quote: str = Field(alias="q", description=QUOTE_DESC)
    source: str = Field(alias="src", description=SOURCE_DESC)
    confidence: Literal["high", "medium", "low"] = Field(alias="c")
    # how the species was identified when the quote doesn't name it (Chen2007, 2026-10-23: Table 2
    # gives acids and amines only as structure drawings -- the quote can't show which one it was)
    identified_by: str = Field(default="", alias="how",
                               description="Only when the quoted words don't name the species: how you "
                                           "identified it, at most 15 words -- e.g. 'structure drawing, "
                                           "Table 2 entry 3', 'compound 7 = ...', 'abbreviation FF'.")
    # a result named without an amount (Mickey, 2026-10-23): 'detected' is written as the text
    # "detected", 'not detected' as 0 (calculators/amounts.py)
    # what a sampled % means (Mickey, 2026-10-29): a product's yield, or how much of a starting material was
    # recovered -> sampled_<name>_%recovered
    average: bool = Field(
        default=False, alias="avg",
        description="True when the value is an AVERAGE over several runs or replicates (mean, avg., 'averaged "
                    "across triplicate experiments'); leave out otherwise.")
    measure: Literal["yield", "recovered", "ratio"] = Field(
        default="yield", alias="meas",
        description="For a sampled value only: 'recovered' when it is the % of a STARTING material left "
                    "unreacted or recovered (e.g. 'Recovered nicotinamide (%)'); 'ratio' when it is a ratio "
                    "between products (e.g. 'ribo : arabino', name the species 'II : III'); leave out for a "
                    "product yield or concentration.")
    detection: Literal["", "detected", "not detected"] = Field(
        default="", alias="det",
        description="Only for a 'sampled' species with no amount (v null): 'detected' when the paper lists "
                    "it as observed / formed, 'not detected' when it says it was looked for and not found "
                    "('no product was detected'). Set `u` to the unit the paper's other results of that kind "
                    "use (e.g. '%' in a yield table).")
    # set by calculators/mixing.py / amounts.py, never by the model (hidden from its schema)
    derived: SkipJsonSchema[bool] = False
    calculated_from: SkipJsonSchema[str] = ""  # "amount": mM = amount / reaction volume (amounts.py)
    exact_mM: SkipJsonSchema[float] = 0.0      # a derived value before rounding, for chained calculations

    @property
    def mM_for_calculation(self) -> Optional[float]:
        return self.exact_mM or self.concentration_mM
    # set by ingestion/normalize.py from PubChem (pubchem.py); 0 / "" = not looked up or not found
    pubchem_cid: SkipJsonSchema[int] = 0
    pubchem_title: SkipJsonSchema[str] = ""

    @property
    def variable(self) -> str:
        """Which variable this value is, among entries for the same set/sample: the
        species name, or 'stock <name>' for a stock-solution concentration (both
        can exist for one species, in different columns)."""
        name = f"stock {self.name}" if self.concentration_basis == "stock" else self.name
        return name + (" avg" if self.average else "")


class SoluteGroup(BaseModel):
    """The model's grouping: one entry per set (and sample) with its species."""
    model_config = ConfigDict(populate_by_name=True, json_schema_extra=_required(["set", "species"]))
    set_label: str = Field(alias="set", description="Exact structure-plan set_label; '' if these values are "
                                                    "constant across the whole paper (a fixed background "
                                                    "reagent in every condition).")
    sample_label: str = Field(default="", alias="sample",
                              description="Exact structure-plan sample_label within the set: required for "
                                          "'sampled' values, and for initial values that differ between the "
                                          "set's samples; leave out for values of the whole set.")
    species: List[SoluteEntry]


# a trailing '%' is the column's unit printed in the cell (pulletikurti2022's '88%', '19%a'): 45 of 60 values
# were dropped before it was allowed
_CELL = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?|[-+]?\.\d+)\s*(?:[x×*·]\s*10\s*\^?\s*([-+]?\d+))?\s*%?"
                   r"\s*[a-zA-Z*†‡§#]{0,2}\s*(?:(?:±|\+/-|\+-)\s*\d+(?:\.\d+)?\s*%?\s*[a-zA-Z*]{0,2})?\s*$")


def _cell_number(text: str):
    """A table cell as printed -> its number: '2.77', '2.77a' (footnote mark), '1.2 × 10−3', '−0.5'.
    None for anything else -- never guessed: ranges, limits ('<0.1'), OCR-lost exponents ('10−4')."""
    t = text.replace("\u2212", "-").replace("\u2013", "-").replace(",", "").replace("\u00a0", " ")
    m = _CELL.match(t)
    if not m:
        return None
    if re.fullmatch(r"10-\d+", t.strip()):              # '10−4': an exponent whose superscript was lost
        return None
    value = float(m.group(1))
    return value * 10 ** int(m.group(2)) if m.group(2) else value


class TableColumn(BaseModel):
    """One species column of a results table (TableResults)."""
    model_config = ConfigDict(populate_by_name=True, json_schema_extra=_required(["nm", "r", "ph", "u", "lbl"]))
    name: str = Field(alias="nm", description="Species name, as for a species entry's `nm`.")
    role: Role = Field(alias="r")
    phase: Phase = Field(alias="ph")
    unit: str = Field(alias="u", description="The column's unit exactly as printed, e.g. '%', 'mmol/L'.")
    label: str = Field(alias="lbl", description="The column header as printed, e.g. '% (Gly)2'.")
    identified_by: str = Field(default="", alias="how",
                               description="Only when the header doesn't name the species: how you identified "
                                           "it, at most 15 words.")
    average: bool = Field(
        default=False, alias="avg",
        description="True when the value is an AVERAGE over several runs or replicates (mean, avg., 'averaged "
                    "across triplicate experiments'); leave out otherwise.")
    measure: Literal["yield", "recovered", "ratio"] = Field(
        default="yield", alias="meas",
        description="For a sampled value only: 'recovered' when it is the % of a STARTING material left "
                    "unreacted or recovered (e.g. 'Recovered nicotinamide (%)'); 'ratio' when it is a ratio "
                    "between products (e.g. 'ribo : arabino', name the species 'II : III'); leave out for a "
                    "product yield or concentration.")


class TableRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True, json_schema_extra=_required(["set", "sample", "row", "v"]))
    set_label: str = Field(alias="set", description="Exact structure-plan set_label of this row.")
    sample_label: str = Field(alias="sample", description="Exact structure-plan sample_label of this row.")
    label: str = Field(alias="row", description="The row's label as printed, e.g. '97.3' (a time), 'Entry 3'.")
    values: List[str] = Field(alias="v", description="One per column, in column order, exactly as printed "
                                                     "('2.77'); 'nd' where the paper reports the product as "
                                                     "not detected, 'detected' where it's present without an "
                                                     "amount, '' for an empty or not-measured cell.")


class TableResults(BaseModel):
    """A table's values in its own layout (2026-10-27): the columns once, then one row per sample with
    just its values -- not one species entry per cell repeating the name, role, unit, quote and source
    (most of the chemistry answer: faisal2005's 225 cells were 27K output tokens). Expanded into the
    same species entries (`ChemistryExtraction.solutes`) with a quote from the row label and value and
    the source table, row and column."""
    model_config = ConfigDict(populate_by_name=True, json_schema_extra=_required(["src", "cols", "rows", "c"]))
    source: str = Field(alias="src", description="The table, e.g. 'Table 1' (or 'Table 2, upper part').")
    columns: List[TableColumn] = Field(alias="cols")
    rows: List[TableRow]
    confidence: Literal["high", "medium", "low"] = Field(alias="c")

    _ND = {"nd", "n.d.", "n.d", "not detected", "<lod", "bdl", "b.d.l."}
    _DETECTED = {"detected", "+", "present", "yes"}

    def entries(self) -> List["SoluteEntry"]:
        out = []
        for row in self.rows:
            for col, raw in zip(self.columns, row.values):
                text = (raw or "").strip()
                if not text or text in ("-", "\u2013", "\u2014", "n.m.", "nm") or re.fullmatch(r"[-\u2013\u2014]\s*[a-z*†‡]?", text):
                    continue                             # empty, or a dash with a footnote mark ('-b')
                low = text.lower()
                detection = "not detected" if low in self._ND else "detected" if low in self._DETECTED else ""
                number, note = None, None
                if not detection:
                    number = _cell_number(text)
                    if number is None:                   # a range, '<0.1', '10-4': kept, flagged, never guessed
                        note = f"table cell '{text}' isn't a single number -- not read"
                out.append(SoluteEntry(
                    name=col.name, role=col.role, phase=col.phase, set_label=row.set_label or None,
                    sample_label=row.sample_label or None, concentration_value=number, conversion_note=note,
                    concentration_unit_raw=col.unit or None, detection=detection if col.role == "sampled" else "",
                    quote=f"{row.label} {text}".strip(),
                    source=f"{self.source}, row {row.label}, column {col.label}",
                    confidence=self.confidence, identified_by=col.identified_by, measure=col.measure,
                    average=col.average))
        return out


class ChemistryExtraction(BaseModel):
    model_config = ConfigDict(populate_by_name=True,
                              json_schema_extra=_required(["tables", "groups", "unmapped_species",
                                                           "added_solutions", "molar_ratios", "mixture_totals"]))
    paper_id: SkipJsonSchema[str] = ""
    tables: List[TableResults] = Field(default_factory=list,
                                       description="Every table of values, in its own layout: columns once, "
                                                   "one row per sample.")
    groups: List[SoluteGroup] = Field(default_factory=list,
                                      description="Species grouped by set (and sample): one entry per set/sample "
                                                  "that has species.")
    # the flat list the code works with: groups flattened (below), or an older recording's "solutes"
    solutes: SkipJsonSchema[List[SoluteEntry]] = Field(default_factory=list)
    unmapped_species: List[str] = Field(
        default_factory=list,
        description="Species names encountered that don't match the controlled vocabulary "
                    "-- surfaced for human review / ontology extension, never silently dropped.",
    )
    added_solutions: List[AddedSolution] = Field(
        default_factory=list,
        description="When the paper says how a reaction mixture was made by combining volumes of "
                    "solutions: EVERY solution and solvent combined, with its volume, so the mixture "
                    "concentrations can be calculated. Empty if the paper doesn't say.",
    )

    molar_ratios: List[MolarRatio] = Field(
        default_factory=list,
        description="Molar ratios between species, per set, when the paper states them (e.g. 'ribose "
                    "phosphate : cytosine = 1:2'). Record them even when the concentrations are also given.",
    )

    mixture_totals: List[MixtureTotal] = Field(
        default_factory=list,
        description="A total amount or concentration the paper gives for several species together, with their "
                    "ratio ('1:1 ratio of each component, total 1 mmol'), per set/sample. The pipeline splits it.",
    )

    @model_validator(mode="after")
    def _flatten(self):
        for group in self.groups:
            for entry in group.species:
                entry.set_label = group.set_label or None
                entry.sample_label = group.sample_label or None
                self.solutes.append(entry)
        for table in self.tables:
            self.solutes.extend(table.entries())
        self.groups, self.tables = [], []    # kept once, in `solutes` (what's saved and replayed)
        return self

    def conflicting_set_species(self) -> set:
        """(set_label, name) pairs with several DIFFERENT initial values for the same
        set and no sample_label to tell them apart (seen in truman2024's Table 2
        before the prompt asked for sample labels). Writing any one of them would
        put wrong values on most rows, so they're left out and flagged."""
        values: dict = {}
        for s in self.solutes:
            if s.role == "initial" and s.set_label is not None and not s.sample_label:
                values.setdefault((s.set_label, s.variable), set()).add(s.concentration_mM)
        return {k for k, v in values.items() if len(v) > 1}

    def ambiguous_paper_wide_species(self) -> set:
        """Initial species given BOTH as paper-wide (set_label null) and for a
        specific set somewhere else. A genuinely paper-wide background reagent
        never also varies by set, so the null-labelled entry is most likely a
        set-specific value missing its set_label -- applying it to every set
        would put it on rows where it doesn't belong (seen with NaCl in one
        eder1994 run)."""
        paper_wide = {s.variable for s in self.solutes if s.role == "initial" and s.set_label is None}
        per_set = {s.variable for s in self.solutes if s.role == "initial" and s.set_label is not None}
        return paper_wide & per_set
