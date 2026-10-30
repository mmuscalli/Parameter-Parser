"""
Offline tests for the focused search (focused_search.py): which parameters can be chosen, the
local keyword screening (passages, tables kept whole, 'not mentioned' without a call), paper lists
from a CSV, the answer conversion (units, uncertainties, EXOFAST version) and a whole search over
an arXiv paper and a local PDF. Stand-ins for the network and the model; no API calls.

Run with: python tests/test_focused_search.py
"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from parameter_extractor import api_client, packs
from parameter_extractor import focused_search as fs
from parameter_extractor.config.run_config import RunConfig
from parameter_extractor.ingestion import arxiv_source as ax
from test_arxiv_source import fake_get
from test_pipeline_offline import PDF as EDER_PDF


def test_parameters_to_choose_from():
    try:
        pack = packs.activate("exoplanets")
        cols = {p.column: p for p in fs.available_parameters(pack)}
        assert cols["pl_orbper"].unit == "d" and cols["pl_orbper"].group == "Planet parameters"
        assert cols["pl_fitsoftware"].kind == "text" and "pl_fitexofastver" in cols
        off = {p.column for p in fs.available_parameters(pack, {"fit_models": "off", "planet_parameters": "off"})}
        assert "pl_fitsoftware" not in off and "pl_orbper" not in off and "st_teff" in off
        prebiotic = {p.column for p in fs.available_parameters(packs.activate("prebiotic_chemistry"))}
        assert {"initial_temperature_C", "cycle_number"} <= prebiotic
    finally:
        packs.activate("prebiotic_chemistry")


def test_keyword_screening():
    p = fs.FocusParameter("pl_orbper", "Planet", "orbital period", "d")
    assert fs.keywords_for([p], ["EXOFAST", " exofast "]) == ["exofast"]          # the user's words win
    assert fs.keywords_for([p]) == ["orbital", "period"]
    text = "\n".join(["Title of the paper", "Abstract text.", *[f"filler line {i} " + "x" * 60 for i in range(30)],
                      "We used EXOFASTv2 for the fit.", "more filler", *[f"filler {i}" for i in range(10)],
                      "Table 2: Fitted parameters", "Parameter | Value", "P (d) | 11.5", "K (m/s) | 30.1",
                      *[f"tail {i}" for i in range(20)]])
    body, hits = fs.passages(text, ["exofast"])
    assert hits == 1 and "We used EXOFASTv2" in body and "Table 2" not in body and "[...]" in body
    body, hits = fs.passages(text, ["fitted parameters"])
    assert hits == 1 and "K (m/s) | 30.1" in body and "P (d) | 11.5" in body        # the table, whole
    assert fs.passages(text, ["juliet"])[1] == 0


def test_whole_tables_in_passages():
    """teng2023's planet table (2026-10-24): rows separated by blank lines, a caption without a 'Table N'
    label ('Orbital parameters.') several lines above, rows with no search word in them. Whole tables
    keep every row; rows-only keeps just what's near a match."""
    text = "\n".join(["Title", "x" * 1600, *[f"intro {i}" for i in range(20)],
                      "\\tbl", "", "Orbital parameters.", "*", "**", "footnote mark", "",
                      "Parameters | P | K | e", "", "Unit | (d) | (m/s) |", "",
                      *[r for i in range(30) for r in (f"HD {1000 + i} b | {100 + i}.5 | 30 | 0.1", "")],
                      "{tabnote}", *[f"tail {i}" for i in range(20)]])
    lines = text.splitlines()
    spans = fs.table_spans(lines)
    assert len(spans) == 1 and "HD 1029 b" in lines[spans[0].stop - 1]
    body, hits = fs.passages(text, ["orbital"])
    assert hits == 1 and "HD 1000 b |" in body and "HD 1029 b |" in body                # every row
    rows_only, _ = fs.passages(text, ["orbital"], whole_tables=False)
    assert "HD 1029 b |" not in rows_only and "Orbital parameters." in rows_only
    captioned = "\n".join(["Table 2: Fit results", "a | b", "", "c | d", "", "e | f"])
    assert [(s.start, s.stop) for s in fs.table_spans(captioned.splitlines())] == [(0, 6)]


