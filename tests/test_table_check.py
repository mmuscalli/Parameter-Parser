"""
Offline tests for the second reading of table values (F3, ingestion/table_check.py, 2026-11-11): the comparison
rules on small grids, the readers of landscape pages (teng2023 Table 3: decimal points and superscript uncertainties),
and replays of reference runs (Claude's answers: no flags expected).

Run with: python tests/test_table_check.py
"""
import _isolation  # noqa: F401,E402 -- first: the user's own data never reaches a test (tests/_isolation.py)
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parameter_extractor.ingestion import table_check as tc  # noqa: E402
from parameter_extractor.ingestion import table_grid as tg  # noqa: E402
from parameter_extractor.ingestion.table_grid import Grid  # noqa: E402

PAPERS = Path(__file__).resolve().parents[2] / "Paper Files"


def _grid(table, rows):
    return Grid("G1", table, "1", "", rows)


def _v(value, row="HD 1 b", ep=0.0, em=0.0, table="Table 3", target="", column="pl_x"):
    return tc.TableValue("planet_parameters", table, row, target, column, value, ep, em)


def test_the_comparison_rules():
    g = _grid("Table 3", [["Planet", "P (d)", "e"],
                          ["HD 1 b", "$312.08_{-1.69}^{+1.36}$", "$0.266_{-0.068}^{+0.081}$"],
                          ["HD 2 b", "${30.7}_{-4.9}^{+8.8}$", "0.10"]])
    assert tc.check(_v(312.08, ep=1.36, em=-1.69), [g], True) is None                   # agrees
    f = tc.check(_v(0.266, ep=0.058, em=-0.068), [g], True)                             # uncertainty misread
    assert f.kind == "table_check" and f.cell == "0.266 (+0.081 / −0.068)"
    assert tc.check(_v(30.7, row="HD 2 b", ep=8.8, em=-4.9), [g], True) is None         # braces around the value
    nf = tc.check(_v(0.12, row="HD 2 b"), [g], True)                                    # not in its row
    assert nf.kind == "table_not_found" and "0.10" in nf.cell
    assert tc.check(_v(0.12, row="HD 2 b"), [g], False) is None                         # table ids not trusted
    assert tc.check(_v(5.0, row="HD 9 b", table="Table 7"), [g], True) is None          # nothing to compare with
    # a transposed table: one object per column
    t = _grid("Table 4", [["Parameter", "HD 5 b", "HD 6 b"], ["a (au)", "1.2", "$3.36_{-0.13}^{+0.12}$"]])
    assert tc.check(_v(3.36, row="", target="HD 6 b", ep=0.12, em=-0.13, table="Table 4"), [t], True) is None
    assert tc.check(_v(3.36, row="", target="HD 6 b", ep=0.2, em=-0.13, table="Table 4"), [t], True).kind == \
        "table_check"
    # a row named by its conditions; 'ND' stored as 0; a value that is its row's own label
    c = _grid("Table 1", [["temp", "time", "Gly-Gly", "NH4+"], ["240", "10.0", "6.84", "ND"]])
    assert tc.check(_v(6.84, row="240 °C/10.0 s", table="Table 1"), [c], True) is None
    assert tc.check(_v(0.0, row="240 °C/10.0 s", table="Table 1"), [c], True) is None
    assert tc.check(_v(7.0, row="240 °C/10.0 s", table="Table 1"), [c], True).kind == "table_not_found"
    assert tc.check(_v(1.0, row="Cycle 1", table="Table 1", column="cycle_number"), [c], True) is None
    # a dense table whose columns ran together: values in one cell still found
    d = _grid("Table 3", [["HD 1 b", "18.42^{+2.53}_{−2.43} 0.269^{+0.165}_{−0.150}"]])
    assert tc.check(_v(0.269, ep=0.165, em=-0.150), [d], True) is None
    # a text layer that lost its decimal points is no second reading
    assert tc.garbled(_grid("Table 3", [["HD 1 b", "312 08 + 1 36", "18 42 + 2 53"]]))


def test_flag_text_groups_per_table():
    items = [tc.Finding("table_check", _v(0.266, ep=0.058, em=-0.068), "0.266 (+0.081 / −0.068)"),
             tc.Finding("table_check", _v(38.03, row="HD 4732 c", ep=3.15, em=-3.15), "38.03 (+1.3 / −3.15)"),
             tc.Finding("table_not_found", _v(0.12, row="HD 2 b"), "row: HD 2 b | 0.10")]
    msgs = tc.flag_messages(items, "the PDF's text layer")
    assert [k for k, _ in msgs] == ["table_check", "table_not_found"]
    assert msgs[0][1].startswith("Table 3: 2 value(s) whose uncertainties differ") and msgs[0][1].count("\n- ") == 2
    assert "read 38.03 ± 3.15; the table has 38.03 (+1.3 / −3.15)" in msgs[0][1]


def test_landscape_pages_are_read():
    """teng2023 Table 3 (a landscape page): decimal points 1.7 pt above their digits and superscripts drawn one glyph
    at a time came out as '312 08 + 1 36'; read whole now, and the table's full width (its last columns were cut)."""
    pdf = PAPERS / "Paper Lists" / "Teng2023" / "teng2023.pdf"
    if not pdf.is_file():
        print(f"SKIP: needs {pdf}")
        return
    found, words = tg._turned_tables(str(pdf), 8, 90)[0]
    x0, top, x1, bottom = found["box"]
    body = [w for w in words if x0 - 1 <= w["x0"] and w["x1"] <= x1 + 1 and top <= w["top"] <= bottom]
    rows = tg.grid_rows(body)
    text = " ".join(c for r in rows for c in r)
    assert "312.08^{+1.36}_{−1.69}" in text and "1.117^{+0.003}" in text            # the last column too
    grid = Grid("P1", "Table 3", "", "", rows)
    assert not tc.garbled(grid)
    v = tc.TableValue("planet_parameters", "Table 3", "HD 2952 b", "HD 2952 b", "pl_orbper", 312.08, 1.36, -1.69)
    assert tc.check(v, [grid], True) is None


def test_reference_replays_raise_no_flags():
    """Claude's recorded answers (prebiotic references with text-layer tables) agree with the second reading."""
    from test_reference_runs import REFERENCES, replay_reference
    for name in ("kim2017", "truman2024", "faisal2005"):
        with tempfile.TemporaryDirectory() as out:
            result = replay_reference(REFERENCES / name, Path(out))
            if result is None:
                print(f"SKIP: {name}'s PDF isn't here")
                return
            flags = [f.message for f in result.paper_flags if f.kind in ("table_check", "table_not_found")]
            assert not flags, (name, flags)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All table cross-check tests passed.")
