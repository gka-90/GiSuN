"""
Tool-calling loop shared by the task agents (kept from agent/core.py, trimmed).

The model calls tools until it calls `submit`. The submit arguments go through
`validate`; problems are returned to the model as the tool result so it can fix
them. Every step is recorded in the trace.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from gisun import llm

MAX_RESULT_CHARS = 2500


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Any]

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


@dataclass
class LoopResult:
    answer: dict | None
    trace: list[dict] = field(default_factory=list)
    steps: int = 0
    tool_log: list[dict] = field(default_factory=list)  # (name, args, output) for the judge / check


def _text(value) -> str:
    t = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return t if len(t) <= MAX_RESULT_CHARS else t[:MAX_RESULT_CHARS] + " ...(truncated)"


def _recover(content: str, names: set[str]):
    """Small models sometimes write the tool call as JSON text."""
    obj = llm.parse_json(content)
    if obj and obj.get("name") in names and isinstance(obj.get("arguments"), dict):
        return obj["name"], obj["arguments"]
    return None


def run_tool_loop(system: str, task: str, tools: list[Tool], submit: Tool,
                  validate: Callable[[dict, list[dict]], list[str]], max_steps: int) -> LoopResult:
    by_name = {t.name: t for t in tools + [submit]}
    schemas = [t.schema() for t in by_name.values()]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]
    res = LoopResult(answer=None)
    last = None

    for step in range(1, max_steps + 1):
        res.steps = step
        reply = llm.chat(messages, schemas)  # LLMError propagates to the debug agent
        calls = [(c["name"], c["arguments"]) for c in reply["tool_calls"]]
        if not calls and (rec := _recover(reply["content"], set(by_name))):
            calls = [rec]
        messages.append({"role": "assistant", "content": reply["content"],
                         "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls]})
        if reply["content"].strip():
            res.trace.append({"step": step, "kind": "thought", "detail": reply["content"].strip()[:500]})

        if not calls:
            hint = f"Use the tools. When you have decided, call {submit.name}."
            messages.append({"role": "user", "content": hint})
            res.trace.append({"step": step, "kind": "nudge", "detail": hint})
            continue

        key = json.dumps(calls, sort_keys=True, default=str)
        if key == last:  # identical call twice in a row: tell it instead of looping
            messages.append({"role": "user", "content": "You repeated the same call. Change it or submit."})
        last = key

        for name, args in calls:
            res.trace.append({"step": step, "kind": "tool_call", "tool": name, "args": args})
            if name == submit.name:
                problems = validate(args, res.tool_log)
                res.trace.append({"step": step, "kind": "self_check", "passed": not problems, "problems": problems})
                if not problems:
                    res.answer = args
                    return res
                output = {"accepted": False, "problems": problems, "instruction": f"Fix and call {submit.name} again."}
            elif name in by_name:
                try:
                    output = by_name[name].fn(**args)
                except Exception as e:
                    output = {"error": f"{type(e).__name__}: {e}"}
                res.tool_log.append({"tool": name, "args": args, "output": output})
            else:
                output = {"error": f"unknown tool {name!r}; available: {sorted(by_name)}"}
            text = _text(output)
            res.trace.append({"step": step, "kind": "tool_result", "tool": name, "detail": text[:500]})
            messages.append({"role": "tool", "content": text, "tool_name": name})
    return res
