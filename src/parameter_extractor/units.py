"""
Units: parse quantities as papers print them ("1 cm3", "0.5 mol dm-3",
"45 min", "130 ºC", "1 × 10-3 M") and convert them to a column's unit.

Deliberately a small explicit table rather than a general units library: paper
notation needs custom normalisation anyway, and an explicit table makes every
conversion easy to audit. Anything not in the table is NOT converted (the
caller keeps the text and flags it) -- a wrong conversion would be worse than
none.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# canonical unit -> (dimension, factor to the dimension's base unit)
# bases: concentration mM, volume mL, time h, mass g, pressure bar, length nm,
#        flow mL/min, rate rpm, fraction %, temperature °C (offset units below)
_UNITS: Dict[str, Tuple[str, float]] = {
    "M": ("concentration", 1000.0), "mM": ("concentration", 1.0), "µM": ("concentration", 1e-3),
    "nM": ("concentration", 1e-6),
    "L": ("volume", 1000.0), "mL": ("volume", 1.0), "µL": ("volume", 1e-3), "m3": ("volume", 1e6),
    "s": ("time", 1 / 3600), "min": ("time", 1 / 60), "h": ("time", 1.0), "d": ("time", 24.0),
    "week": ("time", 168.0),
    "kg": ("mass", 1000.0), "g": ("mass", 1.0), "mg": ("mass", 1e-3), "µg": ("mass", 1e-6),
    "bar": ("pressure", 1.0), "mbar": ("pressure", 1e-3), "atm": ("pressure", 1.01325),
    "Pa": ("pressure", 1e-5), "kPa": ("pressure", 1e-2), "MPa": ("pressure", 10.0),
    "psi": ("pressure", 0.0689476), "Torr": ("pressure", 0.00133322),
    "nm": ("length", 1.0), "µm": ("length", 1e3), "mm": ("length", 1e6), "cm": ("length", 1e7),
    "mL/min": ("flow", 1.0), "µL/min": ("flow", 1e-3), "L/min": ("flow", 1000.0), "mL/h": ("flow", 1 / 60),
    "rpm": ("rate", 1.0),
    "%": ("fraction", 1.0),
    "°C": ("temperature", 1.0), "K": ("temperature", 1.0), "°F": ("temperature", 1.0),
}

# spellings seen in papers -> canonical unit (matched after normalise_unit_text)
_ALIASES = {
    "m": "M", "mol/l": "M", "moll-1": "M", "moldm-3": "M", "mol/dm3": "M", "mol·dm-3": "M", "molar": "M",
    "mm": "mM", "mmol/l": "mM", "mmoll-1": "mM", "mmoldm-3": "mM", "millimolar": "mM",
    "µm": "µM", "umol/l": "µM", "µmol/l": "µM", "µmoldm-3": "µM", "um": "µM",
    "nm": "nM", "nmol/l": "nM",
    "l": "L", "dm3": "L", "litre": "L", "liter": "L",
    "ml": "mL", "cm3": "mL", "cc": "mL", "millilitre": "mL", "milliliter": "mL",
    "µl": "µL", "ul": "µL", "mm3": "µL", "microlitre": "µL", "microliter": "µL",
    "s": "s", "sec": "s", "secs": "s", "second": "s", "seconds": "s",
    "min": "min", "mins": "min", "minute": "min", "minutes": "min",
    "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "d": "d", "day": "d", "days": "d", "week": "week", "weeks": "week",
    "kg": "kg", "g": "g", "mg": "mg", "µg": "µg", "ug": "µg",
    "bar": "bar", "mbar": "mbar", "atm": "atm", "pa": "Pa", "kpa": "kPa", "mpa": "MPa", "psi": "psi",
    "torr": "Torr", "mmhg": "Torr",
    "µm(length)": "µm", "cm": "cm",
    "ml/min": "mL/min", "mlmin-1": "mL/min", "cm3min-1": "mL/min", "cm3/min": "mL/min", "µl/min": "µL/min", "ulmin-1": "µL/min", "µlmin-1": "µL/min",
    "l/min": "L/min", "ml/h": "mL/h", "mlh-1": "mL/h",
    "rpm": "rpm", "r/min": "rpm",
    "%": "%", "percent": "%", "%rh": "%", "rh%": "%",
    "°c": "°C", "c": "°C", "degc": "°C", "oc": "°C", "celsius": "°C", "k": "K", "kelvin": "K",
    "°f": "°F", "f": "°F",
}

# column unit (observations.unit_for_column) -> canonical unit
_COLUMN_UNITS = {"mM": "mM", "°C": "°C", "h": "h", "s": "s", "min": "min", "bar": "bar", "mL": "mL",
                 "µL": "µL", "g": "g", "nm": "nm", "rpm": "rpm", "K": "K", "%": "%", "mL/min": "mL/min"}


def normalise_unit_text(text: str) -> str:
    t = text.strip()
    t = (t.replace("μ", "µ").replace("º", "°").replace("˚", "°").replace("−", "-").replace("–", "-")
          .replace("³", "3").replace("⁻", "-").replace("¹", "1").replace("·", ""))
    t = re.sub(r"\^", "", t)
    t = re.sub(r"\s+", "", t)
    return t


def canonical_unit(text: str) -> Optional[str]:
    """The canonical unit for a printed unit, or None if it isn't one we convert."""
    t = normalise_unit_text(text)
    if t in _UNITS:                      # already canonical, case-sensitive (M vs m, mM)
        return t
    low = t.lower()
    if t == "mM":
        return "mM"
    if t in ("µM", "uM"):
        return "µM"
    if t == "nM":
        return "nM"
    return _ALIASES.get(low)


