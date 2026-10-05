"""
Backend for the extension.

POST /verify   fast, no model: runs detect_numeric_claims() and
               detect_bias_framing() and returns the combined flags in the
               shared format that extension/content.js renders.
POST /pipeline, GET /pipeline/{id}
               multi-agent pipeline (gisun/, see PIPELINE.md): runs in the
               background, poll for the result. Needs a model unless mode=rules_only.
POST /quiz     agent: Two Truths and a Lie with self-checking
               (agent/quiz_agent.py). Needs Ollama running.

Run from the project root:
    uvicorn server:app --port 8000 --reload
"""

import os

from fastapi import FastAPI
from pydantic import BaseModel

from agent.quiz_agent import generate_quiz_agent
from detect_bias_framing import detect_bias_framing
from detect_numeric_claims import detect_numeric_claims
from gisun.api import router as pipeline_router
from gisun.tools.language import context_cues

WORDLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bias_wordlist.json")

app = FastAPI(title="GiSuN backend")
app.include_router(pipeline_router)


class VerifyRequest(BaseModel):
    text: str


class QuizRequest(BaseModel):
    topic: str


def _to_utf16_offsets(text: str, flags: list[dict]) -> list[dict]:
    """Python indexes by code point, but JS strings index by UTF-16 unit, so
    any emoji before a match would shift its offsets in content.js. Convert
    start_index/end_index to UTF-16 so they line up with the page text."""
    utf16_at = [0]
    for ch in text:
        utf16_at.append(utf16_at[-1] + (2 if ord(ch) > 0xFFFF else 1))
    for flag in flags:
        flag["start_index"] = utf16_at[flag["start_index"]]
        flag["end_index"] = utf16_at[flag["end_index"]]
    return flags


def _drop_nested(flags: list[dict]) -> list[dict]:
    """The word list has overlapping phrases ("war on" / "war on women"), so
    keep only the longest match wherever one bias flag sits inside another."""
    return [
        f for f in flags
        if not any(
            o is not f
            and o["start_index"] <= f["start_index"] and f["end_index"] <= o["end_index"]
            and o["end_index"] - o["start_index"] > f["end_index"] - f["start_index"]
            for o in flags
        )
    ]


def _in_use(flag: dict) -> bool:
    """Drop loaded words that are negated, quoted or only mentioned ("not a crisis",
    the term "illegal alien"): highlighting those teaches users to ignore highlights.
    Vague attribution ("experts say") is kept: negating it doesn't add a source."""
    if flag.get("category") == "vague_or_unsourced_attribution":
        return True
    cues = context_cues(flag["sentence"], flag["matched_value"])
    return not (cues.get("negated") or cues.get("quoted") or cues.get("mentioned_not_used"))


def _detect(text: str) -> tuple[list[dict], list[dict]]:
    numeric_flags = detect_numeric_claims(text)
    bias_flags = [f for f in _drop_nested(detect_bias_framing(text, wordlist_path=WORDLIST_PATH)) if _in_use(f)]
    return numeric_flags, bias_flags


@app.post("/verify")
def verify(req: VerifyRequest) -> dict:
    numeric_flags, bias_flags = _detect(req.text)
    flags = sorted(numeric_flags + bias_flags, key=lambda f: f["start_index"])
    return {"flags": _to_utf16_offsets(req.text, flags)}


@app.post("/quiz")
def quiz(req: QuizRequest) -> dict:
    return generate_quiz_agent(req.topic)
