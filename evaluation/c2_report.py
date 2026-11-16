"""
The two C2 results in one screen, from the newest outputs on disk:

    python -m evaluation.c2_report

1. Built test set (datasets/gold_c2_catalog.json, run with hpc/run_eval.slurm): gold label vs decision,
   per kind of sentence, and precision / recall / F1 for "met".
2. Real chatbot answers (hpc/run_chatgpt_test.slurm): how many numeric claims C2 could check, and why not.
"""

import glob
import json
import os
from collections import Counter

GOLD = "datasets/gold_c2_catalog.json"


def newest(pattern: str, keep=lambda p: True) -> str | None:
    paths = sorted((p for p in glob.glob(pattern) if keep(p)), key=os.path.getmtime)
    return paths[-1] if paths else None


def test_set() -> None:
    summary = newest("evaluation/outputs/ablation_*/summary.json",
                     lambda p: json.load(open(p)).get("gold") == GOLD)
    print("== 1. Built test set ==")
    if not summary:
        return print("no run on", GOLD, "yet\n")
    root = os.path.dirname(summary)
    batch = os.path.join(root, "full")
    table, status, missing = Counter(), Counter(), 0
    gold = json.load(open(GOLD))
    for item in gold:
        want, kind = next(iter(item["labels"].values()))["C2"], item["id"].rsplit("-", 1)[1]
        path = os.path.join(batch, item["id"] + ".json")
        got, why = "not_run", None
        if os.path.exists(path):
            for c in json.load(open(path))["claims"]:
                if "C2" in c["criteria"]:
                    got, why = c["criteria"]["C2"]["decision"], c["criteria"]["C2"].get("c2_status")
        else:
            missing += 1
        table[(kind, want, got)] += 1
        if got != want:
            status[(got, why)] += 1
    print(root, f"({len(gold) - missing} of {len(gold)} items finished)")
    kinds = ["exact", "wrong", "approx_true", "approx_wrong", "floor_true", "floor_wrong"]
    cols = ["met", "not_met", "undetermined", "not_run"]
    print(f"{'kind':14}{'gold':9}" + "".join(f"{c:>14}" for c in cols))
    for k in kinds:
        want = "met" if k in ("wrong", "approx_wrong", "floor_wrong") else "not_met"
        print(f"{k:14}{want:9}" + "".join(f"{table[(k, want, c)]:>14}" for c in cols))
    tp = sum(n for (k, w, g), n in table.items() if w == "met" and g == "met")
    fp = sum(n for (k, w, g), n in table.items() if w == "not_met" and g == "met")
    fn = sum(n for (k, w, g), n in table.items() if w == "met" and g != "met")
    exact = sum(n for (k, w, g), n in table.items() if w == g)
    p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    print(f"'met': precision {p:.2f}  recall {r:.2f}  F1 {2 * p * r / max(p + r, 1e-9):.2f}"
          f"   exact decision right: {exact} of {len(gold)}")
    print("wrong or undecided, by reason:", ", ".join(f"{n} {g}/{w}" for (g, w), n in status.most_common()) or "none")
    print()


def real_answers() -> None:
    path = newest("evaluation/outputs/*_full_*.json")
    print("== 2. Real chatbot answers ==")
    if not path:
        return print("no run yet")
    counts = Counter()
    for a in json.load(open(path))["answers_detail"]:
        for c in a["claims"]:
            if "C2" in c.get("criteria", {}):
                counts[(c["criteria"]["C2"], c.get("c2_status"))] += 1
    total = sum(counts.values())
    checked = sum(n for (d, s), n in counts.items() if s == "checked")
    print(path)
    print(f"{total} numeric claims, {checked} checked against an official figure")
    for (d, s), n in counts.most_common():
        print(f"{n:>4}  {d:13} {s}")


if __name__ == "__main__":
    test_set()
    real_answers()
