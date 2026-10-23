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
    # set by calculators/mixing.py, never by the model (hidden from its schema)
    derived: SkipJsonSchema[bool] = False
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
        return f"stock {self.name}" if self.concentration_basis == "stock" else self.name


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


class ChemistryExtraction(BaseModel):
    model_config = ConfigDict(populate_by_name=True,
                              json_schema_extra=_required(["groups", "unmapped_species", "added_solutions",
                                                           "molar_ratios"]))
    paper_id: SkipJsonSchema[str] = ""
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

    @model_validator(mode="after")
    def _flatten(self):
        for group in self.groups:
            for entry in group.species:
                entry.set_label = group.set_label or None
                entry.sample_label = group.sample_label or None
                self.solutes.append(entry)
        self.groups = []                 # kept once, in `solutes` (what's saved and replayed)
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
