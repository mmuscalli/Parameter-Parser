"""
Offline tests for papers read from arXiv (ingestion/arxiv_source.py, html_text.py, paper_source.py):
identifiers, the API's Atom feed, DOI -> arXiv via CrossRef, ADS bibcodes, the HTML -> text
conversion (tables as rows, exact LaTeX values, no bibliography), and a whole run of nielsen2019
from its arXiv ID, replaying the model's recorded answers. A stand-in for the network; no API calls.

Run with: python tests/test_arxiv_source.py
"""
import gzip
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client, errors, packs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.ingestion import arxiv_source as ax
from parameter_extractor.ingestion.html_text import html_to_text
from parameter_extractor.paper_source import is_identifier, resolve_paper, run_name
from parameter_extractor.validation import exoplanet_archive
from test_pipeline_offline import make_replay

FIX = ROOT / "tests" / "fixtures" / "arxiv_nielsen2019"
FEED = (FIX / "api_1811.01882.xml").read_bytes()
HTML = gzip.decompress((FIX / "1811.01882v4.html.gz").read_bytes())
NIELSEN_PDF = ROOT.parent / "Paper Files" / "Paper Lists" / "Nielsen2019" / "nielsen2019.pdf"
EMPTY_FEED = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def fake_get(calls=None, crossref=None):
    def get(url, params=None, headers=None, arxiv=True):
        if calls is not None:
            calls.append((url, params))
        if url == ax.API_URL:
            q = (params or {}).get("search_query", "")
            if (params or {}).get("id_list", "").startswith("1811.01882") or "HD1397" in q or "Jovian" in q:
                return FEED
            return EMPTY_FEED
        if url.startswith("https://arxiv.org/html/1811.01882"):
            return HTML
        if url.startswith("https://api.crossref.org/"):
            return json.dumps({"message": crossref or {}}).encode()
        raise AssertionError(f"unexpected request {url} {params}")
    return get


def test_identifiers():
    cases = {"2308.05343": ("arxiv", "2308.05343"), "arXiv:1811.01882v4": ("arxiv", "1811.01882v4"),
             "https://arxiv.org/pdf/2601.10450v1": ("arxiv", "2601.10450v1"),
             "astro-ph/0601001": ("arxiv", "astro-ph/0601001"),
             "10.1093/pasj/psad056": ("doi", "10.1093/pasj/psad056"),
             "https://doi.org/10.1051/0004-6361/201834577.": ("doi", "10.1051/0004-6361/201834577"),
             "2023PASJ...75.1030T": ("bibcode", "2023PASJ...75.1030T"),
             "2023arXiv230805343T": ("bibcode", "2023arXiv230805343T")}
    for text, expected in cases.items():
        found = ax.parse_identifier(text)
        assert found and (found.kind, found.value) == expected, (text, found)
    assert ax.parse_identifier("teng2023") is None and ax.parse_identifier("") is None
    assert is_identifier("10.1093/pasj/psad056") and not is_identifier(Path("teng2023.pdf"))
    assert not is_identifier("/papers/teng2023.pdf")
    assert run_name("10.1093/pasj/psad056") == "doi_10.1093_pasj_psad056"
    assert run_name("arXiv:2308.05343v1") == "arXiv_2308.05343v1" and run_name(Path("x/teng2023.pdf")) == "teng2023"
    # in a paper's first pages: arXiv's margin stamp, else a DOI
    assert str(ax.identifier_in_text("arXiv:1811.01882v4 [astro-ph.EP] 20 Feb 2019")) == "arXiv:1811.01882v4"
    assert str(ax.identifier_in_text("https://doi.org/10.1093/pasj/psad056 Advance")) == "DOI 10.1093/pasj/psad056"