_NUMBER = r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)"
_QUANTITY = re.compile(
    rf"^\s*(?P<num>{_NUMBER})\s*(?:(?:[x×*]|·)\s*10\s*(?:\^|e|E)?\s*(?P<exp>[-−–+]?\s*\d+))?\s*(?P<unit>.*?)\s*$")


def parse_quantity(text: str) -> Optional[Tuple[float, str]]:
    """'1 cm3' -> (1.0, 'mL'); '1 × 10-3 M' -> (0.001, 'M'). None for ranges ('1-4 h'),
    multiple quantities, or units not in the table."""
    if text is None:
        return None
    t = str(text).strip()
    if re.search(rf"{_NUMBER}\s*(?:-|–|to)\s*{_NUMBER}", t) and not re.search(r"10\s*[-−–]\s*\d", t):
        return None                                      # a range: no single value
    m = _QUANTITY.match(t)
    if not m:
        return None
    unit = canonical_unit(m.group("unit")) if m.group("unit") else None
    if unit is None:
        return None
    value = float(m.group("num").replace(",", "."))
    if m.group("exp"):
        value *= 10 ** int(re.sub(r"[\s−–]", lambda c: "-" if c.group() in "−–" else "", m.group("exp")))
    return value, unit


def convert(value: float, from_unit: str, to_unit: str) -> Optional[float]:
    """Convert between canonical units of the same dimension; None if incompatible."""
    if from_unit == to_unit:
        return value
    a, b = _UNITS.get(from_unit), _UNITS.get(to_unit)
    if a is None or b is None or a[0] != b[0]:
        return None
    if a[0] == "temperature":
        c = {"°C": value, "K": value - 273.15, "°F": (value - 32) * 5 / 9}[from_unit]
        return {"°C": c, "K": c + 273.15, "°F": c * 9 / 5 + 32}[to_unit]
    return value * a[1] / b[1]


@dataclass
class Conversion:
    value: float
    note: str            # e.g. "converted from '1 cm3'" ('' if no conversion was needed)


def to_column_unit(raw, unit: Optional[str], column_unit: str) -> Optional[Conversion]:
    """Convert a value (number + unit, or text like '45 min') into a column's unit
    (as given by observations.unit_for_column). None if it can't be done safely --
    then the caller keeps the original and flags it."""
    target = _COLUMN_UNITS.get(column_unit)
    if target is None:
        return None
    if isinstance(raw, (int, float)):
        source = canonical_unit(unit) if unit else None
        if source is None:
            return Conversion(float(raw), "") if not unit else None
        out = convert(float(raw), source, target)
        return None if out is None else Conversion(_tidy(out), "" if source == target
                                                   else f"converted from {raw:g} {unit}")
    
    parsed = parse_quantity(str(raw))
    if parsed is None:
        try:
            return Conversion(float(str(raw).strip()), "")     # a bare number: assume the column's unit
        except ValueError:
            return None
    value, source = parsed
    out = convert(value, source, target)
    if out is None:
        return None
    return Conversion(_tidy(out), f"read from '{raw}'" if source == target else f"converted from '{raw}'")


def _tidy(x: float) -> float:
    """Round away float noise (0.1 * 3 = 0.30000000000000004) without losing precision."""
    return float(f"{x:.10g}")
