"""
Corrections and checked marks (W2, 2026-11-11): the reviewer finishes the review in the app.

- A **correction** changes one value of a run's dataset: corrections.json in the run folder keeps, per cell, the row,
  the column, the value as extracted, the corrected value, when, and an optional note. The files follow at once:
  <paper>_extracted.csv gets the corrected value; <paper>_observations.csv keeps the extracted value in its own
  column (`extracted_value`) and marks the line (`corrected`); a queue's combined CSV files are updated too. A
  reverted cell gets its extracted value back and leaves corrections.json. A rebuild or resume of the run carries
  the corrections over (pipeline.finish).
- A **checked mark** on an entry of "Things to check" is the reviewer's own state: flags_checked.json holds the keys
  (`flag_key`) of the checked ones. Nothing is dropped from any file.

These are the reviewer's corrections, not a curated answer set: nothing here touches gold-standard validation.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CORRECTIONS_FILE = "corrections.json"
CHECKED_FILE = "flags_checked.json"
EXTRACTED_COLUMN = "extracted_value"          # observations CSV: the value as extracted, when corrected
CORRECTED_COLUMN = "corrected"                # observations CSV: 'yes' (+ the note)
FIXED_COLUMNS = {"entry_number", "full_id", "set_id", "sample_id"}   # row identity: not correctable


@dataclass
class Correction:
    full_id: str
    column: str
    extracted: str            # the value as extracted ('' = the cell was empty)
    value: str                # the corrected value, as stored in the dataset
    time: str = ""
    note: str = ""


Key = Tuple[str, str]


# ---- corrections.json ----------------------------------------------------------------------------------------------

def load(run_dir: Path) -> Dict[Key, Correction]:
    path = Path(run_dir) / CORRECTIONS_FILE
    try:
        data = json.loads(path.read_text()) if path.is_file() else []
    except (OSError, ValueError):
        return {}
    out = {}
    for d in data:
        try:
            c = Correction(**{k: d[k] for k in Correction.__dataclass_fields__ if k in d})
        except TypeError:
            continue
        out[(c.full_id, c.column)] = c
    return out


def _save(run_dir: Path, corrections: Dict[Key, Correction]) -> None:
    path = Path(run_dir) / CORRECTIONS_FILE
    if not corrections:
        if path.is_file():
            path.unlink()
        return
    path.write_text(json.dumps([asdict(c) for c in corrections.values()], indent=2, ensure_ascii=False))


def correct(run_dir: Path, full_id: str, column: str, extracted: str, value: str, note: Optional[str] = None) -> \
        Optional[Correction]:
    """Record a correction and update the files. `extracted` is the value shown before (the first correction of a cell
    keeps the value as extracted). Correcting back to the extracted value reverts. Returns the correction (None when
    reverted)."""
    if column in FIXED_COLUMNS:
        raise ValueError(f"{column} identifies the row and can't be corrected")
    corrections = load(run_dir)
    old = corrections.get((full_id, column))
    original = old.extracted if old else extracted
    if str(value) == str(original):
        return revert(run_dir, full_id, column)
    c = Correction(full_id, column, original, str(value), datetime.now().isoformat(timespec="seconds"),
                   (note if note is not None else (old.note if old else "")))
    corrections[(full_id, column)] = c
    _save(run_dir, corrections)
    _write_cell(Path(run_dir), c, corrected=True)
    return c


def correct_many(run_dir: Path, items: List[Tuple[str, str, str, str]], note: Optional[str] = None) -> None:
    """Several corrections at once -- (row, column, value shown before, new value) -- with each file written once
    (the Flagged values window's "Change selected values" and "Replace whole column with value")."""
    corrections = load(run_dir)
    changes = []
    for full_id, column, extracted, value in items:
        if column in FIXED_COLUMNS:
            raise ValueError(f"{column} identifies the row and can't be corrected")
        old = corrections.get((full_id, column))
        original = old.extracted if old else extracted
        if str(value) == str(original):
            if corrections.pop((full_id, column), None) is not None:
                changes.append((old, False))
            continue
        c = Correction(full_id, column, original, str(value), datetime.now().isoformat(timespec="seconds"),
                       note if note is not None else (old.note if old else ""))
        corrections[(full_id, column)] = c
        changes.append((c, True))
    _save(run_dir, corrections)
    _write_changes(Path(run_dir), changes)


def restore(run_dir: Path, states: List[Tuple[str, str, Optional[Correction]]]) -> None:
    """Put cells back as they were (undo): each (row, column, its correction then -- None = as extracted)."""
    corrections = load(run_dir)
    changes = []
    for full_id, column, before in states:
        now = corrections.pop((full_id, column), None)
        if before is not None:
            corrections[(full_id, column)] = before
            changes.append((before, True))
        elif now is not None:
            changes.append((now, False))
    _save(run_dir, corrections)
    _write_changes(Path(run_dir), changes)


def revert(run_dir: Path, full_id: str, column: str) -> None:
    corrections = load(run_dir)
    c = corrections.pop((full_id, column), None)
    if c is None:
        return None
    _save(run_dir, corrections)
    _write_cell(Path(run_dir), c, corrected=False)
    return None


def set_note(run_dir: Path, full_id: str, column: str, note: str) -> None:
    corrections = load(run_dir)
    c = corrections.get((full_id, column))
    if c is not None:
        c.note = note
        _save(run_dir, corrections)
        _write_cell(Path(run_dir), c, corrected=True)


def carry_over(old_dir: Path, new_dir: Path) -> List[Correction]:
    """A rebuilt / resumed run: the corrections (and checked marks) of the earlier folder, applied to the new files
    where their row and column still exist. Returns the ones applied."""
    applied = []
    header = _dataset_header(new_dir)
    rows = _dataset_ids(new_dir)
    kept = {}
    for key, c in load(old_dir).items():
        if c.full_id in rows and (c.column in header or not c.extracted):
            kept[key] = c
    if kept:
        _save(new_dir, kept)
        _write_cells(Path(new_dir), list(kept.values()), corrected=True)    # each file read and written once
        applied += kept.values()
    marks = Path(old_dir) / CHECKED_FILE
    if marks.is_file():
        (Path(new_dir) / CHECKED_FILE).write_text(marks.read_text())
    return applied


# ---- the files -------------------------------------------------------------------------------------------------------

def _dataset_csv(run_dir: Path) -> Optional[Path]:
    found = sorted(p for p in Path(run_dir).glob("*_extracted.csv") if not p.name.startswith("combined_"))
    return found[0] if found else None


def _dataset_header(run_dir: Path) -> List[str]:
    path = _dataset_csv(run_dir)
    if path is None:
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f), [])


