"""
Plan agent: decides which criteria to evaluate for which claim, and in which
phase. Starts from the registry's deterministic applicability rules; the model
may drop a criterion that doesn't fit (with a reason) or add one the rules
missed (e.g. loaded wording the word list didn't catch).
"""

import json

from gisun import config, llm
from gisun.criteria import CRITERIA, applicable

SYSTEM = """You plan a critical-reading check of a chatbot answer.
For each claim you get candidate criteria chosen by rules. Decide which to run.
- Keep a candidate unless it clearly does not apply.
- Add a criterion only if the claim clearly needs it (e.g. loaded wording not in the word list -> C3).
- A claim with "flags": [] was not flagged by any rule; C3-C6 are offered so you can catch what the
  rules missed. Drop the ones that clearly don't fit (e.g. C6 for a sentence with no cause and effect).
Return ONLY JSON: {"tasks": [{"claim_id": 0, "criterion": "C1", "reason": "..."}], "dropped": [{"claim_id": 0, "criterion": "C6", "reason": "..."}]}"""


def rule_plan(ctx, open_criteria: bool = False) -> dict[int, list[str]]:
    return {c["claim_id"]: applicable(c, open_criteria) for c in ctx.claims}


def _funnel_c2(ctx, plan: dict[int, list[str]], notes: list) -> dict[int, list[str]]:
    """Open problem #3: C2 (search + read + compare) is the slow check, so only the
    config.C2_MAX_CLAIMS most check-worthy claims get it (extract_claims' score, then
    reading order). Every drop is logged in the plan notes so its cost can be measured."""
    with_c2 = sorted((c for c in ctx.claims if "C2" in plan.get(c["claim_id"], [])),
                     key=lambda c: (-c["score"], c["claim_id"]))
    for c in with_c2[config.C2_MAX_CLAIMS:]:
        plan[c["claim_id"]] = [k for k in plan[c["claim_id"]] if k != "C2"]
        notes.append({"claim_id": c["claim_id"], "criterion": "C2", "by": "funnel",
                      "reason": f"not among the {config.C2_MAX_CLAIMS} most check-worthy claims (score {c['score']})"})
    return plan


def _with_dependencies(plan: dict[int, list[str]]) -> dict[int, list[str]]:
    out = {}
    for cid, crits in plan.items():
        crits = [c for c in crits if c in CRITERIA]
        crits = [c for c in crits if all(dep in crits for dep in CRITERIA[c]["depends_on"])]
        out[cid] = sorted(set(crits), key=lambda c: (CRITERIA[c]["phase"], c))
    return out


def plan(ctx, use_model: bool, open_criteria: bool = False) -> dict:
    base = rule_plan(ctx, open_criteria)
    if not use_model or not ctx.claims:
        notes = []
        return {"tasks": _with_dependencies(_funnel_c2(ctx, base, notes)), "by": "rules", "notes": notes}

    table = "\n".join(f"{k}: {v['name']} -- {v['question']}" for k, v in CRITERIA.items())
    claims = [{"claim_id": c["claim_id"], "sentence": c["sentence"], "candidates": base[c["claim_id"]],
               "flags": [f["matched_value"] for f in c["flags"]]} for c in ctx.claims]
    user = f"Criteria:\n{table}\n\nUser question: {ctx.question or '(unknown)'}\n\nClaims:\n" \
           f"{json.dumps(claims, ensure_ascii=False, indent=1)}"
    try:
        out = llm.chat_json(SYSTEM, user)
        chosen: dict[int, list[str]] = {c["claim_id"]: [] for c in ctx.claims}
        for t in out.get("tasks", []):
            cid, crit = int(t.get("claim_id", -1)), str(t.get("criterion"))
            if cid in chosen and crit in CRITERIA:
                chosen[cid].append(crit)
        # Safety net: the model may drop C1/C2 for a statistic only with a reason; never silently.
        dropped = {(int(d.get("claim_id", -1)), str(d.get("criterion"))) for d in out.get("dropped", [])}
        for cid, crits in base.items():
            for crit in crits:
                if crit not in chosen[cid] and (cid, crit) not in dropped:
                    chosen[cid].append(crit)
        notes = list(out.get("dropped", []))
        return {"tasks": _with_dependencies(_funnel_c2(ctx, chosen, notes)), "by": "agent", "notes": notes}
    except (llm.LLMError, ValueError, TypeError) as e:
        notes = [f"plan agent failed: {e}"]
        return {"tasks": _with_dependencies(_funnel_c2(ctx, base, notes)), "by": "rules", "notes": notes}
