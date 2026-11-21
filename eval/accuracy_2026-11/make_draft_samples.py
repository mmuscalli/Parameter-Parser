"""Accuracy evaluation, Phase 1: which papers each batch's data pack is drafted from (seed 20261120).

P1: 10 papers with hand data (so the papers a pack was drafted from and the held-out ones can be scored apart);
P2, P3: 5 each; E1: one discovery paper per detection method, plus a second transit paper (the commonest method).
Writes `<batch>/draft_papers.txt` in the test folder and `drafts.json` here (batch -> pack id, name, papers).
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[2] / "Paper Files/Accuracy Test 2026-11"
SEED = 20261120
BATCHES = json.loads((HERE / "batches.json").read_text())


def pick(keys, n, rng):
    keys = sorted(keys)
    rng.shuffle(keys)
    return sorted(keys[:n])


def main() -> None:
    rng = random.Random(SEED)
    samples = {
        "P1": pick([k for k, m in BATCHES["P1"].items() if m.get("hand_id")], 10, rng),
        "P2": pick(BATCHES["P2"], 5, rng),
        "P3": pick(BATCHES["P3"], 5, rng),
    }
    e1 = [k for k, m in BATCHES["E1"].items() if m.get("arxiv")]          # the sampled discovery papers
    by_method = {}
    for k in e1:
        by_method.setdefault(BATCHES["E1"][k]["method"], []).append(k)
    chosen = []
    for method in ("Transit", "Radial Velocity", "Imaging", "Microlensing"):
        chosen += pick(by_method[method], 2 if method == "Transit" else 1, rng)
    samples["E1"] = sorted(chosen)
    drafts = {}
    for batch, keys in samples.items():
        lines = [f"arXiv:{BATCHES[batch][k]['arxiv']}" if batch == "E1" else BATCHES[batch][k]["pdf"] for k in keys]
        (TESTS / batch / "draft_papers.txt").write_text("\n".join(lines) + "\n")
        drafts[batch] = {"pack": f"accuracy_{batch.lower()}_drafted", "name": f"Accuracy test {batch} (drafted)",
                         "papers": keys}
        print(batch, keys)
    (HERE / "drafts.json").write_text(json.dumps(drafts, indent=1))


if __name__ == "__main__":
    main()
