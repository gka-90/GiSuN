"""
Debug agent: handles technical failures of a task (backend errors, timeouts,
no decision within the step budget) by retrying with a note about what went
wrong. It does not judge content -- that's the judge's job.
"""

from gisun import config, llm


def run_with_debug(attempt, retries: int = config.DEBUG_MAX_RETRIES):
    """attempt(feedback) -> LoopResult. Returns (LoopResult | None, debug_log)."""
    log, feedback = [], None
    for i in range(retries + 1):
        try:
            res = attempt(feedback)
        except llm.LLMError as e:
            log.append({"attempt": i + 1, "error": str(e)})
            feedback = ["The previous attempt failed with a technical error. Keep tool calls simple and "
                        "submit as soon as you have evidence."]
            continue
        if res.answer is not None:
            return res, log
        entry = failure_entry(i + 1, res)
        log.append(entry)
        feedback = ["You ran out of steps without an accepted decision."] + \
                   (entry["rejected_because"] or ["Call submit_decision earlier."])
    return None, log


def failure_entry(attempt: int, res) -> dict:
    """Why an attempt ended with no decision, kept in the output so failures can be diagnosed
    (which tools it called, what the Check agent rejected) even though the trace is dropped."""
    rejected = [t["problems"] for t in res.trace if t.get("kind") == "self_check" and not t["passed"]]
    return {"attempt": attempt, "error": f"no accepted decision after {res.steps} steps",
            "tools_called": [t["tool"] for t in res.trace if t.get("kind") == "tool_call"],
            "submits_rejected": len(rejected),
            "rejected_because": rejected[-1] if rejected else []}
