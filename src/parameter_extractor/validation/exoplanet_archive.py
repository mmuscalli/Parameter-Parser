"""
Check extracted exoplanet rows against the NASA Exoplanet Archive.

The archive keeps every published parameter set of a planet (table `ps`, one
row per planet and reference). The right one to compare with is the set whose
PLANETARY PARAMETER reference (pl_refname) is the paper being extracted (Mickey,
2026-10-20 -- not necessarily the default set, nor the discovery paper). It is
fetched from the archive's public TAP service (no key), compared column by
column, and the archive rows are saved in the run folder (archive_rows.json)
so the comparison can be replayed offline.

Planets are matched by name in the archive's style (Greek letters as "eps",
"omi", ...; case-insensitive), else -- for a planet the archive files under
another name (41 Lyn b = HD 81688 b) -- by orbital period among the archive's
planets from this paper. Only columns the archive took from this paper are
compared: st_* when its st_refname is the paper, sy_* likewise (usually Gaia
or TICv8, so not), disc_* likewise; the others are listed as from another
reference.

A value matches when it agrees to within the paper's rounding: 0.5% relative,
or half the last printed digit (archive zero-padding ignored), whichever is
larger. Text values match case-insensitively. Fails soft: no network -> a
note, never a failed run.
"""
from __future__ import annotations
import csv
import io
import json
import re
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional

TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
TIMEOUT_SEC = 30
REL_TOLERANCE = 0.005
SKIP = {"pl_name", "hostname", "pl_letter", "pl_refname", "st_refname", "sy_refname", "disc_refname"}
PERIOD_MATCH = 0.01                 # alias fallback: orbital periods within 1%
# column prefix -> the archive column naming the reference those values came from
REFERENCE_OF = {"st_": "st_refname", "sy_": "sy_refname", "disc_": "disc_refname"}
_GREEK = {"α": "alf", "β": "bet", "γ": "gam", "δ": "del", "ε": "eps", "ζ": "zet", "η": "eta", "θ": "tet",
          "ι": "iot", "κ": "kap", "λ": "lam", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "omi", "π": "pi",
          "ρ": "rho", "σ": "sig", "τ": "tau", "υ": "ups", "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "ome"}


def _strip_html(text) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(text or ""))).strip()


