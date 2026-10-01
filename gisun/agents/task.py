"""Task agent: decides ONE criterion for ONE claim, choosing its own tools."""

import json

from gisun import config
from gisun.agents.check import check_decision
from gisun.agents.loop import Tool, run_tool_loop
from gisun.agents.toolbox import build_tools
from gisun.criteria import CRITERIA, DECISIONS, STRENGTHS

SYSTEM = """You check one claim from a chatbot answer against one criterion, for a student learning to read critically.
Use the tools to gather evidence, then call submit_decision.
- decision "met" means the problem IS present; "not_met" means it is not; "undetermined" if the evidence can't settle it.
- strength: how sure the evidence makes you (strong / moderate / supporting).
- evidence: exact quotes. source = "response" for words from the answer, or the source_id you opened.
- Never invent quotes or sources. Respond in English."""


def run_task(ctx, claim: dict, cid: str, feedback: list[str] | None = None, max_steps: int | None = None):
    crit = CRITERIA[cid]
    tools = build_tools(crit["tools"], claim, ctx)
    submit = Tool("submit_decision", "Submit your decision for this criterion. It is checked.",
                  {"type": "object", "required": ["decision", "strength", "reasoning", "evidence"], "properties": {
                      "decision": {"type": "string", "enum": list(DECISIONS)},
                      "strength": {"type": "string", "enum": list(STRENGTHS)},
                      "reasoning": {"type": "string"},
                      "evidence": {"type": "array", "items": {"type": "object", "properties": {
                          "quote": {"type": "string"}, "source": {"type": "string"}}}}}},
                  lambda **_: None)
    flags = [{"text": f["matched_value"], "type": f["type"], **({"category": f["category"]} if "category" in f else {})}
             for f in claim["flags"]]
    task = (f"Criterion {cid} ({crit['name']}): {crit['question']}\nGuidance: {crit['guidance']}\n\n"
            f"Claim: {claim['sentence']}\nPrevious sentences: {claim['context_before']}\n"
            f"Detector flags: {json.dumps(flags, ensure_ascii=False)}")
    if feedback:
        task += "\n\nA reviewer rejected your previous decision:\n- " + "\n- ".join(feedback) + \
                "\nInvestigate again and submit a corrected decision."
    return run_tool_loop(SYSTEM, task, tools, submit,
                         validate=lambda args, log: check_decision(cid, args, claim, ctx, log),
                         max_steps=max_steps or config.TASK_MAX_STEPS)
