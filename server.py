"""
Minimal backend for the extension: POST /verify runs detect_numeric_claims()
and detect_bias_framing() on a chatbot response and returns the combined flags
in the shared format that extension/content.js renders.

Run from the project root:
    uvicorn server:app --port 8000 --reload
"""

import os

from fastapi import FastAPI
from pydantic import BaseModel

from detect_bias_framing import detect_bias_framing
from detect_numeric_claims import detect_numeric_claims

WORDLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bias_wordlist.json")

app = FastAPI(title="GiSuN backend")


class VerifyRequest(BaseModel):
    text: str


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


@app.post("/verify")
def verify(req: VerifyRequest) -> dict:
    flags = detect_numeric_claims(req.text) + detect_bias_framing(req.text, wordlist_path=WORDLIST_PATH)
    flags.sort(key=lambda f: f["start_index"])
    return {"flags": _to_utf16_offsets(req.text, flags)}
