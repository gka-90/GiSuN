"""
One chat() call for every backend, returning the same shape:

    {"content": str, "tool_calls": [{"name": str, "arguments": dict}]}

ollama        -> the ollama Python package (laptop)
openai_compat -> any OpenAI-compatible /chat/completions endpoint (vLLM on the HPC)
none          -> raises; the pipeline runs in rules_only mode without a model
"""

import json
import re
import urllib.request

from gisun import config


class LLMError(RuntimeError):
    pass


def _ollama_chat(messages, tools):
    import ollama
    client = ollama.Client(timeout=config.TIMEOUT_S)
    reply = client.chat(model=config.MODEL, messages=messages, tools=tools or None,
                        options={"temperature": config.TEMPERATURE, "num_ctx": config.NUM_CTX})
    msg = reply.message
    return {"content": msg.content or "",
            "tool_calls": [{"name": c.function.name, "arguments": dict(c.function.arguments or {})}
                           for c in msg.tool_calls or []]}


def _openai_chat(messages, tools):
    # The OpenAI format wants tool results linked to call ids; we keep our own
    # simpler history, so flatten tool turns into user turns for this backend.
    flat = []
    for m in messages:
        if m["role"] == "tool":
            flat.append({"role": "user", "content": f"[result of {m.get('tool_name', 'tool')}]\n{m['content']}"})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            flat.append({"role": "assistant", "content": m.get("content") or json.dumps(
                {"tool_calls": m["tool_calls"]}, ensure_ascii=False)})
        else:
            flat.append({"role": m["role"], "content": m.get("content", "")})
    body = {"model": config.MODEL, "messages": flat, "temperature": config.TEMPERATURE}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(config.BASE_URL.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {config.API_KEY}"})
    with urllib.request.urlopen(req, timeout=config.TIMEOUT_S) as resp:
        data = json.loads(resp.read())
    msg = data["choices"][0]["message"]
    calls = []
    for c in msg.get("tool_calls") or []:
        args = c["function"].get("arguments") or "{}"
        calls.append({"name": c["function"]["name"],
                      "arguments": json.loads(args) if isinstance(args, str) else args})
    return {"content": msg.get("content") or "", "tool_calls": calls}


_BACKENDS = {"ollama": _ollama_chat, "openai_compat": _openai_chat}
_override = None  # tests install a fake backend here


def set_backend(fn):
    """Install a custom chat function (used by tests); None restores the config backend."""
    global _override
    _override = fn


def available() -> bool:
    return _override is not None or config.BACKEND in _BACKENDS


def chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    fn = _override or _BACKENDS.get(config.BACKEND)
    if fn is None:
        raise LLMError(f"no model backend (GISUN_BACKEND={config.BACKEND!r})")
    try:
        return fn(messages, tools)
    except LLMError:
        raise
    except Exception as e:  # network, timeout, bad JSON from server ...
        raise LLMError(f"{type(e).__name__}: {e}") from e


def parse_json(text: str) -> dict | None:
    """Pull the first JSON object out of a reply (tolerates ```json fences / prose)."""
    text = re.sub(r"```(?:json)?", "", text or "")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def chat_json(system: str, user: str) -> dict:
    """Single call that must return a JSON object."""
    reply = chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
    obj = parse_json(reply["content"])
    if obj is None:
        raise LLMError(f"reply was not JSON: {reply['content'][:200]!r}")
    return obj
