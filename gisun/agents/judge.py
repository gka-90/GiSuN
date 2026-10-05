"""
Judge agent: reviews a task's decision for reasoning quality -- does the
evidence actually support the decision, is the strength appropriate, did the
agent miss an obvious reading (negation, quotation, a source in the previous
sentence)? Structural checks are already done by check.py.
"""

import json

from gisun import llm
from gisun.criteria import CRITERIA

SYSTEM = """You review another agent's decision in a critical-reading checker. Be strict but fair.
Approve if the evidence supports the decision and the strength fits. Ask for revision only for a concrete
error (evidence contradicts the decision, a negated/quoted term treated as loaded use, a source in the
context ignored, a number misread, strength clearly too high).
Return ONLY JSON: {"verdict": "approve" | "revise", "problems": ["..."]}"""


def judge(ctx, claim: dict, cid: str, decision: dict, tool_log: list[dict]) -> dict:
    crit = CRITERIA[cid]
    seen = [{"tool": t["tool"], "args": t["args"], "output": str(t["output"])[:400]} for t in tool_log][-6:]
    user = (f"Criterion {cid}: {crit['question']}\nGuidance: {crit['guidance']}\n\n"
            f"Claim: {claim['sentence']}\nPrevious sentences: {claim['context_before']}\n\n"
            f"Decision under review:\n{json.dumps(decision, ensure_ascii=False, indent=1)}\n\n"
            f"Tool results the agent saw:\n{json.dumps(seen, ensure_ascii=False, indent=1)}")
    try:
        out = llm.chat_json(SYSTEM, user, judge=True)  # GISUN_JUDGE_MODEL, if set (open problem #11)
    except llm.LLMError as e:
        return {"verdict": "approve", "problems": [], "note": f"judge unavailable: {e}"}
    verdict = out.get("verdict") if out.get("verdict") in ("approve", "revise") else "approve"
    problems = [str(p) for p in out.get("problems") or []][:4]
    if verdict == "revise" and not problems:
        verdict = "approve"  # a rejection must say what to fix
    return {"verdict": verdict, "problems": problems}
