"""Speed test of the parallel run: how long does one answer take to check with 1, 4, 8, 16 tasks at once?

Runs the real pipeline on the first N answers of datasets/gold_answers.json for each setting and
prints a table (median / mean seconds per answer, seconds per claim). Needs the model running
(GISUN_BACKEND=openai_compat GISUN_BASE_URL=... GISUN_MODEL=...), e.g. on the HPC.

    python -m evaluation.speed_test --n 10
    python -m evaluation.speed_test --n 10 --settings 1:no_judge 16:no_judge

A setting is PARALLEL:MODE. PARALLEL is how many claim x criterion tasks run at once
(gisun/config.py MAX_PARALLEL_TASKS); MODE is full | no_judge | no_debug | task_only.
Results are also saved to evaluation/outputs/speed_test.json.
"""
import argparse
import json
import statistics
import time
from pathlib import Path

from gisun import config
from gisun.pipeline import run

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS = ["1:no_judge", "4:no_judge", "8:no_judge", "16:no_judge"]  # parallelism only: same mode


def time_setting(answers, parallel: int, mode: str) -> dict:
    config.MAX_PARALLEL_TASKS = parallel
    rows = []
    for a in answers:
        start = time.perf_counter()
        result = run(a["text"], a.get("question", ""), mode=mode)
        seconds = time.perf_counter() - start
        rows.append({"id": a["id"], "seconds": round(seconds, 1), "claims": len(result["claims"]),
                     "words": len(a["text"].split())})
        print(f"  {parallel:>2} parallel, {mode:<9} {a['id']:<14} {seconds:6.1f} s  {rows[-1]['claims']} claims", flush=True)
    secs = [r["seconds"] for r in rows]
    claims = sum(r["claims"] for r in rows)
    return {"parallel": parallel, "mode": mode, "answers": len(rows), "claims": claims,
            "median_s": round(statistics.median(secs), 1), "mean_s": round(statistics.mean(secs), 1),
            "max_s": max(secs), "s_per_claim": round(sum(secs) / claims, 1) if claims else None, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="how many answers to time")
    ap.add_argument("--settings", nargs="+", default=DEFAULT_SETTINGS, help="PARALLEL:MODE, e.g. 16:no_judge")
    ap.add_argument("--data", default=str(ROOT / "datasets" / "gold_answers.json"))
    args = ap.parse_args()
    answers = json.load(open(args.data))[: args.n]
    print(f"model {config.MODEL} ({config.BACKEND}); {len(answers)} answers\n")
    out = []
    for s in args.settings:
        parallel, mode = s.split(":")
        out.append(time_setting(answers, int(parallel), mode))
    print(f"\n{'setting':<18}{'answers':>8}{'claims':>8}{'median s':>10}{'mean s':>9}{'max s':>8}{'s/claim':>9}")
    for r in out:
        print(f"{r['parallel']:>2} parallel, {r['mode']:<9}{r['answers']:>5}{r['claims']:>8}"
              f"{r['median_s']:>10}{r['mean_s']:>9}{r['max_s']:>8}{r['s_per_claim']:>9}")
    path = ROOT / "evaluation" / "outputs" / "speed_test.json"
    path.parent.mkdir(exist_ok=True)
    json.dump({"model": config.MODEL, "results": out}, open(path, "w"), indent=2)
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()