def test_feed_and_lookups():
    [r] = ax.parse_feed(FEED)
    assert (r.arxiv_id, r.version, r.doi, r.year) == ("1811.01882", "v4", "10.1051/0004-6361/201834577", 2019)
    assert r.authors[0] == "L. D. Nielsen" and r.journal_ref.startswith("A&A 623")
    with patch.object(ax, "_get", fake_get()):
        assert ax.resolve("1811.01882v2").version == "v2"            # the version asked for
        # a DOI arXiv doesn't list -> CrossRef title + first author -> title search, close match only
        crossref = {"title": ["A Jovian planet in an eccentric 11.5 day orbit around HD 1397 discovered by TESS"],
                    "author": [{"family": "Nielsen"}]}
        with patch.object(ax, "_get", fake_get(crossref=crossref)):
            found = ax.by_doi("10.9999/not-on-arxiv")
            assert found.arxiv_id == "1811.01882"
        far = {"title": ["Something else entirely about Jovian planets"], "author": [{"family": "Nielsen"}]}
        with patch.object(ax, "_get", fake_get(crossref=far)):
            try:
                ax.by_doi("10.9999/other")
            except errors.PaperSourceError as e:
                assert "isn't on arXiv" in str(e)
            else:
                raise AssertionError("a poor title match must not be accepted")
        assert ax.resolve("2018arXiv181101882N").arxiv_id == "1811.01882"   # an arXiv-style bibcode
        try:
            ax.resolve("2019A&A...623A.100N")
        except errors.PaperSourceError as e:
            assert "without an ADS token" in str(e)          # tried CrossRef: nothing matched
        else:
            raise AssertionError("a journal bibcode needs an ADS token")


def test_html_to_text():
    text = html_to_text(HTML.decode())
    assert "EXOFASTv2" in text and "Gaussian priors" in text
    assert "References" not in text[-3000:] and "Eastman, J." not in text           # bibliography dropped
    rows = [line for line in text.splitlines() if " | " in line]
    assert len(rows) > 40                                                            # tables as rows
    assert any("_{-" in line and "^{+" in line for line in rows)                      # exact LaTeX values
    tiny = html_to_text('<div class="ltx_document"><span class="ltx_tabular"><span class="ltx_tr">'
                        '<span class="ltx_td">75 Cet</span><span class="ltx_td"><math alttext="0.10_{-0.05}^{+0.08}">'
                        '<mn>0.10</mn></math></span></span></span><section class="ltx_bibliography">X</section></div>')
    assert tiny.strip() == "75 Cet | $0.10_{-0.05}^{+0.08}$"


def test_a_local_pdf_read_from_arxiv_when_asked():
    if not NIELSEN_PDF.is_file():
        print(f"SKIP: needs {NIELSEN_PDF}"); return
    with tempfile.TemporaryDirectory() as tmp, patch.object(ax, "_get", fake_get()):
        plain = resolve_paper(NIELSEN_PDF, Path(tmp))
        assert plain.pdf == NIELSEN_PDF and not plain.text                    # option off: the PDF
        source = resolve_paper(NIELSEN_PDF, Path(tmp), prefer_arxiv=True)
        assert source.from_arxiv_text and source.record.versioned_id == "1811.01882v4"   # margin stamp
        assert "a preprint" in source.label and (Path(tmp) / "arxiv.html").is_file()
    def offline(*a, **k):
        raise errors.PaperSourceError("Couldn't reach arXiv (offline).")
    with tempfile.TemporaryDirectory() as tmp, patch.object(ax, "_get", offline):
        source = resolve_paper(NIELSEN_PDF, Path(tmp), prefer_arxiv=True)       # falls back, says why
        assert source.pdf == NIELSEN_PDF and "The PDF was read" in source.notes[0]


def test_a_paper_given_by_arxiv_id_runs_end_to_end():
    """nielsen2019 from 'arXiv:1811.01882': text from the HTML, metadata from the arXiv record (no
    metadata call), no page numbers, a preprint flag -- and the archive check still matches."""
    saved = json.loads((FIX / "archive_rows.json").read_text())
    try:
        with tempfile.TemporaryDirectory() as tmp, patch.object(ax, "_get", fake_get()), \
                patch.object(api_client, "_send", make_replay(FIX)), \
                patch.object(exoplanet_archive, "fetch_parameter_sets", lambda names, ref: saved):
            from parameter_extractor.pipeline import run_pipeline
            result = run_pipeline("arXiv:1811.01882", RunConfig.from_settings(
                api_key="x", output_dir=Path(tmp), pack="exoplanets", online_checks=True))
            assert result.run_dir.name.startswith("arXiv_1811.01882_")
            assert [u.stage for u in result.usage if u.stage == "metadata"] == []     # no metadata call
            source = json.loads((result.run_dir / "source.json").read_text())
            assert source["read_from"].startswith("arXiv:1811.01882v4 full text")
            summary = json.loads((result.run_dir / "run_summary.json").read_text())
            assert summary["read_from"] == source["read_from"] and summary["config"]["ads_token"] == ""
            [row] = result.rows
            assert row.paper_title.startswith("A Jovian planet") and row.year_published == 2019
            assert row.journal_published == "A&A"
            import csv as _csv
            written = next(_csv.DictReader(open(result.csv_path)))
            assert written["paper_arxiv_id"] == "1811.01882v4" and written["paper_title"].startswith("A Jovian")
            assert all(src.page is None for src in row.provenance.values())             # no pages in HTML
            flag = next(f for f in result.paper_flags if f.kind == "paper_source")
            assert "version v4" in flag.message and "A&A 623, A100 (2019)" in flag.message
            report = json.loads((result.run_dir / "archive_validation.json").read_text())
            assert len(report[0]["matches"]) >= 110 and not report[0]["differs"]
    finally:
        packs.activate("prebiotic_chemistry")



