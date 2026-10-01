"""
Async endpoints for the extension. Add to server.py:

    from gisun.api import router as pipeline_router
    app.include_router(pipeline_router)

POST /pipeline        {"text", "question", "mode"} -> {"job_id"}  (returns immediately)
GET  /pipeline/{id}   -> {"status": "running" | "done" | "error", "result": ...}
Results are cached by (text, question, mode), so re-opening a response is instant.
"""

import hashlib
import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from gisun.pipeline import MODES, run

router = APIRouter()
_jobs: dict[str, dict] = {}
_cache: dict[str, str] = {}
_lock = threading.Lock()


class PipelineRequest(BaseModel):
    text: str
    question: str = ""
    mode: str = "full"


def _to_utf16(text: str, flags: list[dict]) -> list[dict]:
    at = [0]
    for ch in text:
        at.append(at[-1] + (2 if ord(ch) > 0xFFFF else 1))
    return [{**f, "start_index": at[f["start_index"]], "end_index": at[f["end_index"]]} for f in flags]


def _work(job_id: str, req: PipelineRequest):
    try:
        result = run(req.text, req.question, mode=req.mode, keep_trace=True)
        result["flags"] = _to_utf16(req.text, result["flags"])
        _jobs[job_id] = {"status": "done", "result": result}
    except Exception as e:
        _jobs[job_id] = {"status": "error", "error": f"{type(e).__name__}: {e}"}


@router.post("/pipeline")
def start(req: PipelineRequest) -> dict:
    if req.mode not in MODES:
        raise HTTPException(400, f"mode must be one of {list(MODES)}")
    key = hashlib.sha256(f"{req.mode}\0{req.question}\0{req.text}".encode()).hexdigest()
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
