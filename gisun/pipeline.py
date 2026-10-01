"""
GiSuN pipeline: ChatGPT answer -> per-claim, per-criterion decisions -> risk.

    preprocess (Tier 1 detectors, deterministic)
         |
    Plan agent -> which criteria for which claim, in phases
         |
    for each phase, tasks in parallel:
         Task agent (chooses tools) -> Debug (retries failures) -> Judge (reviews) -> Check (validates)
         |
    scoring.py (deterministic) -> claim risk + response level

Modes (for the ablation study, RQ3):
    full        plan + task + debug + judge
    no_judge    plan + task + debug
    no_debug    plan + task + judge
    task_only   task agent only (rule plan, no debug, no judge)
    rules_only  no model at all (the current Tier 1 system) -- the baseline to beat

A task that fails in any mode falls back to the criterion's rule, marked by="rules".

CLI:
    python -m gisun.pipeline --text "..." [--mode full]
    python -m gisun.pipeline --dataset datasets/gold.json --mode full
"""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from gisun import config, llm
from gisun.agents.check import check_decision, normalize
from gisun.agents.debug import run_with_debug
from gisun.agents.judge import judge
from gisun.agents.plan import plan
from gisun.agents.task import run_task
from gisun.criteria import CRITERIA, PHASES
from gisun.preprocess import preprocess
from gisun.scoring import score_claim, score_response

MODES = {
    "full":       {"plan": True,  "task": True,  "debug": True,  "judge": True},
    "no_judge":   {"plan": True,  "task": True,  "debug": True,  "judge": False},
    "no_debug":   {"plan": True,  "task": True,  "debug": False, "judge": True},
    "task_only":  {"plan": False, "task": True,  "debug": False, "judge": False},
    "rules_only": {"plan": False, "task": False, "debug": False, "judge": False},
}


def _rule(ctx, claim, cid, why: str) -> dict:
    out = normalize(cid, CRITERIA[cid]["rule"](claim, ctx))
    out.update(by="rules", note=why)
    return out


def _run_one(ctx, claim: dict, cid: str, mode: dict) -> dict:
    t0 = time.time()
    if not mode["task"]:
        return {**_rule(ctx, claim, cid, "rules_only mode"), "seconds": 0.0, "trace": []}

    attempt = lambda fb: run_task(ctx, claim, cid, feedback=fb)
    if mode["debug"]:
        res, debug_log = run_with_debug(attempt)
    else:
        debug_log = []
        try:
            res = attempt(None)
            res = res if res.answer is not None else None
        except llm.LLMError as e:
            res, debug_log = None, [{"attempt": 1, "error": str(e)}]

    if res is None:
        return {**_rule(ctx, claim, cid, "agent failed; rule fallback"), "debug": debug_log,
                "seconds": round(time.time() - t0, 1), "trace": []}

    decision, trace, judge_log = normalize(cid, res.answer), list(res.trace), []
    if mode["judge"]:
        for _ in range(config.JUDGE_MAX_REVISIONS + 1):
            review = judge(ctx, claim, cid, decision, res.tool_log)
            judge_log.append(review)
            if review["verdict"] == "approve" or len(judge_log) > config.JUDGE_MAX_REVISIONS:
                break
            revised = run_task(ctx, claim, cid, feedback=review["problems"])
            if revised.answer is None:
                break
            res, decision = revised, normalize(cid, revised.answer)
            trace += [{"kind": "revision"}] + revised.trace
        if judge_log and judge_log[-1]["verdict"] == "revise":
            decision["judge_disputed"] = True  # kept, but flagged for the evaluation / UI

    final_problems = check_decision(cid, decision, claim, ctx, res.tool_log)  # Check agent, final pass
    if final_problems:
        return {**_rule(ctx, claim, cid, f"final check failed: {final_problems}"), "seconds": round(time.time() - t0, 1),
                "trace": trace}
    return {**decision, "by": "agent", "debug": debug_log, "judge": judge_log, "steps": res.steps,
            "seconds": round(time.time() - t0, 1), "trace": trace}


