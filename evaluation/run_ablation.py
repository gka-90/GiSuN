"""
RQ3: run every mode on the same gold set and compare.

    python -m evaluation.run_ablation --gold datasets/gold_example.json
    python -m evaluation.run_ablation --gold ... --modes full rules_only   # subset

On the HPC, run once per model (GISUN_MODEL=...) to get the model-size curve.

    python -m evaluation.run_ablation --gold ... --force_criteria   # or GISUN_FORCE_CRITERIA=1

--force_criteria runs every criterion the gold labels ask about (evaluation/evaluate.py), and the
summary gives both numbers: "routed_*" with the Plan agent's routing, the plain ones with forced
criteria, plus per criterion how many gold pairs routing missed and why ("routing_missed").
"""

import argparse
import json
import os
from datetime import datetime

from evaluation.evaluate import evaluate
from gisun import config
from gisun.pipeline import MODES, run_dataset

def ablate(gold: str, modes: list[str], root: str, force: bool | None = None) -> dict:
    """Run every mode on the gold set; returns {mode: metrics} and writes root/summary.json.
    force (default config.FORCE_CRITERIA): run every criterion the gold labels ask about."""
    force = config.FORCE_CRITERIA if force is None else force
    table = {}
    for mode in modes:
        batch = os.path.join(root, mode)
        run_dataset(gold, mode, batch, force=force)
        m = evaluate(gold, batch)
        r = m["routing"]
        secs = [v.get("seconds", 0) for v in json.load(open(os.path.join(batch, "batch_summary.json")))["items"].values()]
        table[mode] = {"f1": m["rq1_overall"]["f1"], "accuracy": m["rq1_overall"]["accuracy"],
                       "claim_risk_acc": m["rq2_claim_risk_accuracy"], "decided_by": m["decided_by"],
                       "not_run": m["decided_by"].get("not_run", 0),  # gold pairs this mode skipped
                       "avg_seconds": round(sum(secs) / max(len(secs), 1), 1),
                       "precision": m["rq1_overall"]["precision"], "recall": m["rq1_overall"]["recall"],
                       "forced_criteria": force,
                       # the same run with only the criteria the routing chose (= the plain numbers if not forced)
                       "routed_f1": r["rq1_overall"]["f1"], "routed_precision": r["rq1_overall"]["precision"],
                       "routed_recall": r["rq1_overall"]["recall"],
                       "routed_by_criterion": r["rq1_by_criterion"],
                       "routing_missed": r["missed"],  # {criterion: {cause: gold pairs}}
                       "plan_dropped": {c: v.get("plan_dropped", 0) for c, v in r["missed"].items()},
                       "by_criterion": m["rq1_by_criterion"]}
    json.dump({"model": config.MODEL, "gold": gold, "forced_criteria": force, "modes": table},
              open(os.path.join(root, "summary.json"), "w"), indent=2)
    return table


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--modes", nargs="+", default=list(MODES))
    ap.add_argument("--run_id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--force_criteria", action="store_true", default=config.FORCE_CRITERIA,
                    help="run every labeled criterion (default: GISUN_FORCE_CRITERIA)")
    a = ap.parse_args()
    name = f"ablation_{config.MODEL.replace('/', '_').replace(':', '-')}_{a.run_id}" + ("_forced" if a.force_criteria else "")
    root = os.path.join("evaluation", "outputs", name)
    table = ablate(a.gold, a.modes, root, force=a.force_criteria)
    print(json.dumps({k: {m: v for m, v in row.items() if not m.endswith("by_criterion")} for k, row in table.items()},
                     indent=2))
