"""
Formulas: calculations a research area declares without code (Mickey, 2026-11-05). pack.json:

    "formulas": [
      {"column": "temperature_K", "expression": "temperature_C + 273.15",
       "description": "the temperature in kelvin", "if_present": "check"}
    ]

Each formula fills its column on every row where all its inputs have values, after the review (so accepted values
count), in list order (a later formula can use an earlier one's column). The column's unit is whatever its name
says (temperature_K: K); inputs are in their own columns' units -- the formula does any conversion itself.

The expression language -- parsed with Python's `ast` and evaluated by a whitelist, never eval():
  columns          temperature_C, or `sampled_Gly-Gly_aq_%yield` in backticks (names with - % ( ) etc.)
  numbers          2, 0.5, 1e-3; constants pi, e
  arithmetic       + - * / ** and parentheses; comparisons < <= > >= == != ; and, or, not
  functions        abs, min, max, round(x, digits), sqrt, exp, ln, log10
                   first(a, b, ...)         the first value that's there (e.g. first(measured_T, set_T))
                   ifelse(test, a, b)       a when test is true, else b
                   sum_of("regex"), mean_of, max_of, min_of, count_of
                                            over the row's columns whose NAME matches the pattern
                                            (e.g. sum_of("^sampled_.*_aq_%yield$"))
A column without a numeric value is MISSING: the result is missing too (the cell stays empty), except inside
first() / count_of() and the aggregates (which skip missing columns). Text values ('detected') count as missing.

if_present -- what happens where the row already has a value in the formula's column (e.g. the paper states it):
  "check"   (default) keep the paper's value; a calculated value that differs (> 1% or 0.05 absolute) is flagged
  "keep"    keep it, no comparison
  "replace" the formula's value replaces it
"""
from __future__ import annotations
import ast
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

IF_PRESENT = ("check", "keep", "replace")
CHECK_RELATIVE, CHECK_ABSOLUTE = 0.01, 0.05


class _Missing:
    def __repr__(self):
        return "MISSING"


MISSING = _Missing()


class FormulaError(ValueError):
    """An expression that can't be used (bad syntax, an unknown function, a disallowed construct)."""


_BACKTICK = re.compile(r"`([^`]+)`")
_FUNCTIONS = {"abs", "min", "max", "round", "sqrt", "exp", "ln", "log10", "first", "ifelse",
              "sum_of", "mean_of", "max_of", "min_of", "count_of", "col"}
_AGGREGATES = {"sum_of", "mean_of", "max_of", "min_of", "count_of"}
_CONSTANTS = {"pi": math.pi, "e": math.e}
FUNCTION_HELP = [
    ("abs(x), min(a, b, ...), max(a, b, ...)", "absolute value, smallest, largest"),
    ("round(x, digits)", "rounded to that many decimals"),
    ("sqrt(x), exp(x), ln(x), log10(x)", "square root, e^x, natural and base-10 logarithm"),
    ("first(a, b, ...)", "the first value that's there (the others are fallbacks)"),
    ("ifelse(test, a, b)", "a when the test is true, else b -- e.g. ifelse(pH < 7, 1, 0)"),
    ('sum_of("pattern"), mean_of, max_of, min_of, count_of',
     "over the row's columns whose name matches the pattern, e.g. sum_of(\"^sampled_.*_%yield$\")"),
    ("`column-name`", "a column whose name has characters like - % ( ) goes in backticks"),
]


def _prepare(expression: str) -> str:
    """Backtick names -> col("...") calls (identifiers can't hold - % ( ))."""
    return _BACKTICK.sub(lambda m: f"col({m.group(1)!r})", expression or "")


@dataclass
class Formula:
    column: str
    expression: str
    description: str = ""
    if_present: str = "check"
    _tree: Optional[ast.AST] = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Formula":
        return cls(column=(d.get("column") or "").strip(), expression=(d.get("expression") or "").strip(),
                   description=d.get("description", ""), if_present=d.get("if_present", "check") or "check")

    @property
    def tree(self) -> ast.AST:
        if self._tree is None:
            self._tree = parse(self.expression)
        return self._tree

    def inputs(self) -> List[str]:
        """The columns the expression names (not the aggregates' patterns)."""
        return referenced_columns(self.tree)

    def patterns(self) -> List[str]:
        return [a.args[0].value for a in ast.walk(self.tree)
                if isinstance(a, ast.Call) and isinstance(a.func, ast.Name) and a.func.id in _AGGREGATES
                and a.args and isinstance(a.args[0], ast.Constant)]


