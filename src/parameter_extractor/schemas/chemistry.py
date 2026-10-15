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
from pydantic import BaseModel, Field
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
    quote: str = ""
    source: str = ""


class SoluteEntry(BaseModel):
    name: str = Field(description="Chemical species/compound name as it should appear in the "
                                   "database -- match the controlled vocabulary in "
                                   "schemas/template_vocab.json when the compound is already "
                                   "tracked there (e.g. 'NaCl', 'CuCl2', 'Gly').")
    in_controlled_vocab: bool = Field(
        description="Whether `name` matched an existing template_vocab.json entry. False "
                    "means this is a new species not yet a column -- flag for ontology/"
                    "template extension rather than silently coining a new column."
    )
    phase: Phase
    role: Role
    set_label: Optional[str] = Field(
        default=None,
        description="Which structure-plan set this value belongs to, or null if it's "
                    "constant across the whole paper (e.g. the fixed 0.5 mol dm-3 CuCl2 "
                    "background present in every condition in eder1994).",
    )
    sample_label: Optional[str] = Field(
        default=None,
        description="For role 'sampled': the exact structure-plan sample_label (within "
                    "set_label) this measurement belongs to, e.g. 't = 97.3 h'. Null for "
                    "initial-composition values that apply to the whole set.",
    )
    concentration_value: Optional[float] = Field(description="Numeric value in the ORIGINAL reported unit.")
    concentration_unit_raw: Optional[str] = Field(description="Unit exactly as stated, e.g. 'mol dm-3'.")
    concentration_basis: ConcentrationBasis = Field(
        default="mixture",
        description="'mixture' if the value is the concentration in the reaction mixture itself; 'stock' "
                    "if it's the concentration of a solution BEFORE it was combined with others (e.g. "
                    "'5 µL of a 15 mM solution was added to ...'). Never convert a stock value to a "
                    "mixture value yourself -- the pipeline calculates that from `added_solutions`.",
    )
    stock_solution: str = Field(
        default="",
        description="For a 'stock' value: the `solution` label (in added_solutions) of the solution it "
                    "was added in. '' otherwise.",
    )
    concentration_mM: Optional[float] = Field(
        default=None,
        description="Converted to mM. Leave null and flag in `conversion_note` if the "
                    "conversion requires an assumption (e.g. an unstated molecular weight) "
                    "rather than silently computing a possibly-wrong number.",
    )
    conversion_note: Optional[str] = None
    quote: str
    source: str
    confidence: Literal["high", "medium", "low"]
    # set by calculators/mixing.py, never by the model (hidden from its schema)
    derived: SkipJsonSchema[bool] = False
    # set by ingestion/normalize.py from PubChem (pubchem.py); 0 / "" = not looked up or not found
    pubchem_cid: SkipJsonSchema[int] = 0
    pubchem_title: SkipJsonSchema[str] = ""

    @property
    def variable(self) -> str:
        """Which variable this value is, among entries for the same set/sample: the
        species name, or 'stock <name>' for a stock-solution concentration (both
        can exist for one species, in different columns)."""
        return f"stock {self.name}" if self.concentration_basis == "stock" else self.name


class ChemistryExtraction(BaseModel):
    paper_id: str
    solutes: List[SoluteEntry]
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