def test_answer_conversion_and_paper_lists():
    Answer = fs.answer_model(["pl_orbper", "pl_fitexofastver"])
    a = Answer.model_validate({"values": [
        {"obj": "11 Com b", "col": "pl_orbper", "v": "0.8849", "u": "yr", "ep": "0.0002", "em": "0.0001",
         "q": "P = 0.8849 yr", "src": "Table 3", "c": "high"},
        {"obj": "", "col": "pl_fitexofastver", "v": "EXOFASTv2", "u": "", "ep": "", "em": "", "q": "EXOFASTv2",
         "src": "Sect. 3", "c": "high"}], "not_found": []})
    params = {"pl_orbper": fs.FocusParameter("pl_orbper", "P", "orbital period", "d"),
              "pl_fitexofastver": fs.FocusParameter("pl_fitexofastver", "F", "EXOFAST version", "", "text")}
    period, version = (fs._converted(params[v.col], v, "x") for v in a.values)
    assert abs(period.value - 323.21) < 0.1 and period.unit == "d" and period.err_minus < 0 < period.err_plus
    assert period.printed == "0.8849 yr" and version.value == 2
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "papers.csv"
        listing.write_text("id,notes\narXiv:1811.01882,HD 1397\n10.1093/pasj/psad056,\n"
                           "2023PASJ...75.1030T,ADS\nlocal/teng2023.pdf,\nnot a paper,\narXiv:1811.01882,again\n")
        items = fs.read_paper_list(listing)
        assert items == ["arXiv:1811.01882", "10.1093/pasj/psad056", "2023PASJ...75.1030T",
                         Path(tmp) / "local" / "teng2023.pdf"]


def test_results_one_row_per_object_and_a_column_per_parameter():
    """Mickey, 2026-10-24: each parameter is its own column holding its value (not parameter/value
    pairs); a paper-wide value (the software) goes on each object's row; uncertainty columns, in the
    pack's naming, only when some value has one."""
    period = fs.FocusParameter("pl_orbper", "Planet", "orbital period", "d", "number",
                               ("pl_orbpererr1", "pl_orbpererr2"))
    software = fs.FocusParameter("pl_fitsoftware", "Fits", "software", "", "text")
    v = lambda obj, col, value, unit="", ep="", em="": fs.FocusedValue("p", obj, col, value, unit, ep, em,
                                                                         quote="q", where="Table 2")
    found = fs.PaperOutcome(item="x", paper="p", status="found", values=[
        v("", "pl_fitsoftware", "EXOFASTv2"), v("b", "pl_orbper", 11.535, "d", 0.001, -0.002),
        v("c", "pl_orbper", 4.2, "yr"), v("c", "pl_orbper", 1534.0, "d")])
    none = fs.PaperOutcome(item="y", paper="q", status="not mentioned")
    rows = fs.wide_rows([found, none])
    assert [(r.outcome.paper, r.obj) for r in rows] == [("p", "b"), ("p", "c"), ("q", "")]
    columns = fs.result_columns([period, software], [found, none])
    assert [c for c, _, _ in columns] == ["pl_orbper", "pl_orbpererr1", "pl_orbpererr2", "pl_fitsoftware"]
    b, c, q = rows
    assert fs.cell_text(b.cells["pl_orbper"], period) == "11.535"
    assert fs.cell_text(b.cells["pl_orbper"], period, "err_minus") == "-0.002"
    assert fs.cell_text(c.cells["pl_orbper"], period) == "4.2 yr; 1534"        # unconverted keeps its unit
    assert fs.cell_text(b.cells["pl_fitsoftware"], software) == fs.cell_text(c.cells["pl_fitsoftware"]) == "EXOFASTv2"
    assert q.cells == {} and "Table 2" in fs.value_tip(b.cells["pl_orbper"])
    assert [c for c, _, _ in fs.result_columns([period], [none])] == ["pl_orbper"]   # no errors: no columns


def test_rows_are_the_packs_samples_grouped_by_set():
    """Mickey, 2026-10-30: eder1994's focused rows were whole experiment sets (every time point of a set
    in one cell). Values now name their set and sample, as in a full run: one row per sample, a set's
    values on each of its rows, the paper's on every row, a set with no sample values as its own row."""
    v = lambda st, obj, col, value: fs.FocusedValue("p", obj, col, value, "", set=st)
    out = fs.PaperOutcome(item="x", paper="p", status="found", values=[
        v("", "", "analysis_method", "HPLC"),
        v("Na+ 3.33, 81 C", "", "initial_temperature_C", 81), v("Na+ 3.33, 81 C", "t = 97.3 h", "yield", 2.77),
        v("Na+ 3.33, 81 C", "t = 245.8 h", "yield", 5.60), v("K+ 3.33, 85 C", "", "initial_temperature_C", 85)])
    rows = fs.wide_rows([out])
    assert [(r.set, r.obj) for r in rows] == [("Na+ 3.33, 81 C", "t = 97.3 h"), ("Na+ 3.33, 81 C", "t = 245.8 h"),
                                               ("K+ 3.33, 85 C", "")]
    first, _, k = rows
    assert {c: [x.value for x in vs] for c, vs in first.cells.items()} == {
        "analysis_method": ["HPLC"], "initial_temperature_C": [81], "yield": [2.77]}
    assert [x.value for x in k.cells["initial_temperature_C"]] == [85] and "yield" not in k.cells
    # rows the answer lists: a set-level value fills each of them, even with no sample value requested
    listed = fs.PaperOutcome(item="z", paper="r", status="found", rows=[("A", "t = 1 h"), ("A", "t = 2 h")],
                             values=[v("A", "", "initial_temperature_C", 80)])
    assert [(r.set, r.obj, [x.value for x in r.cells["initial_temperature_C"]]) for r in fs.wide_rows([listed])] \
        == [("A", "t = 1 h", [80]), ("A", "t = 2 h", [80])]
    # answers without a set (older recordings) keep one row per object
    old = fs.PaperOutcome(item="y", paper="q", status="found", values=[fs.FocusedValue("q", "b", "x", 1, "")])
    assert [(r.set, r.obj) for r in fs.wide_rows([old])] == [("", "b")]


