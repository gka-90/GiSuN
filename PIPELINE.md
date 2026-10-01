# GiSuN multi-agent pipeline

Modeled on the plan / task / debug / judge / check design of multi-agent
variant classification: the model gathers and judges evidence per criterion;
**deterministic rules combine the decisions** (the LLM never picks the final risk).

```
ChatGPT answer + user question
      |
      v
preprocess.py      Tier 1 detectors -> claims (+ context, attribution)     deterministic
      |
      v
Plan agent         which criteria for which claim, in phases               agents/plan.py
      |
      v
Phase 1 (parallel): C1 C3 C4 C5 C6       Phase 2: C2 (after C1)
   each task:  Task -> Debug (retry) -> Judge (review, 1 revision) -> Check (validate)
      |
      v
scoring.py         claim risk (low/medium/high, +unverified) and response level   deterministic
      |
      +--> outputs/*.json, /pipeline API for the extension
```

## Criteria (`gisun/criteria.py`)
| id | name | question ("met" = problem present) | tools |
|---|---|---|---|
| C1 | unsourced_statistic | statistic with no specific source nearby? | find_attribution, context_window |
| C2 | statistic_contradicted | does a reliable source contradict the number? | search, read_source, compare_numbers |
| C3 | loaded_language | slanted wording where neutral would do? | context_cues, wordlist_lookup |
| C4 | overgeneralization | sweeping absolute claim? | context_cues |
| C5 | vague_attribution | "experts say" instead of a source? | find_attribution, context_window |
| C6 | unsupported_causal_claim | cause-effect with no evidence? | find_attribution, context_window |

Each criterion also has a deterministic `rule`, used in `rules_only` mode and as the
fallback when an agent fails (`by: "rules"` in the output).

## Agents
| agent | file | decides | model? |
|---|---|---|---|
| Plan | agents/plan.py | criteria per claim; may drop (with reason) or add | yes, falls back to rules |
| Task | agents/task.py | one criterion for one claim; chooses its own tools | yes |
| Debug | agents/debug.py | retries technical failures / step-budget overruns | no |
| Judge | agents/judge.py | approves or sends back with concrete problems (max 1 revision) | yes |
| Check | agents/check.py | schema; every quote must be in the response or a source **opened in this run**; C2 needs compare_numbers and must agree with it | no |

## Run
```bash
# laptop (Ollama)
GISUN_MODEL=qwen2.5:7b python -m gisun.pipeline --text "..." --mode full
# no model
python -m gisun.pipeline --text "..." --mode rules_only
# HPC (vLLM through an SSH tunnel, or inside a job: hpc/run_eval.slurm)
GISUN_BACKEND=openai_compat GISUN_BASE_URL=http://localhost:8001/v1 GISUN_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ \
  python -m gisun.pipeline --dataset datasets/gold_example.json
```

## Evaluation
| RQ | script | measures |
|---|---|---|
| RQ1 | evaluation/evaluate.py | criterion-level accuracy / P / R / F1 |
| RQ2 | evaluation/evaluate.py | claim risk agreement |
| RQ3 | evaluation/run_ablation.py | full / no_judge / no_debug / task_only / **rules_only** |
| RQ4 | (todo) | C2 retrieval: was the right source found (Recall@k) |
| baseline | baseline/zero_tool.py | one call, no tools |

Run RQ3 once per model on the HPC for the model-size curve.

First result (rules_only on the 4-item example set): F1 0.84, but **C2 F1 0.0** (rules can't
verify numbers) and C1 misses "The 2020 Census counted ..." (no attribution verb) -- exactly the
gaps the agents are meant to close.

## Tests (no model)
`python -m unittest tests.test_pipeline` -- a scripted fake model checks the full flow,
rejection of an invented quote, judge revisions, and rule fallback when the backend is down.

## Not done yet
- `data/reference_corpus.json` is 3 SAMPLE entries: replace with real snapshots (BLS, Census, World Bank,
  a Wikipedia dump) or run SearXNG on the HPC (`GISUN_SEARCH=searxng`).
- `datasets/gold_example.json` is 4 hand-made items: build 50+ real ChatGPT answers, labeled by both of you.
- Extension: call `POST /pipeline`, poll `GET /pipeline/{id}`, show per-claim risk, reasons and evidence;
  let the user overrule a decision and recompute with scoring.py.
- Quiz: use a C2-contradicted claim as the "lie".
