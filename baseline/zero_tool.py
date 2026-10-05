"""
Zero-tool baseline: one model call reads the whole answer and decides every
criterion for every claim, with no tools, plan, judge or checks. Output has
the same shape as the pipeline, so evaluation/evaluate.py scores it directly.

    python -m baseline.zero_tool --dataset datasets/gold_example.json
"""

import argparse
import json
import os
from datetime import datetime

from gisun import config, llm
from gisun.criteria import CRITERIA, applicable
from gisun.preprocess import preprocess
from gisun.scoring import score_claim, score_response

SYSTEM = """You check claims in a chatbot answer. For each claim and each listed criterion decide
"met" (the problem is present), "not_met" or "undetermined". Use only your own knowledge.
Return ONLY JSON: {"claims": [{"claim_id": 0, "criteria": {"C1": "met"}}]}"""


def run(text: str, question: str = "") -> dict:
    ctx = preprocess(text, question, all_sentences=config.OPEN_CRITERIA)  # same claims as the full pipeline
    table = "\n".join(f"{k}: {v['question']}" for k, v in CRITERIA.items())
    claims = [{"claim_id": c["claim_id"], "sentence": c["sentence"], "criteria": applicable(c, config.OPEN_CRITERIA)}
              for c in ctx.claims]
    out = llm.chat_json(SYSTEM, f"Criteria:\n{table}\n\nAnswer:\n{text}\n\nClaims:\n{json.dumps(claims, indent=1)}")
    by_id = {int(c.get("claim_id", -1)): c.get("criteria", {}) for c in out.get("claims", [])}
    claims_out = []
    for c in claims:
        decisions = {cid: {"decision": by_id.get(c["claim_id"], {}).get(cid, "undetermined"), "strength": "moderate",
                           "by": "baseline"} for cid in c["criteria"]}
        for d in decisions.values():
            d["decision"] = d["decision"] if d["decision"] in ("met", "not_met", "undetermined") else "undetermined"
        claims_out.append({**c, "criteria": decisions, "score": score_claim(decisions)})
    return {"mode": "zero_tool_baseline", "model": config.MODEL, "claims": claims_out,
            "response": score_response([c["score"] for c in claims_out])}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    a = ap.parse_args()
    out = os.path.join("outputs", f"baseline_{datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(out, exist_ok=True)
    for item in json.load(open(a.dataset, encoding="utf-8")):
        json.dump(run(item["text"], item.get("question", "")), open(os.path.join(out, f"{item['id']}.json"), "w"), indent=2)
    print(out)
