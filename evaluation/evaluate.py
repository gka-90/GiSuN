"""
RQ1  criterion-level: accuracy / precision / recall / F1 of "met" over (claim, criterion) pairs
RQ2  claim-level: does the claim's risk agree with the gold ("high/medium" if any gold criterion is met, else "low")

Gold format (datasets/gold_example.json): each item has "labels": {sentence_substring: {criterion: decision}}.
A gold pair the pipeline never evaluated counts as a miss (predicted "not_run").

    python -m evaluation.evaluate --gold datasets/gold_example.json --batch outputs/batch_full_.../
"""

import argparse
import json
import os
from collections import Counter, defaultdict


def _match_claim(result: dict, key: str):
    return next((c for c in result["claims"] if key.lower() in c["sentence"].lower()), None)


def evaluate(gold_path: str, batch_dir: str) -> dict:
    gold = json.load(open(gold_path, encoding="utf-8"))
    pairs, per_crit, claim_hits, sources = [], defaultdict(Counter), Counter(), Counter()
    for item in gold:
        path = os.path.join(batch_dir, f"{item['id']}.json")
        result = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"claims": []}
        for key, crits in item["labels"].items():
            claim = _match_claim(result, key)
            for cid, gold_dec in crits.items():
                pred = claim["criteria"].get(cid) if claim else None
                pred_dec = pred["decision"] if pred else "not_run"
                if pred:
                    sources[pred["by"]] += 1
                pairs.append((item["id"], key, cid, gold_dec, pred_dec))
                g, p = gold_dec == "met", pred_dec == "met"
                per_crit[cid]["tp" if g and p else "fp" if p else "fn" if g else "tn"] += 1
            gold_risky = any(d == "met" for d in crits.values())
            pred_risky = bool(claim) and claim["score"]["risk"] != "low"
            claim_hits["correct" if gold_risky == pred_risky else "wrong"] += 1

    def prf(c):
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
        r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
        return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
                "accuracy": round((c["tp"] + c["tn"]) / max(sum(c.values()), 1), 3), "n": sum(c.values())}

    total = sum(per_crit.values(), Counter())
    return {"rq1_overall": prf(total), "rq1_by_criterion": {k: prf(v) for k, v in sorted(per_crit.items())},
            "rq2_claim_risk_accuracy": round(claim_hits["correct"] / max(sum(claim_hits.values()), 1), 3),
            "decided_by": dict(sources),
            "errors": [p for p in pairs if (p[3] == "met") != (p[4] == "met")]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--batch", required=True)
    a = ap.parse_args()
    print(json.dumps(evaluate(a.gold, a.batch), indent=2, ensure_ascii=False))