def _fake_send(calls):
    def send(ctx, *, model, system_prompt, content, response_model, stop_reason="end_turn"):
        calls.append({"model": model, "content": content})
        answer = {"values": [{"obj": "", "col": "pl_fitsoftware", "v": "EXOFASTv2", "u": "", "ep": "", "em": "",
                              "q": "using EXOFASTv2", "src": "Abstract", "c": "high"},
                             {"obj": "", "col": "pl_fitexofastver", "v": "EXOFASTv2", "u": "", "ep": "", "em": "",
                              "q": "using EXOFASTv2", "src": "Abstract", "c": "high"}], "not_found": []}
        answer["values"] = [v for v in answer["values"] if f"`{v['col']}`" in content]   # only what was asked
        return SimpleNamespace(id="fake", stop_reason=stop_reason, parsed_output=response_model.model_validate(answer),
                               content=[SimpleNamespace(type="text", text=json.dumps(answer))],
                               usage=SimpleNamespace(input_tokens=6000, output_tokens=300))
    return send


def test_a_search_over_several_papers():
    if not EDER_PDF.is_file():
        print(f"SKIP: needs {EDER_PDF}"); return
    calls = []
    try:
        with tempfile.TemporaryDirectory() as tmp, patch.object(ax, "_get", fake_get()), \
                patch.object(api_client, "_send", _fake_send(calls)):
            cfg = RunConfig.from_settings(api_key="x", output_dir=Path(tmp), pack="exoplanets", model_profile="economy")
            progress = []
            run = fs.run_focused_search(["arXiv:1811.01882", EDER_PDF, "2023PASJ...75.1030T"],
                                        ["pl_fitsoftware", "pl_fitexofastver"], cfg, search_words=["EXOFAST"],
                                        on_progress=lambda d, t, m: progress.append((d, t, m)))
            by_item = {o.item: o for o in run.outcomes}
            nielsen = by_item["arXiv:1811.01882"]
            assert nielsen.status == "found" and nielsen.found == ["pl_fitsoftware", "pl_fitexofastver"]
            assert "full text (arXiv HTML" in nielsen.read_from and nielsen.title.startswith("A Jovian planet")
            assert by_item[str(EDER_PDF)].status == "not mentioned"                  # screened out locally
            assert by_item["2023PASJ...75.1030T"].status == "error" and "without an ADS token" in \
                by_item["2023PASJ...75.1030T"].message
            assert len(calls) == 1 and calls[0]["model"] == "claude-haiku-5-5"        # one small call in all
            sent = calls[0]["content"]
            sent = sent if isinstance(sent, str) else json.dumps(sent)
            assert "PAPER PASSAGES" in sent and len(sent) < 30_000                     # passages, not the paper
            import csv as _csv
            rows = list(_csv.DictReader(open(run.results_csv)))
            assert list(rows[0])[:7] == ["reference", "paper", "set", "obj", "status", "pl_fitsoftware", "pl_fitexofastver"]
            nielsen_row = next(r for r in rows if r["paper"] == "arXiv_1811.01882")
            assert (nielsen_row["pl_fitsoftware"], nielsen_row["pl_fitexofastver"]) == ("EXOFASTv2", "2")
            assert len(rows) == 3 and {r["status"] for r in rows} == {"found", "not mentioned", "error"}
            quotes = run.quotes_csv.read_text().splitlines()                       # the quotes are kept
            assert len(quotes) == 3 and "using EXOFASTv2" in quotes[1]
            papers = run.papers_csv.read_text()
            assert "not mentioned" in papers and "without an ADS token" in papers
            summary = json.loads((run.out_dir / "focused_summary.json").read_text())
            assert summary["status_counts"] == {"found": 1, "not found": 0, "not mentioned": 1, "error": 1}
            assert progress[-1][0] == progress[-1][1] == 3
            whole = fs.run_focused_search(["arXiv:1811.01882"], ["pl_fitsoftware"], cfg, whole_paper=True)
            sent = calls[-1]["content"]
            assert whole.outcomes[0].status == "found" and "PAPER TEXT" in (sent if isinstance(sent, str) else
                                                                             json.dumps(sent))
    finally:
        packs.activate("prebiotic_chemistry")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All focused-search tests passed.")
