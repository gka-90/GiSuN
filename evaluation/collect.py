"""
Collect real ChatGPT answers for the gold set (open problem #9) from public datasets.

    wildchat  allenai/WildChat-1M: real user conversations with ChatGPT (gpt-3.5-turbo / gpt-4),
              license ODC-BY. One parquet shard (~60k conversations, 200-340 MB) is plenty.
    hc3       Hello-SimpleAI/HC3: ChatGPT answers (Dec 2022) to finance / medicine / open_qa
              questions, license CC-BY-SA.

Only single-turn English conversations whose question is about one of DOMAINS, and whose
answer gives the detectors something to work on (numbers, loaded or vague wording, causal
claims), are kept. Coding, creative writing, role-play and editing requests are dropped:
GiSuN checks factual answers. Every item records where it came from (dataset, row id, model,
date), which the paper needs.

    python -m evaluation.collect --source wildchat --shards 10 11 --n 60
    python -m evaluation.collect --source hc3 --n 20 --out datasets/candidates_hc3.json

Downloads go to datasets/raw/ (gitignored). WildChat needs pyarrow (pip install pyarrow).
"""

import argparse
import json
import os
import random
import re
import urllib.request
from collections import Counter

from gisun.preprocess import preprocess

RAW = os.path.join("datasets", "raw")
# Items read and rejected by hand (off-topic, personal advice, near-duplicates), with the reason;
# kept in the repo so the selection is reproducible and reportable
EXCLUDED = os.path.join("datasets", "excluded.json")
WILDCHAT_URL = "https://huggingface.co/datasets/allenai/WildChat-1M/resolve/main/data/train-{:05d}-of-00014.parquet"
HC3_URL = "https://huggingface.co/datasets/Hello-SimpleAI/HC3/resolve/main/{}.jsonl"
HC3_CONFIGS = ["finance", "medicine", "open_qa"]

DOMAINS = {
    "economy": r"\b(econom\w*|unemploy\w*|inflation|gdp|recession|wages?|minimum wage|poverty|income|tax(es)?|"
               r"debt|deficit|housing|stock market|interest rates?|jobs?)\b",
    "health": r"\b(health|disease|vaccin\w*|covid|cancer|obesity|diabetes|mortality|life expectancy|"
              r"smoking|drugs?|mental health|depression|suicide|diet|nutrition|medical)\b",
    "politics": r"\b(election|vote|voting|immigra\w*|government|policy|congress|president|democra\w*|"
                r"republican|gun|crime|police|abortion|welfare|war|military|refugee)\b",
    "history": r"\b(history|historical|world war|civil war|cold war|empire|revolution|holocaust|slavery|"
               r"colonial\w*|ancient|medieval|century)\b",
    "environment": r"\b(climate|global warming|emission\w*|carbon|pollution|renewable|fossil fuel|"
                   r"deforestation|sea level)\b",
    "society": r"\b(education|student debt|college tuition|homeless\w*|social media|population|birth rate|"
               r"gender|racism|inequality|wealth gap)\b",
}
# Requests that are not asking for facts
SKIP_PROMPT = re.compile(
    r"\b(write|rewrite|paraphrase|translate|story|poem|essay|code|python|javascript|sql|function|script|"
    r"role ?play|pretend|act as|imagine|summari[sz]e (this|the following)|email|letter|resume|cover letter|"
    r"lyrics|joke|tweet|caption|slogan|outline|prompt|describe|hypothetical|what if|fiction\w*|alternate|"
    r"would|scenario|calculate|probability|solve|equation|how much is|chapter|episode|character)\b", re.I)
# A question asking for information, not a dialogue, a script or a task description
QUESTION = re.compile(r"^(what|why|how|is|are|was|were|does|do|did|can|could|which|who|when|where|explain|"
                      r"tell me|give me|list|should|has|have)\b", re.I)
DIALOGUE = re.compile(r"^\s*[\[(]|^\s*[A-Z][a-z]+\s*:", re.M)


def _download(url: str, path: str) -> str:
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        print(f"downloading {url}")
        urllib.request.urlretrieve(url, path + ".part")
        os.replace(path + ".part", path)
    return path


def _domain(question: str) -> str | None:
    hits = {d: len(re.findall(p, question, re.I)) for d, p in DOMAINS.items()}
    best = max(hits, key=hits.get)
    return best if hits[best] else None