def test_exoplanet_archive_reference_links():
    """Mickey's list (2026-10-24): the Exoplanet Archive's pl_refname cells -- HTML links to ADS
    abstracts (one with the '&' URL-encoded as %26, labels with &amp;) -- are read as bibcodes with
    their labels; journal bibcodes resolve without an ADS token: volume + page -> CrossRef -> DOI."""
    from parameter_extractor.focused_search import read_paper_list
    items = read_paper_list(ROOT / "tests" / "fixtures" / "archive_refnames.csv")
    assert [str(i) for i in items] == ["2020A&A...644A...1T", "2018PASJ...70...59T", "2022MNRAS.512..583G",
                                       "2024MNRAS.527.3183M", "2013A&A...555A..87M"]       # the header '0' skipped
    assert [i.label for i in items][3:] == ["Michel & Mugrauer 2024", "Mitchell et al. 2013"]
    assert [i.first_author for i in items] == ["Tala Pinto", "Takarada", "Gaidos", "Michel", "Mitchell"]
    assert str(ax.identifier_in_cell("see https://arxiv.org/abs/2308.05343v1")) == "arXiv:2308.05343v1"
    assert str(ax.identifier_in_cell("https://doi.org/10.1093/pasj/psad056")) == "10.1093/pasj/psad056"
    assert ax.identifier_in_cell("Teng et al. 2023") is None
    b = ax.Bibcode.parse("2020A&A...644A...1T")
    assert (b.year, b.journal, b.volume, b.page) == (2020, "A&A", "644", "A1")
    assert (ax.Bibcode.parse("2013A&A...553L...5D").page, ax.Bibcode.parse("2022NatAs...6..751C").volume) == ("L5", "6")
    assert ax.Bibcode.parse("2013ApJ...774...55B").page == "55" and ax.Bibcode.parse("2013ApJ...774L..55B").journal == "ApJL"
    items_found = [{"DOI": "10.1051/0004-6361:20078819", "volume": "484", "page": "17-28"},
                   {"DOI": "10.1051/0004-6361/202038285", "volume": "644", "article-number": "A1"}]
    seen = []
    def get(url, params=None, headers=None, arxiv=True):
        seen.append(params)
        return json.dumps({"message": {"items": items_found}}).encode()
    with patch.object(ax, "_get", get):
        assert ax.doi_from_bibcode("2020A&A...644A...1T", "Tala Pinto") == "10.1051/0004-6361/202038285"
        assert "issn:0004-6361" in seen[0]["filter"] and seen[0]["query.author"] == "Tala Pinto"
        try:
            ax.doi_from_bibcode("2020A&A...645A...1T")
        except errors.PaperSourceError as e:
            assert "no matching article" in str(e) and "ADS token" in str(e)
        else:
            raise AssertionError("a volume that doesn't match must not be accepted")


def test_title_search_tolerates_spelling():
    """Moutou 2026: the journal's 'Characterising' vs the preprint's 'Characterizing' -- a query with
    other title words still finds it; the close-title rule still decides."""
    preprint = ax.ArxivRecord("2510.11523", "v1", "Characterizing planetary systems with SPIRou: questions about "
                              "the magnetic cycle of 55 Cnc A and two new planets around B")
    queries = []
    def fake_query(q, max_results=5):
        queries.append(q)
        return [preprint] if "Characterising" not in q else []
    with patch.object(ax, "query", fake_query):
        found = ax.by_title("Characterising planetary systems with SPIRou: Questions about the magnetic cycle of "
                            "55 Cnc A and two new planets around B", "Moutou")
    assert found is preprint and queries[0].startswith("au:Moutou")

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All arXiv source tests passed.")
