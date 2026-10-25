"""
Offline tests for faster searches over many papers (2026-10-25, after Mickey's 1,389-paper run took
14 h: one-request batches waiting ~2.5 min each, 4 at a time): requests pooled into shared Message
Batches (api_client.BatchCollector), identifiers looked up in batches and cached, full texts cached,
patient retries that slow down when arXiv is busy, long-page bibcodes, retrying failed papers.
Stand-ins for the network and the API; no API calls.

Run with: python tests/test_batch_speed.py
"""
import json
import sys
import tempfile
import threading
import time
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client, errors, packs
from parameter_extractor import focused_search as fs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.ingestion import arxiv_source as ax
from test_arxiv_source import FEED, HTML, fake_get


class FakeBatches:
    """messages.batches for many requests: every request answered with `answer(params)`."""
    def __init__(self, answer):
        self.answer, self.created, self.checks = answer, [], {}

    def create(self, requests):
        bid = f"msgbatch_{len(self.created)}"
        self.created.append(requests)
        return SimpleNamespace(id=bid, processing_status="in_progress")

    def retrieve(self, bid):
        self.checks[bid] = self.checks.get(bid, 0) + 1
        return SimpleNamespace(id=bid, processing_status="ended")

    def results(self, bid):
        requests = self.created[int(bid.split("_")[1])]
        for r in requests:
            text = json.dumps(self.answer(r["params"]))
            message = SimpleNamespace(id=f"msg_{r['custom_id']}", stop_reason="end_turn", stop_details=None,
                                      content=[SimpleNamespace(type="text", text=text)],
                                      usage=SimpleNamespace(input_tokens=1000, output_tokens=50))
            yield SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(type="succeeded", message=message))

    def cancel(self, bid):
        pass


