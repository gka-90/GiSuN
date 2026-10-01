"""
The analysis agent's own job: is a word-list hit actually endorsed by the
response, or negated / quoted / put in someone else's mouth?

Three systems on the same sentences:
    wordlist  every hit stays flagged (what /verify does today)
    cue_rule  cleared if every hit has a negation / quote / attribution cue
              before it (context_cues.cue_rule) -- cheap, but can't tell
              "not a crisis" from "not just a crisis"
    agent     /analyze with verdict "not_endorsed"; its cue is checked by code,
              but whether the cue applies is the model's call

Run from the project root (needs Ollama):
    GISUN_MODEL=qwen2.5:3b python eval/eval_context.py --labels eval/context_labels_A.json \
        --labels2 eval/context_labels_B.json

Metrics, for each system (a "clear" = the system says the hit is not slanted):
    accuracy       slanted / not-slanted decision matches the label
    cleared_ok     not-slanted sentences cleared (false alarms removed)
    cleared_wrong  slanted sentences cleared (the dangerous mistake)
    by_group       accuracy per group in context_set.json
For the agent also: consistency across runs, share decided by the agent, latency.
"""

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent.analyzer import analyze_response  # noqa: E402
from agent.core import MODEL  # noqa: E402
from context_cues import cue_rule  # noqa: E402
from extract_claims import extract_claims  # noqa: E402
from server import _detect  # noqa: E402

SYSTEMS = ("wordlist", "cue_rule", "agent")


def score(preds: list[tuple[str, bool, bool]]) -> dict:
    """preds: (group, gold_slanted, predicted_slanted)"""
    def rate(rows):
        return round(sum(g == p for _, g, p in rows) / len(rows), 3) if rows else None
    not_slanted = [r for r in preds if not r[1]]
    slanted = [r for r in preds if r[1]]
    return {
        "accuracy": rate(preds),
        "cleared_ok": f"{sum(not p for _, _, p in not_slanted)}/{len(not_slanted)}",
        "cleared_wrong": f"{sum(not p for _, _, p in slanted)}/{len(slanted)}",
        "by_group": {grp: rate([r for r in preds if r[0] == grp]) for grp in sorted({r[0] for r in preds})},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=os.path.join(ROOT, "eval", "context_set.json"))
    ap.add_argument("--labels", default=os.path.join(ROOT, "eval", "context_labels_draft.json"))
    ap.add_argument("--labels2", help="second annotator's labels, for agreement")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "context_eval_results.json"))
    args = ap.parse_args()

    items = json.load(open(args.set, encoding="utf-8"))
    labels = json.load(open(args.labels, encoding="utf-8"))
    preds = {s: [] for s in SYSTEMS}
    per_item = []
    consistent = by_agent = agent_runs = 0
    agent_seconds = 0.0

    for it in items:
        text, gold = it["text"], labels[it["id"]]
        claims = extract_claims(*_detect(text))
        terms = [f["matched_value"] for c in claims for f in c["flags"] if f["type"] == "bias_framing"]
        if not terms:
            print(f"{it['id']:8} skipped: no word-list hit")
            continue

        rule_slanted = not cue_rule(text, terms)
        runs = []
        for _ in range(args.runs):
            started = time.perf_counter()
            result = analyze_response(text, *_detect(text))
            agent_seconds += time.perf_counter() - started
            # one sentence -> one claim; slanted unless the model cleared it
            claim = result["claims"][0]
            runs.append({"verdict": claim["verdict"], "by": claim["by"], "reason": claim["reason"],
                         "cue": claim.get("cue")})
            by_agent += claim["by"] == "agent"
            agent_runs += 1
            preds["agent"].append((it["group"], gold, claim["verdict"] != "not_endorsed"))
        preds["wordlist"].append((it["group"], gold, True))
        preds["cue_rule"].append((it["group"], gold, rule_slanted))
        consistent += len({r["verdict"] for r in runs}) == 1

        per_item.append({"id": it["id"], "group": it["group"], "text": text, "terms": terms,
                         "gold_slanted": gold, "cue_rule_slanted": rule_slanted, "agent": runs})
        agent_marks = "".join("S" if r["verdict"] != "not_endorsed" else "." for r in runs)
        print(f"{it['id']:8} gold={'S' if gold else '.'} cue_rule={'S' if rule_slanted else '.'} "
              f"agent={agent_marks} {[r['verdict'] for r in runs]}", flush=True)

    summary = {
        "model": MODEL,
        "sentences": len(per_item),
        "runs": args.runs,
        "labels": os.path.basename(args.labels),
        **{s: score(preds[s]) for s in SYSTEMS},
        "agent_consistency": round(consistent / len(per_item), 3),
        "agent_by_agent": round(by_agent / agent_runs, 3),
        "agent_latency_s": round(agent_seconds / agent_runs, 2),
    }
    if args.labels2:
        other = json.load(open(args.labels2, encoding="utf-8"))
        ids = [p["id"] for p in per_item]
        differ = [i for i in ids if labels[i] != other[i]]
        summary["annotators"] = {"agreement": round(1 - len(differ) / len(ids), 3), "disagreements": differ}

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "items": per_item}, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