def parse(expression: str) -> ast.AST:
    """The checked syntax tree of an expression; FormulaError when it isn't allowed."""
    if not (expression or "").strip():
        raise FormulaError("the formula is empty")
    try:
        tree = ast.parse(_prepare(expression), mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"not a formula ({e.msg})") from None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
                name = getattr(node.func, "id", "?")
                raise FormulaError(f"unknown function '{name}'")
            if node.keywords:
                raise FormulaError(f"{node.func.id}() takes its values in order, without names")
            if node.func.id in _AGGREGATES | {"col"}:
                if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) \
                        or not isinstance(node.args[0].value, str):
                    raise FormulaError(f"{node.func.id}() takes one text in quotes")
                if node.func.id in _AGGREGATES:
                    try:
                        re.compile(node.args[0].value)
                    except re.error as e:
                        raise FormulaError(f"{node.func.id}(): not a valid pattern ({e})") from None
            if node.func.id == "ifelse" and len(node.args) != 3:
                raise FormulaError("ifelse() takes three values: test, then, else")
        elif isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Name, ast.Load,
                               ast.operator, ast.unaryop, ast.boolop, ast.cmpop)):
            pass
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, str)) or isinstance(node.value, bool):
                raise FormulaError(f"'{node.value}' can't be used in a formula")
        else:
            raise FormulaError(f"'{type(node).__name__}' isn't allowed in a formula")
    for node in ast.walk(tree):                   # text only as col() / pattern arguments
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if not _is_call_argument(tree, node):
                raise FormulaError(f"text '{node.value}' can only be a column name in backticks or a pattern")
    return tree


def _is_call_argument(tree: ast.AST, constant: ast.Constant) -> bool:
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", "") in _AGGREGATES | {"col"} and constant in n.args
               for n in ast.walk(tree))


