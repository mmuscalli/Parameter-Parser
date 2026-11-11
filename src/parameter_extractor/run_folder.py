"""
A finished run read back from its folder (W3, 2026-11-11): File > Open a results folder… shows an earlier run in the
results tabs as if it had just finished (data with hover provenance, things to check, summary, figures, tables,
equations). Nothing is asked of the model and nothing in the folder is changed.

Everything comes from the files a run writes: run_summary.json (settings, usage, figures, tables, unfound terms),
<paper>_extracted.csv (the data tab reads it directly), <paper>_observations.csv (provenance per cell),
plausibility_flags.json, new_variables.json, equations.json. Folders from older versions may lack some of these;
`load_result` then fills what it can and lists what was missing in `RunResult.opened_notes`.

A queue folder (queue_<stamp>/) holds one run folder per paper: `runs_in(folder)` lists them.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Dict, List, Optional

from parameter_extractor.errors import PipelineError
from parameter_extractor.ingestion.observations import QUOTE_IN_PAPER
from parameter_extractor.run_context import StageUsage
from parameter_extractor.schemas.row_schema import CellSource
from parameter_extractor.validation.plausibility_checks import Flag

SUMMARY = "run_summary.json"
_QUOTE_CHECK = {v: k for k, v in QUOTE_IN_PAPER.items()}       # 'yes' -> 'in text', ...


@dataclass
class SavedRow:
    """One dataset row as saved: what the results tabs need (its id, provenance per column, cited source)."""
    full_id: str
    set_id: str = ""
    sample_id: str = ""
    values: Dict[str, str] = field(default_factory=dict)
    provenance: Dict[str, CellSource] = field(default_factory=dict)
    original_data_reference: Optional[str] = None


def is_run_folder(folder: Path) -> bool:
    return (Path(folder) / SUMMARY).is_file()


def runs_in(folder: Path) -> List[Path]:
    """The run folders to show for a chosen folder: itself if it is one, else (a queue folder, or a results folder
    with several runs) the run folders directly inside it, sorted by name (a queue's papers are numbered)."""
    folder = Path(folder)
    if is_run_folder(folder):
        return [folder]
    return sorted(p for p in folder.iterdir() if p.is_dir() and is_run_folder(p)) if folder.is_dir() else []


def _json(path: Path, notes: List[str], what: str, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        notes.append(f"{what} ({path.name}) couldn't be read: {e}")
        return default


def _flag(d: dict) -> Flag:
    known = {f.name for f in fields(Flag)}
    return Flag(**{k: v for k, v in d.items() if k in known})


def _page(v: str):
    return int(v) if v.isdigit() else (v or None)


def _image(path: str, run_dir: Path, subfolder: str) -> str:
    """An image path saved in the summary, found again if the folder was moved or copied (paths are absolute)."""
    if not path or Path(path).is_file():
        return path
    moved = run_dir / subfolder / Path(path).name
    return str(moved) if moved.is_file() else ""


def _dataset_csv(run_dir: Path) -> Optional[Path]:
    found = sorted(p for p in run_dir.glob("*_extracted.csv") if not p.name.startswith("combined_"))
    return found[0] if found else None


def load_result(run_dir: Path):
    """A RunResult for a finished run folder. Raises PipelineError when it isn't one (no run_summary.json, or no
    dataset CSV -- e.g. a run that failed before writing it)."""
    from parameter_extractor.pipeline import RunResult
    from parameter_extractor.schemas.equations import EquationCandidate
    from parameter_extractor.schemas.variables import NewVariable

    run_dir = Path(run_dir)
    notes: List[str] = []
    if not is_run_folder(run_dir):
        raise PipelineError(f"{run_dir} isn't a results folder of this app (it has no {SUMMARY}).")
    summary = _json(run_dir / SUMMARY, notes, "the run summary", {})
    csv_path = _dataset_csv(run_dir)
    if csv_path is None:
        error = run_dir / "error.txt"
        why = (" The run stopped with an error: " + error.read_text().strip().splitlines()[0]) if error.is_file() else ""
        raise PipelineError(f"{run_dir.name} has no dataset (no *_extracted.csv): the run didn't finish.{why}")
    paper_id = csv_path.name[: -len("_extracted.csv")]

    rows: Dict[str, SavedRow] = {}
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            fid = r.get("full_id", "")
            rows[fid] = SavedRow(fid, r.get("set_id", ""), r.get("sample_id", ""), dict(r),
                                 original_data_reference=r.get("original_data_reference") or None)
    observations = run_dir / f"{paper_id}_observations.csv"
    if observations.is_file():
        with open(observations, newline="") as f:
            for o in csv.DictReader(f):
                row = rows.get(o.get("full_id", ""))
                if row is None or not (o.get("origin") or o.get("quote") or o.get("source")):
                    continue
                row.provenance[o["column"]] = CellSource(
                    origin=o.get("origin", ""), quote=o.get("quote", ""), source=o.get("source", ""),
                    confidence=o.get("confidence") or None, quote_check=_QUOTE_CHECK.get(o.get("quote_in_paper", "")),
                    page=_page(o.get("page", "")))
    else:
        notes.append("no observations file: hovering a value won't show where it came from")

    flags = _json(run_dir / "plausibility_flags.json", notes, "the things to check", {})
    paper_flags = [_flag(d) for d in flags.get("paper_level", [])]
    row_flags = {fid: [_flag(d) for d in fs] for fid, fs in flags.get("rows", {}).items()}

    known = {f.name for f in fields(StageUsage)}
    usage = [StageUsage(**{k: v for k, v in u.items() if k in known}) for u in summary.get("usage", [])]

    figures = []
    for fig in summary.get("figures", []):
        fig = dict(fig)
        for key in ("image", "annotated_image"):
            if key in fig:
                fig[key] = _image(fig[key], run_dir, "figures")
        figures.append(fig)
    tables = [dict(t, image=_image(t.get("image", ""), run_dir, "tables")) for t in summary.get("tables", [])]
    equations = []
    for e in _json(run_dir / "equations.json", notes, "the equations", []):
        try:
            eq = EquationCandidate.model_validate(e)
            if getattr(eq, "image", None):
                eq.image = _image(eq.image, run_dir, "equations")
            equations.append(eq)
        except ValueError:
            pass

    variables = _json(run_dir / "new_variables.json", notes, "the review of new variables", {})
    left_out = []
    for v in variables.get("left_out", []):
        try:
            left_out.append(NewVariable.model_validate(v))
        except ValueError:
            pass
    if "usage" not in summary:
        notes.append("the summary has no token usage (an older version's folder)")

    result = RunResult(paper_id=paper_id, run_dir=run_dir, csv_path=csv_path, rows=list(rows.values()),
                       paper_flags=paper_flags, row_flags=row_flags, usage=usage,
                       flags_path=run_dir / "plausibility_flags.json" if flags else None,
                       observations_path=observations if observations.is_file() else None,
                       figures=figures, tables=tables, equations=equations, new_variables=left_out,
                       accepted_variables=variables.get("accepted", []),
                       unfound_terms=summary.get("unfound_terms", []),
                       pack=(summary.get("config") or {}).get("pack", ""),
                       app_version=summary.get("app_version", ""), opened=True, opened_notes=notes)
    return result