def run(text: str, question: str = "", mode: str = "full", keep_trace: bool = True) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {list(MODES)}")
    m = dict(MODES[mode])
    if m["task"] and not llm.available():
        m = dict(MODES["rules_only"])
        mode = "rules_only (no model backend)"
    t0 = time.time()
    ctx = preprocess(text, question)
    the_plan = plan(ctx, use_model=m["plan"])
    results: dict[int, dict[str, dict]] = {c["claim_id"]: {} for c in ctx.claims}

    with ThreadPoolExecutor(max_workers=config.MAX_PARALLEL_TASKS) as pool:
        for phase in PHASES:
            jobs = []
            for claim in ctx.claims:
                for cid in the_plan["tasks"][claim["claim_id"]]:
                    crit = CRITERIA[cid]
                    if crit["phase"] != phase:
                        continue
                    done = results[claim["claim_id"]]
                    if all(done.get(dep, {}).get("decision") in ok for dep, ok in crit["depends_on"].items()):
                        jobs.append((claim, cid, pool.submit(_run_one, ctx, claim, cid, m)))
            for claim, cid, fut in jobs:
                results[claim["claim_id"]][cid] = fut.result()

    claims_out = []
    for claim in ctx.claims:
        decisions = results[claim["claim_id"]]
        if not keep_trace:
            for d in decisions.values():
                d.pop("trace", None)
        claims_out.append({"claim_id": claim["claim_id"], "sentence": claim["sentence"],
                           "flags": [f["matched_value"] for f in claim["flags"]],
                           "criteria": decisions, "score": score_claim(decisions)})
    by = [d["by"] for c in claims_out for d in c["criteria"].values()]
    return {
        "mode": mode, "model": config.MODEL if m["task"] else None, "backend": config.BACKEND if m["task"] else None,
        "question": question, "text": text,
        "plan": {"by": the_plan["by"], "notes": the_plan["notes"],
                 "tasks": {str(k): v for k, v in the_plan["tasks"].items()}},
        "claims": claims_out,
        "response": score_response([c["score"] for c in claims_out]),
        "agent_share": round(by.count("agent") / len(by), 2) if by else None,
        "seconds": round(time.time() - t0, 1),
        "flags": sorted(ctx.numeric_flags + ctx.bias_flags, key=lambda f: f["start_index"]),
    }


def _save(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    return path


def run_dataset(path: str, mode: str, out_dir: str) -> str:
    """Batch run; writes one file per item and a summary written incrementally (resumable)."""
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "batch_summary.json")
    summary = json.load(open(summary_path)) if os.path.exists(summary_path) else {"mode": mode, "items": {}}
    for item in items:
        if item["id"] in summary["items"]:
            continue  # resume
        try:
            result = run(item["text"], item.get("question", ""), mode=mode)
            _save(result, os.path.join(out_dir, f"{item['id']}.json"))
            summary["items"][item["id"]] = {"ok": True, "seconds": result["seconds"],
                                            "level": result["response"]["level"]}
        except Exception as e:
            summary["items"][item["id"]] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        _save(summary, summary_path)
    return summary_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text")
    ap.add_argument("--question", default="")
    ap.add_argument("--dataset")
    ap.add_argument("--mode", default="full", choices=list(MODES))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if a.dataset:
        print(run_dataset(a.dataset, a.mode, a.out or os.path.join("outputs", f"batch_{a.mode}_{stamp}")))
    elif a.text:
        r = run(a.text, a.question, mode=a.mode)
        print(_save(r, a.out or os.path.join("outputs", f"run_{a.mode}_{stamp}.json")))
        print(json.dumps({"response": r["response"], "claims": [
            {"sentence": c["sentence"], "risk": c["score"]["risk"],
             "criteria": {k: f"{v['decision']} ({v['by']})" for k, v in c["criteria"].items()}}
            for c in r["claims"]]}, indent=2, ensure_ascii=False))
    else:
        ap.error("give --text or --dataset")
