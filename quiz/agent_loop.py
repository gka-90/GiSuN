"""
Generic tool-calling agent loop on top of the local Ollama model.

Instead of one prompt -> one answer, the model works in steps:

    think / call a tool  ->  we run the tool and show it the result  ->  repeat
    ...until it calls the `finish` tool with its final answer.

The finish call is not accepted blindly: `check(args)` (a self-check written
by whoever builds the agent) returns a list of problems. If there are any,
they go back to the model as the finish tool's result and it has to revise.
Every step is recorded in `trace` so the reasoning can be shown / debugged.

Small local models (qwen2.5:1.5b/3b) get tool arguments wrong fairly often,
so tool errors are also sent back to the model rather than raised.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import ollama

MODEL = os.environ.get("GISUN_MODEL", "qwen2.5:1.5b")
MAX_STEPS = 8
MAX_REPEATS = 3  # same reply AND same tool results this many times in a row = stuck, stop early
MAX_RESULT_CHARS = 3000  # keep tool results short so they fit a small model's context
# Ollama's default context window is small; once the conversation outgrows it
# the system prompt is silently cut off and the model loses the instructions.
MODEL_OPTIONS = {"temperature": 0.2, "num_ctx": 8192}
# Seconds per model call. Without it a hung Ollama keeps the request (and a server thread) open forever.
TIMEOUT = float(os.environ.get("GISUN_TIMEOUT", "60"))
_client = ollama.Client(timeout=TIMEOUT)


def chat(**kwargs):
    """Every model call goes through here so they all get TIMEOUT (tests patch this)."""
    return _client.chat(**kwargs)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema for the arguments
    fn: Callable[..., Any]

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters,
        }}


@dataclass
class AgentResult:
    answer: dict | None  # args of the accepted finish call, None if the agent never got there
    trace: list[dict] = field(default_factory=list)
    steps: int = 0


def _to_text(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + " ...(truncated)"


def _recover_tool_call(content: str, by_name: dict[str, Tool]) -> tuple[str, dict] | None:
    """Small models often write a tool call as plain JSON text instead of a real
    tool call. Accept it if it's {"name": ..., "arguments": {...}}, or if its keys
    fit exactly one tool's parameters."""
    match = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("name") in by_name and isinstance(obj.get("arguments"), dict):
        return obj["name"], obj["arguments"]
    fits = [t.name for t in by_name.values()
            if set(t.parameters.get("required", [])) <= obj.keys() <= set(t.parameters.get("properties", {}))
            and obj]
    return (fits[0], obj) if len(fits) == 1 else None


def _stuck(recent: list[str], step_key: list) -> bool:
    recent.append(json.dumps(step_key, default=str))
    del recent[:-MAX_REPEATS]
    return len(recent) == MAX_REPEATS and len(set(recent)) == 1


def run_agent(system: str, task: str, tools: list[Tool], finish: Tool,
              check: Callable[[dict], list[str]], max_steps: int = MAX_STEPS,
              nudge: Callable[[], str] | None = None,
              done: Callable[[], dict | None] | None = None) -> AgentResult:
    """
    Run the observe -> act loop until `finish` is called with arguments that
    pass `check`, or `max_steps` model calls have been used up.

    nudge: what to tell the model when it answers in prose instead of calling
           a tool (small models do this a lot; naming the next action helps).
    done:  optional early exit -- if it returns an answer after a step, stop
           there even if the model never called `finish`.
    """
    by_name = {t.name: t for t in tools + [finish]}
    schemas = [t.schema() for t in by_name.values()]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]
    result = AgentResult(answer=None)
    recent: list[str] = []

    for step in range(1, max_steps + 1):
        result.steps = step
        try:
            reply = chat(model=MODEL, messages=messages, tools=schemas, options=MODEL_OPTIONS)
        except Exception as e:
            result.trace.append({"step": step, "kind": "error", "detail": f"model call failed: {e}"})
            return result

        msg = reply.message
        messages.append(msg)
        # sort_keys: the model shuffles argument order between otherwise identical calls
        step_key = [msg.content, json.dumps([(c.function.name, c.function.arguments)
                                             for c in msg.tool_calls or []], sort_keys=True, default=str)]
        if msg.content and msg.content.strip():
            result.trace.append({"step": step, "kind": "thought", "detail": msg.content.strip()})

        calls = [(c.function.name, dict(c.function.arguments or {})) for c in msg.tool_calls or []]
        if not calls and (recovered := _recover_tool_call(msg.content, by_name)):
            calls = [recovered]
            result.trace.append({"step": step, "kind": "recovered_tool_call", "tool": recovered[0]})
            # Show the model its text was taken as a real call, so the tool result makes sense
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{"function": {"name": recovered[0], "arguments": recovered[1]}}]}
            messages[-1] = msg

        if not calls:
            hint = nudge() if nudge else f"Use the tools to continue. When you are done, call {finish.name}."
            messages.append({"role": "user", "content": hint})
            result.trace.append({"step": step, "kind": "nudge", "detail": hint})
            step_key.append(hint)
            if _stuck(recent, step_key):
                result.trace.append({"step": step, "kind": "stuck", "detail": "same reply repeated; stopping"})
                return result
            continue

        for name, args in calls:
            result.trace.append({"step": step, "kind": "tool_call", "tool": name, "args": args})

            if name == finish.name:
                problems = check(args)
                result.trace.append({"step": step, "kind": "self_check",
                                     "passed": not problems, "problems": problems})
                if not problems:
                    result.answer = args
                    return result
                output = {"accepted": False, "problems": problems,
                          "instruction": f"Fix these problems and call {finish.name} again."}
            elif name in by_name:
                try:
                    output = by_name[name].fn(**args)
                except Exception as e:
                    output = {"error": f"{type(e).__name__}: {e}"}
            else:
                output = {"error": f"Unknown tool '{name}'. Available: {', '.join(by_name)}"}

            text = _to_text(output)
            result.trace.append({"step": step, "kind": "tool_result", "tool": name, "detail": text})
            messages.append({"role": "tool", "content": text, "tool_name": name})
            step_key.append(text)

        # Only stuck if the replies AND what the tools answered stay identical: a repeated
        # rejected call can still make progress (e.g. the analyzer's per-claim attempt cap)
        if _stuck(recent, step_key):
            result.trace.append({"step": step, "kind": "stuck", "detail": "same reply repeated; stopping"})
            return result

        if done and (answer := done()) is not None:
            result.answer = answer
            result.trace.append({"step": step, "kind": "done", "detail": "all work accepted"})
            return result

    return result