def test_requests_from_many_threads_share_a_batch():
    batches = FakeBatches(lambda params: {"n": params["messages"][0]["content"]})
    client = SimpleNamespace(messages=SimpleNamespace(batches=batches))
    collector = api_client.BatchCollector(client, quiet_sec=0.3, max_wait_sec=5)
    out = {}
    with patch.object(api_client, "BATCH_POLL_SECONDS", (0.01, 0.01)):
        def ask(i):
            message, bid = collector.submit({"messages": [{"content": f"paper {i}"}]}, "focused_search")
            out[i] = (json.loads(message.content[0].text)["n"], bid)
        threads = [threading.Thread(target=ask, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
    assert len(batches.created) == 1 and len(batches.created[0]) == 6            # one batch, six requests
    assert all(out[i] == (f"paper {i}", "msgbatch_0") for i in range(6))          # each gets its own answer
    assert collector.batches == ["msgbatch_0"]


def test_lookups_batched_and_cached():
    asked = []
    def fake_query(search_query="", id_list="", max_results=5):
        asked.append(search_query or id_list)
        if id_list:
            return ax.parse_feed(FEED)
        found = []
        for d in [f"10.1234/x{i}" for i in range(25)]:
            if f'"{d}"' in search_query and not d.endswith("7"):        # x7 and x17: not listed on arXiv
                found.append(ax.ArxivRecord(d.replace("/", "."), "v1", f"Paper {d}", doi=d))
        return found
    def by_title_doi(doi, title_search_only=False):
        assert title_search_only                                       # the doi: search was already asked
        raise errors.PaperSourceError(f"DOI {doi} isn't on arXiv.")
    items = [f"10.1234/x{i}" for i in range(25)] + ["arXiv:1811.01882", "2018arXiv181101882N"]
    with tempfile.TemporaryDirectory() as tmp, patch.object(ax, "query", fake_query), \
            patch.object(ax, "by_doi", by_title_doi):
        cache = ax.LookupCache(Path(tmp))
        found = ax.resolve_many(items, cache=cache)
        assert len(asked) == 3, asked                # 25 DOIs in 2 queries + 2 arXiv IDs in 1 (not 27)
        assert found["10.1234/x3"].doi == "10.1234/x3" and isinstance(found["10.1234/x7"], errors.PaperSourceError)
        assert found["2018arXiv181101882N"].arxiv_id == found["arXiv:1811.01882"].arxiv_id == "1811.01882"
        asked.clear()
        again = ax.resolve_many(items, cache=ax.LookupCache(Path(tmp)))      # a new run: from the cache
        assert asked == [] and again["10.1234/x3"].arxiv_id == "10.1234.x3"
        assert isinstance(again["10.1234/x7"], errors.PaperSourceError)         # 'not on arXiv' remembered
        # full texts: downloaded once
        calls = []
        def get(url, params=None, headers=None, arxiv=True):
            calls.append(url)
            return HTML
        record = ax.parse_feed(FEED)[0]
        with patch.object(ax, "_get", get):
            first = ax.fetch_html_text(record, cache=cache)
            second = ax.fetch_html_text(record, cache=ax.LookupCache(Path(tmp)))
        assert first == second and "EXOFASTv2" in first and len(calls) == 1


def test_patient_retries_and_slowing_down():
    attempts = []
    class Busy(urllib.error.HTTPError):
        def __init__(self, code):
            super().__init__("https://export.arxiv.org", code, "busy", {}, None)
    def urlopen(req, timeout=None):
        attempts.append(time.monotonic())
        if len(attempts) <= 3:
            raise Busy(429 if len(attempts) < 3 else 503)
        return SimpleNamespace(read=lambda: b"ok", __enter__=lambda s: s, __exit__=lambda *a: None)
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"ok"
    def opener(req, timeout=None):
        attempts.append(time.monotonic())
        if len(attempts) <= 3:
            raise Busy(429 if len(attempts) < 3 else 503)
        return Resp()
    state = [0.0, 0.0]
    with patch.object(ax, "BACKOFF_SEC", (0.01,) * 6), patch.object(ax.urllib.request, "urlopen", opener):
        data = ax._spaced(threading.Lock(), state, 0.01, SimpleNamespace())
    assert data == b"ok" and len(attempts) == 4
    assert state[1] > 0.01                                     # slowed down after the busy answers
    def always_busy(req, timeout=None):
        raise Busy(429)
    with patch.object(ax, "BACKOFF_SEC", (0.0,) * 6), patch.object(ax.urllib.request, "urlopen", always_busy):
        try:
            ax._spaced(threading.Lock(), [0.0, 0.0], 0.0, SimpleNamespace())
        except urllib.error.HTTPError as e:
            assert e.code == 429
        else:
            raise AssertionError("gives up after RETRIES")


def test_bibcodes_with_long_page_numbers():
    for bib, page in (("2024MNRAS.52710955B", "10955"), ("2024NatSR..1427219L", "27219")):
        found = ax.parse_identifier(bib)
        assert found and found.kind == "bibcode", bib
        assert ax.Bibcode.parse(bib).page == page
    assert "NatSR" in ax.JOURNAL_ISSNS


def test_bibcode_fallbacks_without_a_label():
    """Label-less journal bibcodes (2026-10-25: 20 of 22 missed by the volume + page search): older ApJ
    / AJ DOIs from volume / issue / page; otherwise the journal's listing for the year."""
    asked = []
    def get(url, params=None, headers=None, arxiv=True):
        asked.append((url, dict(params or {})))
        if url.endswith("/works") and "cursor" not in (params or {}):
            return json.dumps({"message": {"items": []}}).encode()          # the search finds nothing
        if url.endswith("/works"):                                          # the listing
            return json.dumps({"message": {"items": [{"DOI": "10.1093/mnras/sty2238", "volume": "481",
                                                      "page": "596-614"}]}}).encode()
        if "/812/2/112" in url:
            return json.dumps({"message": {"DOI": "10.1088/0004-637x/812/2/112", "volume": "812",
                                           "article-number": "112"}}).encode()
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)
    ax._listings.clear()
    with patch.object(ax, "_get", get):
        assert ax.doi_from_bibcode("2015ApJ...812..112S") == "10.1088/0004-637x/812/2/112"
        tried = [u for u, _ in asked if "/0004-637X/" in u]
        assert tried[0].endswith("10.1088/0004-637X/812/1/112") and tried[-1].endswith("/812/2/112")
        assert asked[0][1]["query.bibliographic"] == "812 112 S"                # volume, page, initial
        asked.clear()
        assert ax.doi_from_bibcode("2018MNRAS.481..596J") == "10.1093/mnras/sty2238"
        listing = [p for u, p in asked if "cursor" in p]
        assert listing and "from-pub-date:2018,until-pub-date:2018" in listing[0]["filter"]
        asked.clear()
        try:
            ax.doi_from_bibcode("2018MNRAS.481..600J")                      # not in the listing
        except errors.PaperSourceError:
            pass
        assert not [p for u, p in asked if "cursor" in p]                    # the listing was reused
    ax._listings.clear()


def test_retry_only_the_failed_papers():
    with tempfile.TemporaryDirectory() as tmp:
        papers = Path(tmp) / "papers.csv"
        papers.write_text("item,reference,paper,read_from,title,status,found,hits,cost_usd,input_tokens,output_tokens,"
                          "message\n2020A&A...644A...1T,Tala Pinto et al. 2020,p1,,,error,,0,0,0,0,isn't on arXiv\n"
                          "2018PASJ...70...59T,Takarada et al. 2018,p2,arXiv:1804.04008v1,,found,x,3,0.001,1,1,\n"
                          "2022MNRAS.512..583G,Gaidos et al. 2022,p3,,,error,,0,0,0,0,429\n")
        failed = fs.read_paper_list(papers, only_failed=True)
        assert [str(i) for i in failed] == ["2020A&A...644A...1T", "2022MNRAS.512..583G"]
        assert failed[1].label == "Gaidos et al. 2022" and failed[1].first_author == "Gaidos"
        assert len(fs.read_paper_list(papers)) == 3


def test_a_batch_mode_search_shares_batches():
    """A focused search in batch mode: the papers' requests go out in shared batches."""
    answer = {"values": [{"obj": "", "col": "pl_fitsoftware", "v": "EXOFASTv2", "u": "", "ep": "", "em": "",
                          "q": "using EXOFASTv2", "src": "Abstract", "c": "high"}], "not_found": []}
    batches = FakeBatches(lambda params: answer)
    fake_client = SimpleNamespace(messages=SimpleNamespace(batches=batches))
    import anthropic
    try:
        with tempfile.TemporaryDirectory() as tmp, patch.object(ax, "_get", fake_get()), \
                patch.object(anthropic, "Anthropic", lambda **kw: fake_client), \
                patch.object(api_client, "BATCH_POLL_SECONDS", (0.01, 0.01)), \
                patch.object(api_client.BatchCollector.__init__, "__defaults__", (0.3, 5.0, 2000)):
            cfg = RunConfig.from_settings(api_key="x", output_dir=Path(tmp) / "out", pack="exoplanets",
                                          model_profile="economy", batch_mode=True, arxiv_cache_dir=Path(tmp) / "cache")
            items = ["arXiv:1811.01882", "1811.01882v4", "2018arXiv181101882N"]       # three 'papers'
            run = fs.run_focused_search(items, ["pl_fitsoftware"], cfg, search_words=["EXOFAST"])
            assert [o.status for o in run.outcomes] == ["found"] * 3
            assert sum(len(b) for b in batches.created) == 3 and len(batches.created) <= 2
            assert all(o.cost_usd > 0 for o in run.outcomes)
            assert (Path(tmp) / "cache" / "lookups.json").is_file()
    finally:
        packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All batch-speed tests passed.")
