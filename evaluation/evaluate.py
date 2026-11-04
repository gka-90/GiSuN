"""
RQ1  criterion-level: accuracy / precision / recall / F1 of "met" over (claim, criterion) pairs
RQ2  claim-level: does the claim's risk agree with the gold ("high/medium" if any gold criterion is met, else "low")

Gold format (datasets/gold_example.json): each item has "labels": {sentence_substring: {criterion: decision}}.
A gold pair the pipeline never evaluated counts as a miss (predicted "not_run"), and is counted under
decided_by["not_run"]: a mode can lose points because the plan agent (or the C2 funnel) dropped a
criterion, not because a decision was wrong, so report that count next to F1.

Two views of the same run, so routing misses and judgment misses can be told apart:
    rq1_*          every decision in the outputs. In a forced run (GISUN_FORCE_CRITERIA=1) every
                   labeled criterion ran, so a miss here is a judgment miss.
    routing.rq1_*  only the criteria the rules + Plan agent chose (decisions marked "forced" count
                   as not_run). In a normal run both views are the same.
    routing.missed per criterion, why routing didn't run a gold pair:
                   no_claim       the sentence never became a claim (sentence splitting, filler/question filter)
                   not_candidate  the rules never offered the criterion for that sentence
                   plan_dropped   the Plan agent dropped it (its reason is in plan.notes)
                   funnel         the C2 funnel cut it (config.C2_MAX_CLAIMS)
                   no_output      the item has no output file (failed or not run yet)

    python -m evaluation.evaluate --gold datasets/gold_example.json --batch outputs/batch_full_.../
"""

import argparse
import json
import os
from collections import Counter, defaultdict

from gisun.preprocess import match_claim

MISS_CAUSES = ("no_output", "no_claim", "not_candidate", "plan_dropped", "funnel")


def _match_claim(result: dict, key: str):
    return match_claim(result["claims"], key)


def _prf(c):
    p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
    r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "accuracy": round((c["tp"] + c["tn"]) / max(sum(c.values()), 1), 3), "n": sum(c.values())}


def _miss_cause(result: dict | None, claim: dict | None, cid: str) -> str:
    """Why the routing didn't run this criterion on this claim (see the module docstring)."""
    if result is None:
        return "no_output"
    if claim is None:
        return "no_claim"
    for n in result.get("plan", {}).get("notes", []):
        if isinstance(n, dict) and n.get("claim_id") == claim["claim_id"] and n.get("criterion") == cid:
            if n.get("by") == "funnel":
                return "funnel"
            if n.get("by") in (None, "agent"):  # Plan-agent drops ("by" is missing in older outputs)
                return "plan_dropped"
    return "not_candidate"


def evaluate(gold_path: str, batch_dir: str) -> dict:
    gold = json.load(open(gold_path, encoding="utf-8"))
    pairs, claim_hits, sources, routed_sources = [], Counter(), Counter(), Counter()
    per_crit, routed_crit, missed = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    forced_run = False
    for item in gold:
        path = os.path.join(batch_dir, f"{item['id']}.json")
        result = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
        forced_run = forced_run or bool(result and result.get("forced_criteria"))
        for key, crits in item["labels"].items():
            claim = _match_claim(result, key) if result else None
            for cid, gold_dec in crits.items():
                pred = claim["criteria"].get(cid) if claim else None
                pred_dec = pred["decision"] if pred else "not_run"
                sources[pred["by"] if pred else "not_run"] += 1
                pairs.append((item["id"], key, cid, gold_dec, pred_dec))
                g, p = gold_dec == "met", pred_dec == "met"
                per_crit[cid]["tp" if g and p else "fp" if p else "fn" if g else "tn"] += 1
                # the routing view: what the rules + Plan agent chose, without the forced additions
                routed = pred if pred and not pred.get("forced") else None
                routed_sources[routed["by"] if routed else "not_run"] += 1
                rp = bool(routed) and routed["decision"] == "met"
                routed_crit[cid]["tp" if g and rp else "fp" if rp else "fn" if g else "tn"] += 1
                if routed is None:
                    missed[cid][_miss_cause(result, claim, cid)] += 1
            gold_risky = any(d == "met" for d in crits.values())
            pred_risky = bool(claim) and claim["score"]["risk"] != "low"
            claim_hits["correct" if gold_risky == pred_risky else "wrong"] += 1

    total, routed_total = sum(per_crit.values(), Counter()), sum(routed_crit.values(), Counter())
    return {"forced_criteria": forced_run,
            "rq1_overall": _prf(total), "rq1_by_criterion": {k: _prf(v) for k, v in sorted(per_crit.items())},
            "rq2_claim_risk_accuracy": round(claim_hits["correct"] / max(sum(claim_hits.values()), 1), 3),
            "decided_by": dict(sources),
            "routing": {"rq1_overall": _prf(routed_total),
                        "rq1_by_criterion": {k: _prf(v) for k, v in sorted(routed_crit.items())},
                        "decided_by": dict(routed_sources),
                        "missed": {k: {c: v[c] for c in MISS_CAUSES if v[c]} for k, v in sorted(missed.items())}},
            "errors": [p for p in pairs if (p[3] == "met") != (p[4] == "met")]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--batch", required=True)
    a = ap.parse_args()
    print(json.dumps(evaluate(a.gold, a.batch), indent=2, ensure_ascii=False))
