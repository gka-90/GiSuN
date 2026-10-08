"""
RQ3: run every mode on the same gold set and compare.

    python -m evaluation.run_ablation --gold datasets/gold_example.json
    python -m evaluation.run_ablation --gold ... --modes full rules_only   # subset

On the HPC, run once per model (GISUN_MODEL=...) to get the model-size curve.
"""

import argparse
import json
import os
from datetime import datetime

from evaluation.evaluate import evaluate
from gisun import config
from gisun.pipeline import MODES, run_dataset

def ablate(gold: str, modes: list[str], root: str) -> dict:
    """Run every mode on the gold set; returns {mode: metrics} and writes root/summary.json."""
    table = {}
    for mode in modes:
        batch = os.path.join(root, mode)
        run_dataset(gold, mode, batch)
        m = evaluate(gold, batch)
        secs = [v.get("seconds", 0) for v in json.load(open(os.path.join(batch, "batch_summary.json")))["items"].values()]
        table[mode] = {"f1": m["rq1_overall"]["f1"], "accuracy": m["rq1_overall"]["accuracy"],
                       "claim_risk_acc": m["rq2_claim_risk_accuracy"], "decided_by": m["decided_by"],
                       "not_run": m["decided_by"].get("not_run", 0),  # gold pairs this mode skipped
                       "avg_seconds": round(sum(secs) / max(len(secs), 1), 1),
                       "by_criterion": m["rq1_by_criterion"]}
    json.dump({"model": config.MODEL, "gold": gold, "modes": table}, open(os.path.join(root, "summary.json"), "w"), indent=2)
    return table


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--modes", nargs="+", default=list(MODES))
    ap.add_argument("--run_id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    a = ap.parse_args()
    root = os.path.join("evaluation", "outputs", f"ablation_{config.MODEL.replace('/', '_').replace(':', '-')}_{a.run_id}")
    table = ablate(a.gold, a.modes, root)
    print(json.dumps({k: {m: v for m, v in row.items() if m != "by_criterion"} for k, row in table.items()}, indent=2))
