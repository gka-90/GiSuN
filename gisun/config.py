"""
Model / backend / retrieval configuration. Everything is set by environment
variables so the same code runs on a laptop (Ollama) and on the HPC (vLLM).

    GISUN_BACKEND   ollama (default) | openai_compat | none
    GISUN_MODEL     model name, e.g. qwen2.5:3b (Ollama) or Qwen/Qwen2.5-32B-Instruct (vLLM)
    GISUN_BASE_URL  for openai_compat: http://localhost:8001/v1 (an SSH tunnel to the HPC node)
    GISUN_SEARCH    local (default) | searxng
    GISUN_SEARXNG_URL  e.g. http://localhost:8888
    GISUN_CORPUS    path to the local reference corpus (data/reference_corpus.json)
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BACKEND = os.environ.get("GISUN_BACKEND", "ollama")
MODEL = os.environ.get("GISUN_MODEL", "qwen2.5:3b")
BASE_URL = os.environ.get("GISUN_BASE_URL", "http://localhost:8001/v1")
API_KEY = os.environ.get("GISUN_API_KEY", "EMPTY")  # vLLM ignores it
TEMPERATURE = float(os.environ.get("GISUN_TEMPERATURE", "0.2"))
NUM_CTX = int(os.environ.get("GISUN_NUM_CTX", "8192"))
TIMEOUT_S = int(os.environ.get("GISUN_TIMEOUT", "120"))

SEARCH = os.environ.get("GISUN_SEARCH", "local")
SEARXNG_URL = os.environ.get("GISUN_SEARXNG_URL", "http://localhost:8888")
CORPUS_PATH = os.environ.get("GISUN_CORPUS", os.path.join(ROOT, "data", "reference_corpus.json"))
WORDLIST_PATH = os.path.join(ROOT, "bias_wordlist.json")

# Agent budgets
TASK_MAX_STEPS = int(os.environ.get("GISUN_TASK_STEPS", "8"))
DEBUG_MAX_RETRIES = 2
JUDGE_MAX_REVISIONS = 1
MAX_PARALLEL_TASKS = int(os.environ.get("GISUN_PARALLEL", "4"))