def _keep(question: str, answer: str) -> bool:
    return (15 <= len(question) <= 300 and 400 <= len(answer) <= 3000 and QUESTION.match(question)
            and not SKIP_PROMPT.search(question) and not DIALOGUE.search(question) and "```" not in answer)


def _signals(question: str, answer: str) -> dict:
    """What the detectors find in the answer; items with nothing to check are not useful gold."""
    ctx = preprocess(answer, question)
    signals = Counter(s for c in ctx.claims for s in c["signals"])
    return {"claims": len(ctx.claims), "signals": dict(signals),
            "numbers": len(ctx.numeric_flags), "bias_terms": len(ctx.bias_flags)}


def from_wildchat(shard: int):
    import pyarrow.parquet as pq  # only this source needs it
    path = _download(WILDCHAT_URL.format(shard), os.path.join(RAW, f"wildchat-{shard:05d}.parquet"))
    table = pq.read_table(path, columns=["conversation_hash", "model", "timestamp", "conversation",
                                         "turn", "language", "toxic", "redacted"])
    for row in table.to_pylist():
        if row["turn"] != 1 or row["language"] != "English" or row["toxic"] or row["redacted"]:
            continue
        conv = row["conversation"]
        if len(conv) < 2 or conv[0]["role"] != "user" or conv[1]["role"] != "assistant":
            continue
        yield {"question": conv[0]["content"].strip(), "text": conv[1]["content"].strip(),
               "source": {"dataset": "allenai/WildChat-1M", "license": "ODC-BY", "shard": shard,
                          "conversation_hash": row["conversation_hash"], "model": row["model"],
                          "date": row["timestamp"].strftime("%Y-%m-%d")}}


def from_hc3():
    for config in HC3_CONFIGS:
        path = _download(HC3_URL.format(config), os.path.join(RAW, f"hc3-{config}.jsonl"))
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                row = json.loads(line)
                for answer in row.get("chatgpt_answers", [])[:1]:
                    yield {"question": row["question"].strip(), "text": answer.strip(),
                           "source": {"dataset": "Hello-SimpleAI/HC3", "license": "CC-BY-SA", "config": config,
                                      "row": i, "model": "ChatGPT (Dec 2022)", "date": "2022-12"}}


def _key(source: dict) -> str:
    return source.get("conversation_hash") or f"{source.get('config')}:{source.get('row')}"


def collect(source: str, n: int, shards: list[int], seed: int, min_claims: int) -> list[dict]:
    excluded = {x["key"] for x in json.load(open(EXCLUDED))} if os.path.exists(EXCLUDED) else set()
    rows = (r for s in shards for r in from_wildchat(s)) if source == "wildchat" else from_hc3()
    by_domain, seen = {d: [] for d in DOMAINS}, set()
    for row in rows:
        domain = _domain(row["question"])
        key = re.sub(r"\W+", " ", row["question"].lower()).strip()[:120]
        if not domain or key in seen or _key(row["source"]) in excluded or not _keep(row["question"], row["text"]):
            continue
        seen.add(key)
        sig = _signals(row["question"], row["text"])
        if sig["claims"] < min_claims:
            continue
        by_domain[domain].append({**row, "domain": domain, "detectors": sig})
    # Balanced across domains; within a domain a random sample, not the most-flagged answers,
    # so the gold set isn't tilted toward what the rules already catch
    print("available per domain:", {d: len(p) for d, p in by_domain.items()})
    rng, picked = random.Random(seed), []
    for pool in by_domain.values():
        rng.shuffle(pool)
    while len(picked) < n and any(by_domain.values()):
        for pool in by_domain.values():
            if pool and len(picked) < n:
                picked.append(pool.pop())
    prefix = "wc" if source == "wildchat" else "hc3"
    for i, item in enumerate(picked, 1):
        item["id"] = f"{prefix}{i:03d}"
    return [{"id": x["id"], "domain": x["domain"], "question": x["question"], "text": x["text"],
             "source": x["source"], "detectors": x["detectors"]} for x in picked]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["wildchat", "hc3"], default="wildchat")
    ap.add_argument("--shards", type=int, nargs="+", default=[10], help="WildChat shards 0-13")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--min_claims", type=int, default=2, help="answers with fewer detector claims are skipped")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--out", default=os.path.join("datasets", "candidates.json"))
    a = ap.parse_args()
    items = collect(a.source, a.n, a.shards, a.seed, a.min_claims)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    print(f"{len(items)} items -> {a.out}", dict(Counter(x["domain"] for x in items)))