def _dataset_ids(run_dir: Path) -> set:
    path = _dataset_csv(run_dir)
    if path is None:
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        return {r.get("full_id", "") for r in csv.DictReader(f)}


def _rewrite(path: Path, change) -> None:
    """Read a CSV, let `change(header, rows)` edit it in place, write it back (same column order)."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    header = change(header, rows) or header
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _wide(c: Correction, corrected: bool):
    def change(header, rows):
        if c.column not in header:
            header = header + [c.column]
        for r in rows:
            if r.get("full_id") == c.full_id:
                r[c.column] = c.value if corrected else c.extracted
        return header
    return change


def _long(c: Correction, corrected: bool):
    def change(header, rows):
        for col in (EXTRACTED_COLUMN, CORRECTED_COLUMN):
            if col not in header:
                header = header + [col]
        line = next((r for r in rows if r.get("full_id") == c.full_id and r.get("column") == c.column), None)
        if corrected:
            if line is None:                              # a value the extraction left empty
                from parameter_extractor.ingestion.observations import unit_for_column
                ids = next((r for r in rows if r.get("full_id") == c.full_id), {})
                line = {"full_id": c.full_id, "set_id": ids.get("set_id", ""), "sample_id": ids.get("sample_id", ""),
                        "column": c.column, "unit": unit_for_column(c.column), "origin": "corrected"}
                rows.append(line)
            line["value"] = c.value
            line[EXTRACTED_COLUMN] = c.extracted
            line[CORRECTED_COLUMN] = "yes" + (f": {c.note}" if c.note else "")
        elif line is not None:
            if not c.extracted and line.get("origin") == "corrected":
                rows.remove(line)
            else:
                line["value"] = c.extracted
                line[EXTRACTED_COLUMN] = ""
                line[CORRECTED_COLUMN] = ""
        return header
    return change


def _write_cell(run_dir: Path, c: Correction, corrected: bool) -> None:
    _write_cells(run_dir, [c], corrected)


def _all(changes):
    def change(header, rows):
        for ch in changes:
            header = ch(header, rows) or header
        return header
    return change


def _write_cells(run_dir: Path, cs: List[Correction], corrected: bool) -> None:
    _write_changes(run_dir, [(c, corrected) for c in cs])


def _write_changes(run_dir: Path, changes: List[Tuple[Correction, bool]]) -> None:
    """Corrections (True) and reverts (False) into the run's files (and a queue's combined files), each file read and
    written once."""
    wide = _dataset_csv(run_dir)
    if wide is None or not changes:
        return
    _rewrite(wide, _all([_wide(c, on) for c, on in changes]))
    long = wide.with_name(wide.name.replace("_extracted.csv", "_observations.csv"))
    if long.is_file():
        _rewrite(long, _all([_long(c, on) for c, on in changes]))
    queue = run_dir.parent                                # a paper of a queue: the combined files too
    if (queue / "combined_extracted.csv").is_file():
        _rewrite(queue / "combined_extracted.csv", _all([_wide(c, on) for c, on in changes]))
        if (queue / "combined_observations.csv").is_file():
            _rewrite(queue / "combined_observations.csv", _all([_long(c, on) for c, on in changes]))


# ---- checking a value against its column ----------------------------------------------------------------------------

def stored_value(column: str, text: str, registry=None) -> Tuple[str, str]:
    """(what the dataset stores, problem) for a value typed by the reviewer: checked against the column's data type
    (value_types) and, for a number with a unit, put in the column's unit ('45 min' in a _hr column -> 0.75)."""
    from parameter_extractor import units, value_types
    from parameter_extractor.ingestion.observations import unit_for_column
    text = (text or "").strip()
    if not text:
        return "", ""
    kind = value_types.column_type(column, registry)
    unit = unit_for_column(column)
    if kind in ("number", "integer") and unit and unit != "pH":
        conv = units.to_column_unit(text, None, unit)
        if conv is None and units.parse_range(text) is None:
            return text, f"'{text}' isn't a number in {unit} (or a unit that converts to it)"
        if conv is not None:
            text = f"{conv.value:g}"
    value, problem = value_types.coerce(text, kind)
    if problem:
        return text, problem
    if kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(float(value)), ""                 # as the dataset writes numbers ('91.0', '0.005')
    return str(value), ""


# ---- checked marks ---------------------------------------------------------------------------------------------------

def flag_key(flag, row_id: str = "") -> str:
    """A stable name for one entry of "Things to check" (the same after a rebuild that gives the same flag)."""
    return hashlib.sha1(f"{row_id}|{flag.kind}|{flag.message}".encode()).hexdigest()[:16]


def load_checked(run_dir: Path) -> set:
    path = Path(run_dir) / CHECKED_FILE
    try:
        return set(json.loads(path.read_text())) if path.is_file() else set()
    except (OSError, ValueError):
        return set()


def save_checked(run_dir: Path, keys: set) -> None:
    path = Path(run_dir) / CHECKED_FILE
    if keys:
        path.write_text(json.dumps(sorted(keys), indent=1))
    elif path.is_file():
        path.unlink()