def referenced_columns(tree: ast.AST) -> List[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in _FUNCTIONS \
                and node.id not in _CONSTANTS:
            out.append(node.id)
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "col":
            out.append(node.args[0].value)
    return list(dict.fromkeys(out))


def _number(value):
    if isinstance(value, bool) or value is None or value == "":
        return MISSING
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else MISSING
    try:
        return float(str(value).strip())
    except ValueError:
        return MISSING                               # text ('detected', 'low:high')


def evaluate(expression, values: Dict[str, object]):
    """The expression's value for one row's {column: value}; MISSING when an input is missing. Raises
    ZeroDivisionError / ValueError (math domain) for impossible arithmetic."""
    tree = expression if isinstance(expression, ast.AST) else parse(expression)
    return _eval(tree.body if isinstance(tree, ast.Expression) else tree, values)


def _eval(node, values):
    if isinstance(node, ast.Constant):
        return float(node.value) if isinstance(node.value, (int, float)) else node.value
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        return _number(values.get(node.id))
    if isinstance(node, ast.UnaryOp):
        x = _eval(node.operand, values)
        if x is MISSING:
            return MISSING
        return -x if isinstance(node.op, ast.USub) else x if isinstance(node.op, ast.UAdd) else float(not x)
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, values), _eval(node.right, values)
        if a is MISSING or b is MISSING:
            return MISSING
        op = type(node.op)
        ops = {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.Div: lambda: a / b,
               ast.Pow: lambda: a ** b, ast.Mod: lambda: a % b, ast.FloorDiv: lambda: a // b}
        if op not in ops:
            raise FormulaError("that operator isn't allowed")
        result = ops[op]()
        if isinstance(result, complex):
            raise ValueError("math domain error")
        return result
    if isinstance(node, ast.Compare):
        left = _eval(node.left, values)
        for op, right_node in zip(node.ops, node.comparators):
            right = _eval(right_node, values)
            if left is MISSING or right is MISSING:
                return MISSING
            ok = {ast.Lt: left < right, ast.LtE: left <= right, ast.Gt: left > right, ast.GtE: left >= right,
                  ast.Eq: left == right, ast.NotEq: left != right}.get(type(op))
            if not ok:
                return 0.0
            left = right
        return 1.0
    if isinstance(node, ast.BoolOp):
        parts = [_eval(v, values) for v in node.values]
        if any(p is MISSING for p in parts):
            return MISSING
        return float(all(parts)) if isinstance(node.op, ast.And) else float(any(parts))
    if isinstance(node, ast.Call):
        name = node.func.id
        if name == "col":
            return _number(values.get(node.args[0].value))
        if name in _AGGREGATES:
            pattern = re.compile(node.args[0].value)
            nums = [n for c, v in values.items() if pattern.search(c) and (n := _number(v)) is not MISSING]
            if name == "count_of":
                return float(len(nums))
            if not nums:
                return MISSING
            return {"sum_of": sum(nums), "mean_of": sum(nums) / len(nums), "max_of": max(nums),
                    "min_of": min(nums)}[name]
        if name == "first":
            for arg in node.args:
                v = _eval(arg, values)
                if v is not MISSING:
                    return v
            return MISSING
        if name == "ifelse":
            test = _eval(node.args[0], values)
            if test is MISSING:
                return MISSING
            return _eval(node.args[1] if test else node.args[2], values)
        args = [_eval(a, values) for a in node.args]
        if any(a is MISSING for a in args):
            return MISSING
        if name == "round":
            return float(round(args[0], int(args[1]) if len(args) > 1 else 0))
        fn = {"abs": abs, "min": min, "max": max, "sqrt": math.sqrt, "exp": math.exp, "ln": math.log,
              "log10": math.log10}[name]
        return float(fn(*args))
    raise FormulaError(f"'{type(node).__name__}' isn't allowed in a formula")


def _tidy(x: float) -> float:
    return float(f"{x:.10g}")


def _differs(a: float, b: float) -> bool:
    return abs(a - b) > max(CHECK_ABSOLUTE, CHECK_RELATIVE * max(abs(a), abs(b)))


@dataclass
class FormulaOutcome:
    formula: Formula
    filled: List[str] = field(default_factory=list)                      # full_ids
    differing: List[Tuple[str, float, float]] = field(default_factory=list)   # (full_id, kept, calculated)
    failed: List[Tuple[str, str]] = field(default_factory=list)          # (full_id, why)


def apply_formulas(rows, formulas: List[dict]) -> List[FormulaOutcome]:
    """Fill each formula's column on the rows (see the module docstring); returns what each formula did."""
    from parameter_extractor.ingestion.flatten_to_template import row_to_template_dict, set_row_value
    from parameter_extractor.schemas.common import CONFIDENCE_ORDER
    from parameter_extractor.schemas.row_schema import CellSource
    outcomes = []
    for raw in formulas:
        f = Formula.from_dict(raw)
        outcome = FormulaOutcome(f)
        outcomes.append(outcome)
        try:
            tree = f.tree
        except FormulaError as e:
            outcome.failed.append(("", str(e)))
            continue
        inputs = f.inputs()
        for row in rows:
            record = row_to_template_dict(row)
            try:
                value = evaluate(tree, record)
            except (ZeroDivisionError, ValueError, OverflowError, TypeError) as e:
                outcome.failed.append((row.full_id, "division by zero" if isinstance(e, ZeroDivisionError) else str(e)))
                continue
            if value is MISSING:
                continue
            value = _tidy(float(value))
            existing = _number(record.get(f.column))
            if existing is not MISSING and f.if_present != "replace":
                if f.if_present == "check" and _differs(existing, value):
                    outcome.differing.append((row.full_id, existing, value))
                continue
            used = [c for c in inputs if _number(record.get(c)) is not MISSING]
            levels = [row.provenance[c].confidence for c in used
                      if c in row.provenance and row.provenance[c].confidence in CONFIDENCE_ORDER]
            shown = ", ".join(f"{c} = {record[c]:g}" if isinstance(record[c], (int, float)) else f"{c} = {record[c]}"
                              for c in used)
            set_row_value(row, f.column, value, CellSource(
                origin="calculated", source=f"formula {f.column} = {f.expression}" + (f" with {shown}" if shown else ""),
                confidence=min(levels, key=CONFIDENCE_ORDER.index) if levels else None))
            outcome.filled.append(row.full_id)
    return outcomes


def formula_flags(outcomes: List[FormulaOutcome]):
    """One flag per formula for what it calculated (derived_value), one for values that differ from the paper's
    (conflicting_values) and one for rows it couldn't calculate (not_calculated) -- grouped, never one per row."""
    from parameter_extractor.validation.plausibility_checks import Flag
    flags = []
    for o in outcomes:
        f = o.formula
        if o.filled:
            flags.append(Flag("derived_value", f"{f.column} calculated for {len(o.filled)} row(s) by the research "
                                               f"area's formula {f.column} = {f.expression}"
                                               + (f" ({f.description})" if f.description else "")
                                               + ". Hover a value to see the inputs used."))
        if o.differing:
            listed = "; ".join(f"row {r}: {kept:g} kept, {calc:g} calculated" for r, kept, calc in o.differing[:6])
            more = f"; ... ({len(o.differing) - 6} more)" if len(o.differing) > 6 else ""
            flags.append(Flag("conflicting_values", f"{f.column}: the paper's value differs from the formula "
                                                    f"{f.expression} for {len(o.differing)} row(s) ({listed}{more}). "
                                                    f"The paper's values were kept."))
        if o.failed:
            reasons = sorted({why for _r, why in o.failed})
            rows = [r for r, _w in o.failed if r]
            flags.append(Flag("not_calculated", f"{f.column} (formula {f.expression}) not calculated"
                                                + (f" for {len(rows)} row(s)" if rows else "") + f": {'; '.join(reasons)}."))
    return flags