def archive_name(name: str) -> str:
    """A planet name as the archive writes it: 'ε Tau b' -> 'eps Tau b', 'o UMa b' -> 'omi UMa b'."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    name = "".join(_GREEK.get(ch, ch) for ch in name)
    return re.sub(r"^o(?= [A-Z][A-Za-z]{2}\b)", "omi", name)       # Latin 'o' for omicron, as in 'o UMa'


def _key(name: str) -> str:
    """Host case-insensitive, companion letter not: 'HD 5608 b' is the planet, 'HD 5608 B' a star."""
    host, _, letter = archive_name(name).rpartition(" ")
    return f"{host.lower()} {letter}" if host else letter.lower()


def _sql(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def fetch_parameter_sets(planet_names: List[str], reference: str = "") -> List[dict]:
    """Every published parameter set of these planets (archive table ps), and every
    parameter set from this reference (planets the archive names differently)."""
    names = ",".join(_sql(n) for n in sorted({archive_name(n) for n in planet_names} | set(planet_names)))
    query = f"select * from ps where pl_name in ({names})"
    if reference:
        query += f" or pl_refname like {_sql('%' + reference + '%')}"
    url = f"{TAP_URL}?{urllib.parse.urlencode({'query': query, 'format': 'csv'})}"
    req = urllib.request.Request(url, headers={"User-Agent": "ParameterExtractor"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def _number(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


ANGLES = {"pl_orblper", "pl_projobliq", "pl_trueobliq"}       # degrees, the same modulo 360


def _matches(extracted, archived, column: str = "") -> bool:
    a, b = _number(extracted), _number(archived)
    if a is None or b is None:
        return _strip_html(extracted).lower() == _strip_html(archived).lower()
    if column in ANGLES:
        a = b + ((a - b + 180) % 360 - 180)
    printed = str(archived).strip()
    digits = len(printed.split(".")[1].rstrip("0")) if "." in printed else 0
    return abs(a - b) <= max(REL_TOLERANCE * abs(b), 0.5 * 10 ** -digits, 1e-9)


def _same_reference(archive_ref: str, reference: str) -> bool:
    return _strip_html(archive_ref).lower() == reference.strip().lower()


def compare(records: List[dict], archive_rows: List[dict], reference: str) -> List[dict]:
    """Per extracted row: which archive parameter set it was compared with, and each
    column's outcome (match / differs / not extracted)."""
    report = []
    named = {_key(r.get("pl_name")) for r in records if r.get("pl_name")}
    from_paper = [a for a in archive_rows if _same_reference(a.get("pl_refname", ""), reference)
                  and _key(a.get("pl_name")) not in named]           # this paper's planets under other names
    for rec in records:
        name = rec.get("pl_name")
        if not name:
            continue
        sets = [a for a in archive_rows if _key(a.get("pl_name")) == _key(name)]
        entry = {"pl_name": name, "reference": reference}
        period = _number(rec.get("pl_orbper"))
        if not sets and period:
            alias = [a for a in from_paper if _number(a.get("pl_orbper"))
                     and abs(_number(a["pl_orbper"]) - period) <= PERIOD_MATCH * period]
            if len(alias) == 1:
                sets = [a for a in archive_rows if a.get("pl_name") == alias[0]["pl_name"]]
                entry["archive_name"] = alias[0]["pl_name"]
                entry["matched_by"] = "orbital period"
        if sets and sets[0]["pl_name"] != name:
            entry.setdefault("archive_name", sets[0]["pl_name"])
        chosen = next((a for a in sets if _same_reference(a.get("pl_refname", ""), reference)), None)
        entry["archive_references"] = sorted({_strip_html(a.get("pl_refname")) for a in sets})
        if chosen is None:
            entry["status"] = "no archive parameter set for this reference" if sets else "planet not in the archive"
            report.append(entry)
            continue
        entry["status"] = "compared"
        entry["default_flag"] = chosen.get("default_flag")
        matches, differs, missing, elsewhere = [], [], [], {}
        for column, archived in chosen.items():
            if column in SKIP or column.endswith(("str", "reflink")) or archived in ("", None):
                continue
            ref_col = next((c for prefix, c in REFERENCE_OF.items() if column.startswith(prefix)), None)
            if ref_col and chosen.get(ref_col) and not _same_reference(chosen[ref_col], reference):
                elsewhere.setdefault(_strip_html(chosen[ref_col]), []).append(column)
                continue
            extracted = rec.get(column)
            if extracted in (None, ""):
                if column.startswith(("pl_", "st_")) and not column.endswith("lim"):
                    missing.append(column)
                continue
            (matches if _matches(extracted, archived, column) else differs).append(
                {"column": column, "extracted": extracted, "archive": _number(archived) or _strip_html(archived)})
        entry.update(matches=[m["column"] for m in matches], differs=differs, not_extracted=missing,
                     from_other_references=elsewhere)
        report.append(entry)
    return report


def check(records: List[dict], reference: str, run_dir, fetch: Optional[Callable] = None) -> dict:
    """Fetch (or reuse run_dir/archive_rows.json), compare, write archive_validation.json.
    Returns {"report": [...], "error": "..."}."""
    from pathlib import Path
    run_dir = Path(run_dir)
    saved = run_dir / "archive_rows.json"
    names = [r["pl_name"] for r in records if r.get("pl_name")]
    if not names:
        return {"report": [], "error": "no planet names to look up"}
    try:
        if saved.is_file():
            archive_rows = json.loads(saved.read_text())
        else:
            archive_rows = (fetch or fetch_parameter_sets)(names, reference)
            saved.write_text(json.dumps(archive_rows, indent=1))
    except Exception as e:                     # network, HTTP, parsing: never fail the run
        return {"report": [], "error": f"the NASA Exoplanet Archive couldn't be reached ({type(e).__name__}: {e})"}
    report = compare(records, archive_rows, reference)
    (run_dir / "archive_validation.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return {"report": report, "error": ""}
