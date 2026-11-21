"""Accuracy evaluation, November 2026: batch E1, exoplanet discovery papers (Mickey, 2026-11-20).

- Candidates: the discovery references in `../disc_papers_full.csv` (the Exoplanet Archive's reference links).
- Each reference's detection method and planet count from the archive (table pscomppars, one row per planet).
- A sample stratified by method (seed 20261120), only references with at most MAX_PLANETS planets (a catalogue
  paper costs several times a discovery paper; Teng 2023 stands in for those) that resolve on arXiv.
- For scoring: every archive parameter set (table ps) whose reference is the paper, saved as
  `E1/archive/<key>.json` -- the "hand standard" of the exoplanet batch.
- Teng 2023 and Nielsen 2019 are added from their PDFs.
Network: the archive's TAP service and arXiv / CrossRef lookups (free, spaced as the app spaces them).

Usage: PARAMETER_EXTRACTOR_NO_KEYCHAIN=1 python make_exoplanet_subset.py
"""
import csv
import html
import io
import json
import random
import re
import shutil
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from parameter_extractor.ingestion import arxiv_source  # noqa: E402
from parameter_extractor.validation.exoplanet_archive import TAP_URL  # noqa: E402

ROOT = HERE.parents[2]
OUT = ROOT / "Paper Files/Accuracy Test 2026-11/E1"
SEED, MAX_PLANETS = 20261120, 6
QUOTA = {"Transit": 12, "Radial Velocity": 10, "Imaging": 4, "Microlensing": 4}
PDFS = {  # key: (folder, bibcode, method), read from their first pages
    "Teng2023": (ROOT / "Paper Files/Paper Lists/Teng2023", "2023PASJ...75.1030T", "catalogue"),
    "Nielsen2019": (ROOT / "Paper Files/Paper Lists/Nielsen2019", "2019A&A...623A.100N", "Transit"),
}


def tap(query: str) -> list:
    url = f"{TAP_URL}?{urllib.parse.urlencode({'query': query, 'format': 'csv'})}"
    req = urllib.request.Request(url, headers={"User-Agent": "ParameterExtractor-eval"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return list(csv.DictReader(io.StringIO(resp.read().decode("utf-8"))))


def bibcode(ref_html: str) -> str:
    ref = arxiv_source.identifier_in_cell(ref_html)
    return str(ref) if ref else ""


def label(ref_html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(ref_html))).strip()


def fetch_archive(chosen: dict) -> None:
    """Every ps parameter set whose reference is the paper -> E1/archive/<key>.json (the archive writes a bibcode's
    '&' as '%26' in some links, so both spellings are asked for)."""
    (OUT / "archive").mkdir(parents=True, exist_ok=True)
    for key, c in chosen.items():
        bib = c["bibcode"]
        likes = " or ".join(f"pl_refname like '%{b}%'" for b in {bib, bib.replace("&", "%26")})
        rows = tap(f"select * from ps where {likes}")
        (OUT / "archive" / f"{key}.json").write_text(json.dumps(rows, indent=0))
        c["archive_sets"] = len(rows)


def main() -> None:
    cells = [l for l in (ROOT / "disc_papers_full.csv").read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    wanted = {bibcode(c): c for c in cells if bibcode(c)}
    planets = tap("select pl_name, discoverymethod, disc_refname, disc_year from pscomppars")
    by_ref = defaultdict(list)
    for p in planets:
        b = bibcode(p["disc_refname"])
        if b in wanted:
            by_ref[b].append(p)
    print(f"{len(wanted)} references in the list, {len(by_ref)} found in pscomppars")
    strata = defaultdict(list)
    for b, ps in by_ref.items():
        methods = Counter(p["discoverymethod"] for p in ps)
        method = methods.most_common(1)[0][0]
        if len(ps) <= MAX_PLANETS and method in QUOTA and int(ps[0]["disc_year"] or 0) >= 2008:
            strata[method].append(b)
    rng = random.Random(SEED)
    chosen = {}
    for method, n in QUOTA.items():
        pool = sorted(strata[method])
        rng.shuffle(pool)
        got = 0
        for b in pool:
            if got == n:
                break
            try:
                rec = arxiv_source.resolve(arxiv_source.identifier_in_cell(wanted[b]))
            except Exception as e:                       # not on arXiv, or the lookup failed: take the next one
                print(f"  skip {b}: {type(e).__name__}: {e}"[:160])
                continue
            ascii_label = unicodedata.normalize("NFKD", label(wanted[b])).encode("ascii", "ignore").decode()
            key = re.sub(r"[^A-Za-z0-9]+", "", ascii_label.replace("et al.", "")) or b
            chosen[key] = {"bibcode": b, "reference": label(wanted[b]), "arxiv": rec.arxiv_id, "method": method,
                           "planets": sorted(p["pl_name"] for p in by_ref[b]), "cell": wanted[b]}
            got += 1
            print(f"  {method:16} {key:28} arXiv:{rec.arxiv_id}  {len(by_ref[b])} planet(s)")
        print(f"{method}: {got} of {n} (pool {len(pool)})")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "archive").mkdir(exist_ok=True)
    for key, (folder, bib, method) in PDFS.items():
        pdf = next(p for p in folder.glob("*.pdf"))
        (OUT / key).mkdir(exist_ok=True)
        if not (OUT / key / f"{key}.pdf").exists():
            shutil.copy2(pdf, OUT / key / f"{key}.pdf")
        chosen[key] = {"pdf": str(OUT / key / f"{key}.pdf"), "source": str(pdf), "bibcode": bib, "method": method}
    fetch_archive(chosen)
    # the queue list: arXiv ids for the sampled papers (read from arXiv as a user's list would be), PDFs for the two
    lines = [f"arXiv:{c['arxiv']}" if "arxiv" in c else c["pdf"] for c in chosen.values()]
    (OUT / "papers.txt").write_text("\n".join(lines) + "\n")
    f = HERE / "batches.json"
    batches = json.loads(f.read_text()) if f.is_file() else {}
    batches["E1"] = chosen
    f.write_text(json.dumps(batches, indent=1, ensure_ascii=False))
    print(f"E1: {len(chosen)} papers -> {OUT}")


if __name__ == "__main__":
    main()
