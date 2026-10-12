"""
Offline test for ingestion/crossref_lookup.py.

CrossRef's live API is unreachable from this sandboxed session (confirmed:
blocked by org egress policy from both the cloud container and the linked
computer -- see README.md). So this mocks requests.get() with a FIXTURE
that is not made up -- it mirrors real metadata for eder1994.pdf
(DOI 10.1039/DT9940001125) independently confirmed via the RSC article
landing page (pubs.rsc.org/en/Content/ArticleLanding/1994/DT/DT9940001125)
during this session. That makes this a real test of the matching/threshold
logic even though it can't be a live integration test yet.

Run with: python -m pytest tests/ -v   (or just: python tests/test_crossref_lookup.py)
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.crossref_lookup import lookup_doi

GOOD_FIXTURE = {
    "message": {
        "items": [
            {
                "DOI": "10.1039/dt9940001125",
                "title": ["Influence of alkali- and alkaline-earth-metal cations on "
                           "the 'salt-induced peptide formation' reaction"],
                "author": [{"given": "Artur H.", "family": "Eder"},
                           {"given": "Bernd M.", "family": "Rode"}],
                "issued": {"date-parts": [[1994]]},
                "score": 118.4,
            },
        ]
    }
}

WRONG_PAPER_FIXTURE = {
    "message": {
        "items": [
            {
                "DOI": "10.1016/0040-4039(99)99999-9",
                "title": ["A completely unrelated paper about zeolite catalysis"],
                "author": [{"given": "Someone", "family": "Else"}],
                "issued": {"date-parts": [[2003]]},
                "score": 12.1,
            },
        ]
    }
}

EMPTY_FIXTURE = {"message": {"items": []}}


def _mock_response(payload):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


def test_accepts_strong_match():
    with patch("requests.get", return_value=_mock_response(GOOD_FIXTURE)):
        result = lookup_doi(
            title="Influence of Alkali- and Alkaline-earth-metal Cations on the "
                  "'Salt-induced Peptide Formation' Reaction",
            authors=["Artur H. Eder", "Bernd M. Rode"],
            year=1994,
        )
    assert result.accepted, result.reason
    assert result.doi == "10.1039/dt9940001125"
    assert result.title_similarity > 0.85


def test_rejects_weak_title_match():
    with patch("requests.get", return_value=_mock_response(WRONG_PAPER_FIXTURE)):
        result = lookup_doi(title="Influence of Alkali- and Alkaline-earth-metal Cations "
                                   "on the 'Salt-induced Peptide Formation' Reaction")
    assert not result.accepted
    assert "similarity" in result.reason


def test_handles_no_results():
    with patch("requests.get", return_value=_mock_response(EMPTY_FIXTURE)):
        result = lookup_doi(title="Some obscure paper that CrossRef has never heard of")
    assert not result.accepted
    assert "no candidates" in result.reason


def test_handles_network_failure_gracefully():
    with patch("requests.get", side_effect=ConnectionError("blocked by egress policy")):
        result = lookup_doi(title="eder1994")
    assert not result.accepted
    assert "CrossRef request failed" in result.reason


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS: {name}")
    print("All offline crossref_lookup tests passed.")
