"""
The order of a dataset's columns -- in the CSV and the GUI's Rows tab (Mickey, 2026-11-02): the row's
identifiers (entry_number, full_id, set_id, sample_id), then one block per variable category in its
`table_order` (Metadata, Experimental Methodology, ..., the solution chemistry: starting species, then
products), then Other, then the pipeline's provenance columns.

Which category a column belongs to is configured, not coded (variable_categories.py): a category lists
`columns` by name and/or `patterns` (regular expressions); a pack adds columns to any category with
"category_columns" in its pack.json, and can define column-only categories (model_assigns false: never
offered to the model). A column is placed by, in this order:
  1. a category naming it in `columns`;
  2. the category it was accepted under in a review (this run's choices, or the registry's memory);
  3. its base column -- uncertainty / alternative-estimate / mode / range / average columns sit right after
     the column they belong to ('initial_temperature_C_err_plus', 'pl_orbpererr1', 'x_range_g');
  4. the first category (in definition order) with a matching pattern;
  5. Other.
Within a block: the category's own `columns` order, then the pack's template order, then the app's standard
columns, then by name.
"""
from __future__ import annotations
import re
from typing import Dict, Iterable, List, Optional, Tuple

IDENTIFIERS = ["entry_number", "full_id", "set_id", "sample_id"]
PROVENANCE = ["yield_below_threshold_note", "source_notes", "extraction_confidence"]
OTHER = "other"
IDENTIFIERS_LABEL, PROVENANCE_LABEL = "Row", "Provenance"


def _suffix_rank(rest: str) -> int:
    """A derived column's place after its value: uncertainties and limit, modes, other estimates, priors."""
    for rank, pattern in enumerate((r"^_?(err|lim)", r"^_?modal|^_?mode", r"^_?alt", r"^_?prior")):
        if re.match(pattern, rest):
            return rank
    return 4


def _numbers_first(column: str) -> tuple:
    """'x_alt2' before 'x_alt10'; within one estimate its value, then '+' and '-' uncertainty, then method."""
    column = column.replace("_err_plus", "_err_1").replace("_err_minus", "_err_2")
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"(\d+)", column) if p)


def _strip_markers(column: str) -> str:
    """Without the range / average markers inserted before the unit ('x_avg_range_mM' -> 'x_mM')."""
    from parameter_extractor.ingestion.flatten_to_template import without_range
    column = without_range(column)
    return re.sub(r"_avg(?=_|$)", "", column, count=1)


