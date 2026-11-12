"""
Measured or calculated: what a row's results are (Mickey, 2026-11-12, Cleaves2008: Table 1's 'Calculated equilibrium
concentrations' are a model's values, not sampled concentrations -- tracked per row so datasets can be filtered).

Local, no model. `result_basis` per row:
- "calculated" -- its results are values the paper calculated or modelled: only calculated_ compound columns, or its
  experiment set is described as calculated (set label, the caption of the table it comes from, the row's source notes:
  'calculated equilibrium concentrations', 'modelled', 'simulated', 'predicted values', 'theoretical yields' ...).
  In such a set, values the chemistry step put in sampled_ columns move to calculated_ ones (flagged).
- "measured" -- results measured in the experiments (sampled_ / total_sampled_ values).
- "" -- no results on the row (a starting composition only).
Data reproduced from another paper keeps its own basis (original_data_reference says where it comes from).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict
from parameter_extractor.schemas.row_schema import CellSource
from parameter_extractor.validation.plausibility_checks import Flag

COLUMN = "result_basis"
MEASURED, CALCULATED = "measured", "calculated"
_MEASURED = re.compile(r"^(?:total_sampled_|sampled_.+_(?:aq|gas|s)(?:_[a-z0-9]+)*_)")
_CALCULATED = re.compile(r"^(?:total_calculated_|calculated_.+_(?:aq|gas|s)(?:_[a-z0-9]+)*_)")
# a set described as computed rather than measured
_SAYS_CALCULATED = re.compile(
    r"\b(?:calculated|computed|modell?ed|simulated|predicted|theoretical|estimated)\s+(?:equilibri\w*|concentrations?|"
    r"values?|yields?|data|results?|distributions?|abundances?|amounts?)\b"
    r"|\b(?:equilibrium|thermodynamic|kinetic)\s+(?:calculations?|model(?:l?ing)?|simulations?)\b"
    r"|\bmodel\s+predictions?\b|\bsimulations?\s+(?:of|results?)\b", re.IGNORECASE)


def _empty(v) -> bool:
    return v is None or v == "" or (isinstance(v, float) and v != v)


def says_calculated(*texts: Optional[str]) -> str:
    """The phrase that marks a description as calculated / modelled ('' if none)."""
    for t in texts:
        m = _SAYS_CALCULATED.search(t or "")
        if m:
            return m.group(0)
    return ""


def apply_result_basis(rows, set_labels: List[str], table_captions: Dict[str, str]) -> List[Flag]:
    """Write result_basis on every row; move a calculated set's sampled_ compound values to calculated_ columns.
    `set_labels`: the row plan's set labels in order (set n = rows whose set_id ends in n); `table_captions`:
    {'Table. 1': caption} by data_location."""
    moved: Dict[str, list] = {}
    for r in rows:
        n = int(r.set_id[-3:]) if r.set_id[-3:].isdigit() else 0
        label = set_labels[n - 1] if 0 < n <= len(set_labels) else ""
        where = str(r.extra.get("data_location", "") or "")
        phrase = says_calculated(label, table_captions.get(where, ""), r.source_notes)
        if phrase:
            for store in (r.species_mM, r.extra):
                for column in [c for c in store if _MEASURED.match(c) and not c.startswith("total_")]:
                    new = "calculated_" + column[len("sampled_"):]
                    store[new] = store.pop(column)
                    if column in r.provenance:
                        r.provenance[new] = r.provenance.pop(column)
                    moved.setdefault(phrase, []).append((r.full_id, column, new))
        record = row_to_template_dict(r)
        measured = any(_MEASURED.match(c) and not _empty(v) for c, v in record.items())
        calculated = any(_CALCULATED.match(c) and not _empty(v) for c, v in record.items())
        basis = CALCULATED if (phrase and (calculated or measured)) or (calculated and not measured) else \
            MEASURED if measured else ""
        if basis:
            r.extra[COLUMN] = basis
            why = (f"the set is described as calculated ('{phrase}')" if phrase else
                   "its results are in calculated_ columns" if basis == CALCULATED else
                   "its results are in sampled_ (measured) columns")
            r.provenance[COLUMN] = CellSource(origin="calculated", source=f"result basis: {why}")
    flags = []
    for phrase, items in moved.items():
        rows_ = sorted({fid for fid, _o, _n in items})
        cols = sorted({f"{o} -> {n}" for _f, o, n in items})
        flags.append(Flag(
            "derived_value",
            f"{len(items)} value(s) moved to calculated_ columns: their experiment set is described as calculated "
            f"('{phrase}'), so they are the paper's calculated values, not measured ones -- {'; '.join(cols[:6])}"
            f"{' ...' if len(cols) > 6 else ''}. Rows: {', '.join(rows_)}."))
    return flags
