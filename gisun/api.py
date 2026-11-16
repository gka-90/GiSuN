"""
Async endpoints for the extension. Add to server.py:

    from gisun.api import router as pipeline_router
    app.include_router(pipeline_router)

POST /pipeline        {"text", "question", "mode", "c34_mode"} -> {"job_id"}  (returns immediately)
                      c34_mode: "strict" | "general", from the extension's C3/C4 quiz
GET  /pipeline/{id}   -> {"status": "running" | "done" | "error", "result": ...}
Results are cached by (text, question, mode, c34_mode), so re-opening a response is instant.
"""

import hashlib
import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from gisun.criteria import C34_MODES
from gisun.pipeline import MODES, run

router = APIRouter()
_jobs: dict[str, dict] = {}
_cache: dict[str, str] = {}
_lock = threading.Lock()


class PipelineRequest(BaseModel):
    text: str
    question: str = ""
    mode: str = "full"
    c34_mode: str = "strict"  # the user's C3/C4 mode; older extension versions don't send it


def _to_utf16(text: str, flags: list[dict]) -> list[dict]:
    at = [0]
    for ch in text:
        at.append(at[-1] + (2 if ord(ch) > 0xFFFF else 1))
    return [{**f, "start_index": at[f["start_index"]], "end_index": at[f["end_index"]]} for f in flags]


def _work(job_id: str, req: PipelineRequest):
    try:
        result = run(req.text, req.question, mode=req.mode, keep_trace=True, c34_mode=req.c34_mode)
        result["flags"] = _to_utf16(req.text, result["flags"])
        _jobs[job_id] = {"status": "done", "result": result}
    except Exception as e:
        _jobs[job_id] = {"status": "error", "error": f"{type(e).__name__}: {e}"}


@router.post("/pipeline")
def start(req: PipelineRequest) -> dict:
    if req.mode not in MODES:
        raise HTTPException(400, f"mode must be one of {list(MODES)}")
    if req.c34_mode not in C34_MODES:
        raise HTTPException(400, f"c34_mode must be one of {list(C34_MODES)}")
    # the C3/C4 mode changes the result, so it is part of the cache key
    key = hashlib.sha256(f"{req.mode}\0{req.c34_mode}\0{req.question}\0{req.text}".encode()).hexdigest()
    with _lock:
        if key in _cache and _jobs.get(_cache[key], {}).get("status") != "error":
            return {"job_id": _cache[key], "cached": True}
        job_id = uuid.uuid4().hex
        _cache[key], _jobs[job_id] = job_id, {"status": "running"}
    threading.Thread(target=_work, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id, "cached": False}


@router.get("/pipeline/{job_id}")
def status(job_id: str) -> dict:
    if job_id not in _jobs:
        raise HTTPException(404, "unknown job")
    return _jobs[job_id]
