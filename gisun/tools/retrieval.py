"""
search() / read_source() for the numeric-accuracy criterion (C2).

local   -> keyword search over data/reference_corpus.json (works offline and on the HPC)
searxng -> a self-hosted SearXNG instance (run it on the HPC; no cloud API key)

Every document an agent reads is recorded in the RunContext, so the judge can
check that quoted evidence really came from a source the agent opened.
"""

import json
import re
import urllib.parse
import urllib.request
from functools import lru_cache

from gisun import config

STOP = {"the", "a", "an", "of", "in", "on", "and", "or", "to", "is", "was", "for", "by", "with", "at", "as", "us"}


def _terms(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]


@lru_cache(maxsize=1)
def _corpus() -> list[dict]:
    try:
        with open(config.CORPUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _local_search(query: str, k: int) -> list[dict]:
    q = set(_terms(query))
    scored = []
    for doc in _corpus():
        words = _terms(doc["title"] + " " + doc["text"])
        score = sum(words.count(t) for t in q) + 3 * len(q & set(_terms(doc["title"])))
        if score:
            scored.append((score, doc))
    scored.sort(key=lambda x: -x[0])
    return [{"source_id": d["id"], "title": d["title"], "publisher": d.get("publisher", ""),
             "snippet": d["text"][:200]} for _, d in scored[:k]]


def _searxng_search(query: str, k: int) -> list[dict]:
    url = f"{config.SEARXNG_URL}/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
    with urllib.request.urlopen(url, timeout=20) as resp:
        results = json.loads(resp.read()).get("results", [])
    return [{"source_id": r["url"], "title": r.get("title", ""), "publisher": urllib.parse.urlparse(r["url"]).netloc,
             "snippet": r.get("content", "")[:200]} for r in results[:k]]


def search(query: str, k: int = 5) -> list[dict]:
    if not query or not query.strip():
        raise ValueError("query is empty")
    return _searxng_search(query, k) if config.SEARCH == "searxng" else _local_search(query, k)


def read_source(source_id: str, max_chars: int = 2500) -> dict:
    for doc in _corpus():
        if doc["id"] == source_id:
            return {"source_id": source_id, "title": doc["title"], "publisher": doc.get("publisher", ""),
                    "text": doc["text"][:max_chars]}
    if source_id.startswith("http"):
        with urllib.request.urlopen(source_id, timeout=20) as resp:
            html = resp.read().decode("utf-8", "ignore")
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", html)))
        return {"source_id": source_id, "title": "", "publisher": urllib.parse.urlparse(source_id).netloc,
                "text": text[:max_chars]}
    raise ValueError(f"unknown source_id {source_id!r}; use one returned by search")
