"""
Model / backend / retrieval configuration. Everything is set by environment
variables so the same code runs on a laptop (Ollama) and on the HPC (vLLM).

    GISUN_BACKEND   ollama (default) | openai_compat | none
    GISUN_MODEL     model name, e.g. qwen2.5:3b (Ollama) or Qwen/Qwen2.5-32B-Instruct (vLLM)
    GISUN_BASE_URL  for openai_compat: http://localhost:8001/v1 (an SSH tunnel to the HPC node)
    GISUN_BLS_KEY, GISUN_CENSUS_KEY, GISUN_DATACOMMONS_KEY
                    free API keys for the C2 statistics lookup (gisun/tools/retrieval.py).
                    World Bank needs none; BLS works without one for monthly figures only.
    GISUN_STAT_CACHE    cache of API responses (data/stat_cache.json)
    GISUN_STAT_OFFLINE  1 = use the cache only, no API calls (HPC nodes without internet)
    GISUN_JUDGE_MODEL, GISUN_JUDGE_BASE_URL
                    a different (e.g. larger) model for the Judge agent, so it doesn't share the
                    Task agent's blind spots (open problem #11). Default: same as GISUN_MODEL.
    GISUN_OPEN_CRITERIA  1 (default) = in model modes, run C3-C6 on every factual sentence,
                    not only on sentences the detectors flagged (open problem #1). 0 = old behaviour.
    GISUN_C2_MAX_CLAIMS  only the N most check-worthy claims get the slow C2 source check (#3)

Any of these can also go in a .env file at the repo root (KEY=value per line; git-ignored, so
API keys stay out of the repo). A variable already set in the shell wins over .env.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.removeprefix("export ").split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(os.path.join(ROOT, ".env"))

BACKEND = os.environ.get("GISUN_BACKEND", "ollama")
MODEL = os.environ.get("GISUN_MODEL", "qwen2.5:3b")
BASE_URL = os.environ.get("GISUN_BASE_URL", "http://localhost:8001/v1")
API_KEY = os.environ.get("GISUN_API_KEY", "EMPTY")  # vLLM ignores it
TEMPERATURE = float(os.environ.get("GISUN_TEMPERATURE", "0.2"))
NUM_CTX = int(os.environ.get("GISUN_NUM_CTX", "8192"))
TIMEOUT_S = int(os.environ.get("GISUN_TIMEOUT", "120"))
JUDGE_MODEL = os.environ.get("GISUN_JUDGE_MODEL", MODEL)
JUDGE_BASE_URL = os.environ.get("GISUN_JUDGE_BASE_URL", BASE_URL)

OPEN_CRITERIA = os.environ.get("GISUN_OPEN_CRITERIA", "1") == "1"
C2_MAX_CLAIMS = int(os.environ.get("GISUN_C2_MAX_CLAIMS", "5"))

BLS_KEY = os.environ.get("GISUN_BLS_KEY", "")
CENSUS_KEY = os.environ.get("GISUN_CENSUS_KEY", "")
DATACOMMONS_KEY = os.environ.get("GISUN_DATACOMMONS_KEY", "")
STAT_SERIES_PATH = os.path.join(ROOT, "data", "stat_series.json")
STAT_CACHE_PATH = os.environ.get("GISUN_STAT_CACHE", os.path.join(ROOT, "data", "stat_cache.json"))
STAT_OFFLINE = os.environ.get("GISUN_STAT_OFFLINE", "0") == "1"
WORDLIST_PATH = os.path.join(ROOT, "data", "bias_wordlist.json")

# Agent budgets
TASK_MAX_STEPS = int(os.environ.get("GISUN_TASK_STEPS", "8"))
DEBUG_MAX_RETRIES = 2
JUDGE_MAX_REVISIONS = 1
MAX_PARALLEL_TASKS = int(os.environ.get("GISUN_PARALLEL", "4"))
