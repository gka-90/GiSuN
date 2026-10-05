"""
Inter-annotator agreement (open problem #10): Cohen's kappa between two people's labels.

Both files use the gold format of datasets/gold_example.json and label the same items
independently. Pairs are matched on (item id, sentence key, criterion); a pair only one
person labeled is listed as "unmatched", not scored. Human agreement per criterion is the
ceiling to read the model's scores against: if you two only reach kappa 0.4 on C3, a model
F1 on C3 can't mean much more than that.

    python -m evaluation.agreement --a datasets/labels_gideon.json --b datasets/labels_partner.json
"""

import argparse
import json
from collections import Counter, defaultdict


def _pairs(path: str) -> dict[tuple, str]:
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    return {(item["id"], key, cid): decision
            for item in items for key, crits in item["labels"].items() for cid, decision in crits.items()}


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in ca) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0  # both always used the same single label
    return round((observed - expected) / (1 - expected), 3)


def agreement(path_a: str, path_b: str) -> dict:
    a, b = _pairs(path_a), _pairs(path_b)
    shared = sorted(a.keys() & b.keys())
    by_crit = defaultdict(lambda: ([], []))
    for key in shared:
        by_crit[key[2]][0].append(a[key])
        by_crit[key[2]][1].append(b[key])
    return {
        "overall": {"kappa": cohen_kappa([a[k] for k in shared], [b[k] for k in shared]), "n": len(shared)},
        "by_criterion": {cid: {"kappa": cohen_kappa(x, y), "n": len(x),
                               "agree": round(sum(i == j for i, j in zip(x, y)) / len(x), 3)}
                         for cid, (x, y) in sorted(by_crit.items())},
        "disagreements": [{"item": k[0], "sentence": k[1], "criterion": k[2], "a": a[k], "b": b[k]}
                          for k in shared if a[k] != b[k]],
        "unmatched": len(a.keys() ^ b.keys()),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    args = ap.parse_args()
    print(json.dumps(agreement(args.a, args.b), indent=2, ensure_ascii=False))
