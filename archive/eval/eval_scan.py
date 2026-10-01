"""
Evaluate the scan agent (agent/scanner.py): does it find slanted wording the
word list missed, without flagging neutral wording, and does it give the same
answer every time?

Run from the project root (needs Ollama):
    GISUN_MODEL=qwen2.5:3b python eval/eval_scan.py --labels eval/labels_A.json --labels2 eval/labels_B.json

Metrics (scan proposals only; quoted/negated verdicts are a separate round):
    precision    accepted proposals that overlap a labeled slanted phrase / all accepted proposals
    recall       labeled missed phrases found at least once per run, averaged over runs
    consistency  sentences whose set of accepted proposals is identical across all runs
    agreement    (with --labels2) sentences where both annotators labeled the same phrases
"""

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent.core import MODEL  # noqa: E402
from agent.scanner import scan_for_missed_framing  # noqa: E402
from server import WORDLIST_PATH, _detect  # noqa: E402


def spans(text: str, phrases: list[str]) -> list[tuple[int, int]]:
    out = []
    for p in phrases:
        i = text.lower().find(p.lower())
        if i < 0:
            raise ValueError(f"labeled phrase {p!r} not in text {text!r}")
        out.append((i, i + len(p)))
    return out


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def agreement(items, labels_a, labels_b) -> dict:
    same, differ = 0, []
    for it in items:
        a = {p.lower() for p in labels_a[it["id"]]["missed_slanted"]}
        b = {p.lower() for p in labels_b[it["id"]]["missed_slanted"]}
        if a == b:
            same += 1
        else:
            differ.append({"id": it["id"], "text": it["text"], "A": sorted(a), "B": sorted(b)})
    return {"agreement": same / len(items), "disagreements": differ}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=os.path.join(ROOT, "eval", "bias_scan_set.json"))
    ap.add_argument("--labels", default=os.path.join(ROOT, "eval", "labels_draft.json"))
    ap.add_argument("--labels2", help="second annotator's labels, for agreement")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "scan_eval_results.json"))
    args = ap.parse_args()

    items = json.load(open(args.set, encoding="utf-8"))
    labels = json.load(open(args.labels, encoding="utf-8"))
    categories = list(json.load(open(WORDLIST_PATH, encoding="utf-8")))

    tp = fp = 0
    recall_hits = recall_total = 0
    consistent = 0
    per_item = []
    started = time.time()

    for it in items:
        text = it["text"]
        gold = spans(text, labels[it["id"]]["missed_slanted"])
        _, bias_flags = _detect(text)
        runs = []
        for r in range(args.runs):
            scan = scan_for_missed_framing(text, bias_flags, categories)
            proposals = [(f["start_index"], f["end_index"]) for f in scan["flags"]]
            run_tp = sum(any(overlaps(p, g) for g in gold) for p in proposals)
            tp += run_tp
            fp += len(proposals) - run_tp
            recall_hits += sum(any(overlaps(g, p) for p in proposals) for g in gold)
            recall_total += len(gold)
            runs.append(sorted({text[s:e].lower() for s, e in proposals}))
        same = all(r == runs[0] for r in runs)
        consistent += same
        per_item.append({"id": it["id"], "group": it["group"], "text": text,
                         "labeled": labels[it["id"]]["missed_slanted"], "runs": runs, "consistent": same})
        print(f"{it['id']:8} {'same' if same else 'DIFF':4} labeled={labels[it['id']]['missed_slanted']} runs={runs}",
              flush=True)

    summary = {
        "model": MODEL,
        "runs_per_sentence": args.runs,
        "sentences": len(items),
        "labels": os.path.basename(args.labels),
        "accepted_proposals": tp + fp,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": recall_hits / recall_total if recall_total else None,
        "consistency": consistent / len(items),
        "false_positives_by_group": {
            g: sum(sum(1 for r in p["runs"] for q in r
                       if not any(overlaps(s, gs) for s in spans(p["text"], [q])
                                  for gs in spans(p["text"], p["labeled"])))
                   for p in per_item if p["group"] == g)
            for g in sorted({it["group"] for it in items})},
        "seconds": round(time.time() - started),
    }
    if args.labels2:
        summary["annotators"] = agreement(items, labels, json.load(open(args.labels2, encoding="utf-8")))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "items": per_item}, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
