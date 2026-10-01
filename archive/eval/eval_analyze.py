"""
Does the analysis agent (agent/analyzer.py) beat the rules it falls back to?

The agent can only pick verdicts the detectors support (_verdicts_supported), so
_rule_based() may give the same answers in a fraction of the time. This runs both
on the same responses and compares them.

Run from the project root:
    # 1. write a label template (one row per claim the pipeline extracts), then each
    #    of us copies it and fills in "verdict" independently
    python eval/eval_analyze.py --make-template eval/analyze_labels_template.json
    # 2. compare (needs Ollama)
    GISUN_MODEL=qwen2.5:3b python eval/eval_analyze.py --labels eval/analyze_labels_A.json \
        --labels2 eval/analyze_labels_B.json

eval/analyze_set.json is a starter set of 10 responses written to cover the cases
we know about (cross-sentence sources, negation, quotes). Replace / extend it with
30-50 real ChatGPT responses before reporting numbers.

Metrics:
    rules_vs_agent  claims where the agent's verdict equals the rule verdict, over all runs
    accuracy        (with --labels) verdict == gold label, for rules and for the agent
    consistency     claims whose agent verdict is the same in every run
    by_agent        share of claims the agent decided itself (the rest fell back to rules)
    latency         seconds per response, rules vs. agent
    annotators      (with --labels2) % agreement and Cohen's kappa between the two label files
Every claim where the agent and rules differ is listed with both reasons, so reason
quality can be compared by hand.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent.analyzer import VERDICTS, _rule_based, analyze_response  # noqa: E402
from agent.core import MODEL  # noqa: E402
from extract_claims import extract_claims  # noqa: E402
from server import _detect  # noqa: E402


def rules_only(text: str) -> list[dict]:
    claims = extract_claims(*_detect(text))
    return [{"sentence": c["sentence"], **_rule_based(c)} for c in claims]


def make_template(items: list[dict], path: str):
    template = {
        "_annotator": "YOUR NAME -- fill in independently, don't look at the other file",
        "_verdicts": VERDICTS,
        "_format": "for each claim, set verdict to the one that fits best; note is optional",
    }
    for it in items:
        template[it["id"]] = [{"sentence": c["sentence"], "verdict": "", "note": ""}
                              for c in rules_only(it["text"])]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
    print(f"Wrote {sum(len(v) for k, v in template.items() if not k.startswith('_'))} claims to {path}")


def gold_for(labels: dict, item_id: str) -> dict[str, str]:
    return {row["sentence"]: row["verdict"] for row in labels.get(item_id, []) if row.get("verdict")}


def kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if not n:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in ca) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def annotator_agreement(items, labels_a, labels_b) -> dict:
    a, b, differ = [], [], []
    for it in items:
        ga, gb = gold_for(labels_a, it["id"]), gold_for(labels_b, it["id"])
        for sentence in ga.keys() & gb.keys():
            a.append(ga[sentence])
            b.append(gb[sentence])
            if ga[sentence] != gb[sentence]:
                differ.append({"id": it["id"], "sentence": sentence, "A": ga[sentence], "B": gb[sentence]})
    return {"claims": len(a), "agreement": sum(x == y for x, y in zip(a, b)) / len(a) if a else None,
            "kappa": kappa(a, b), "disagreements": differ}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=os.path.join(ROOT, "eval", "analyze_set.json"))
    ap.add_argument("--make-template", metavar="PATH", help="write a label template and exit (no model)")
    ap.add_argument("--labels", help="gold verdicts (filled-in template)")
    ap.add_argument("--labels2", help="second annotator's labels, for agreement")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "analyze_eval_results.json"))
    args = ap.parse_args()

    items = json.load(open(args.set, encoding="utf-8"))
    if args.make_template:
        make_template(items, args.make_template)
        return
    labels = json.load(open(args.labels, encoding="utf-8")) if args.labels else {}

    n_claims = same_as_rules = by_agent = consistent = 0
    rules_correct = agent_correct = gold_claims = 0
    rules_seconds = agent_seconds = 0.0
    per_item, disagreements = [], []

    for it in items:
        text, gold = it["text"], gold_for(labels, it["id"])

        started = time.perf_counter()
        rules = {r["sentence"]: r for r in rules_only(text)}
        rules_seconds += time.perf_counter() - started

        runs = []
        for _ in range(args.runs):
            started = time.perf_counter()
            result = analyze_response(text, *_detect(text))
            agent_seconds += time.perf_counter() - started
            runs.append({c["sentence"]: c for c in result["claims"]})

        claims = []
        for sentence, rule in rules.items():
            agent = [run[sentence] for run in runs if sentence in run]
            verdicts = [a["verdict"] for a in agent]
            n_claims += 1
            same_as_rules += sum(v == rule["verdict"] for v in verdicts)
            by_agent += sum(a["by"] == "agent" for a in agent)
            consistent += len(set(verdicts)) == 1
            if sentence in gold:
                gold_claims += 1
                rules_correct += rule["verdict"] == gold[sentence]
                agent_correct += sum(v == gold[sentence] for v in verdicts) / len(verdicts)
            for a in agent:
                if a["by"] == "agent" and a["verdict"] != rule["verdict"]:
                    disagreements.append({"id": it["id"], "sentence": sentence, "gold": gold.get(sentence),
                                          "rules": [rule["verdict"], rule["reason"]],
                                          "agent": [a["verdict"], a["reason"]]})
            claims.append({"sentence": sentence, "gold": gold.get(sentence), "rules": rule["verdict"],
                           "agent": verdicts, "by": [a["by"] for a in agent],
                           "agent_reasons": [a["reason"] for a in agent if a["by"] == "agent"]})
            mark = "same" if set(verdicts) == {rule["verdict"]} else "DIFF"
            print(f"{it['id']:4} {mark} rules={rule['verdict']:18} agent={verdicts} gold={gold.get(sentence)}",
                  flush=True)
        per_item.append({"id": it["id"], "claims": claims})

    total = n_claims * args.runs
    summary = {
        "model": MODEL,
        "responses": len(items),
        "claims": n_claims,
        "runs": args.runs,
        "rules_vs_agent": same_as_rules / total if total else None,
        "by_agent": by_agent / total if total else None,
        "consistency": consistent / n_claims if n_claims else None,
        "latency_s": {"rules": round(rules_seconds / len(items), 4),
                      "agent": round(agent_seconds / (len(items) * args.runs), 2)},
    }
    if labels:
        summary["accuracy"] = {"labels": os.path.basename(args.labels), "claims": gold_claims,
                               "rules": rules_correct / gold_claims if gold_claims else None,
                               "agent": agent_correct / gold_claims if gold_claims else None}
    if args.labels2:
        summary["annotators"] = annotator_agreement(items, labels, json.load(open(args.labels2, encoding="utf-8")))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "disagreements": disagreements, "items": per_item},
                  f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"{len(disagreements)} agent verdicts differ from rules; see {args.out}")


if __name__ == "__main__":
    main()