class ColumnOrder:
    """Column placement for one pack (and this run's / the registry's category choices)."""

    def __init__(self, pack=None, chosen: Optional[Dict[str, str]] = None, registry=None):
        from parameter_extractor import packs, variable_categories
        self.pack = pack or packs.current()
        cats = [c for c in variable_categories.categories(self.pack)
                if c.id not in (variable_categories.FIGURE.id, variable_categories.ASSUMED.id)]
        self.categories = cats
        self.by_id = {c.id: c for c in cats}
        self.display = sorted(cats, key=lambda c: (c.table_order, cats.index(c)))
        self.explicit: Dict[str, Tuple[str, int]] = {}
        for c in cats:
            for i, col in enumerate(c.columns):
                self.explicit.setdefault(col, (c.id, i))
        self.patterns = [(c.id, re.compile(p)) for c in cats for p in c.patterns]
        self.chosen = dict(chosen or {})
        if registry is not None:
            for col, info in getattr(registry, "added_columns", {}).items():
                if info.get("category"):
                    self.chosen.setdefault(col, info["category"])
        from parameter_extractor.registry import standard_columns
        self.template = {c: i for i, c in enumerate(self.pack.template_columns)}
        # the active pack's standard columns include its stages' columns; another pack's: its listed ones
        standard = (standard_columns() if self.pack.id == packs.current().id
                    else [c["column"] for c in self.pack.standard_column_entries])
        self.standard = {c: i for i, c in enumerate(standard)}
        self._cat_cache: Dict[str, str] = {}
        self._base_cache: Dict[str, Optional[str]] = {}

    def category_of(self, column: str) -> str:
        if column not in self._cat_cache:
            self._cat_cache[column] = self._category_of(column)
        return self._cat_cache[column]

    def _category_of(self, column: str) -> str:
        if column in self.explicit:
            return self.explicit[column][0]
        if self.chosen.get(column) in self.by_id:
            return self.chosen[column]
        base = self._base(column)
        if base is not None:
            return self.category_of(base)
        for cid, pattern in self.patterns:
            if pattern.search(column):
                return cid
        return OTHER if OTHER in self.by_id else (self.display[-1].id if self.display else "")

    def _base(self, column: str) -> Optional[str]:
        if column not in self._base_cache:
            self._base_cache[column] = self._find_base(column)
        return self._base_cache[column]

    def _find_base(self, column: str) -> Optional[str]:
        """The column this one is derived from: the longest known column it extends ('_err_plus', 'err1',
        '_alt2_method', 'mode1desc', ...), after taking out range / average markers."""
        stripped = _strip_markers(column)
        if stripped != column and (stripped in self.explicit or stripped in self.template):
            return stripped
        known = [c for c in (*self.explicit, *self.template) if c != column and len(c) >= 4
                 and stripped.startswith(c) and len(stripped) > len(c)
                 and (stripped[len(c)] in "_" or not stripped[len(c)].isalpha() or self._suffix(stripped[len(c):]))]
        return max(known, key=len) if known else None

    @staticmethod
    def _suffix(rest: str) -> bool:
        """Archive-style suffixes glued to the name ('err1', 'lim', 'mode2desc', 'alt1method', 'priorcen')."""
        return bool(re.match(r"(err\d|lim|modal_flag|mode\d|alt\d|prior|str\b)", rest))

    def _key(self, column: str) -> tuple:
        cid = self.category_of(column)
        base = self._base(column) if column not in self.explicit else None
        anchor = base or column
        own = self.explicit.get(anchor, (cid, None))[1]
        if base is None:
            rank = 0
        elif column.startswith(anchor):
            rank = 2 + _suffix_rank(column[len(anchor):])
        else:
            rank = 1                         # the value's range / average ('x_range_g'): right after it
        return (own if own is not None and self.explicit[anchor][0] == cid else 10**6,
                self.template.get(anchor, 10**6), self.standard.get(anchor, 10**6), anchor,
                rank, _numbers_first(column))

    def ordered(self, columns: Iterable[str]) -> List[str]:
        cols = list(dict.fromkeys(columns))
        head = [c for c in IDENTIFIERS if c in cols]
        tail = [c for c in PROVENANCE if c in cols]
        rest = [c for c in cols if c not in head and c not in tail]
        rank = {c.id: i for i, c in enumerate(self.display)}
        rest.sort(key=lambda c: (rank.get(self.category_of(c), len(rank)), self._key(c)))
        return head + rest + tail

    def label_of(self, column: str) -> str:
        """The block a column is shown under: 'Row', a category's label, or 'Provenance'."""
        if column in IDENTIFIERS:
            return IDENTIFIERS_LABEL
        if column in PROVENANCE:
            return PROVENANCE_LABEL
        cat = self.by_id.get(self.category_of(column))
        return cat.label if cat else "Other"

    def groups(self, columns: Iterable[str], keep_order: bool = False) -> List[Tuple[str, List[str]]]:
        """[(label, columns)] in display order (or in the order given), for the GUI: Row, the categories,
        Provenance."""
        out: List[Tuple[str, List[str]]] = []
        for column in (list(columns) if keep_order else self.ordered(columns)):
            label = self.label_of(column)
            if out and out[-1][0] == label:
                out[-1][1].append(column)
            else:
                out.append((label, [column]))
        return out
