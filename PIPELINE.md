# GiSuN multi-agent pipeline

Modeled on the plan / task / debug / judge / check design of multi-agent
variant classification: the model gathers and judges evidence per criterion;
**deterministic rules combine the decisions** (the LLM never picks the final risk).

```
ChatGPT answer + user question
      |
      v
preprocess.py      Tier 1 detectors -> claims (+ context, attribution)     deterministic
                   model modes: every factual sentence is a claim, flagged or not
      |
      v
Plan agent         which criteria for which claim, in phases               agents/plan.py
                   C2 funnel: only the GISUN_C2_MAX_CLAIMS most check-worthy claims
      |
      v
Phase 1 (parallel): C1 C3 C4 C5 C6       Phase 2: C2 (after C1)
   each task:  Task -> Debug (retry) -> Judge (review, 1 revision) -> Check (validate)
      |
      v
scoring.py         claim risk (low/medium/high, +unverified) and response level   deterministic
      |
      +--> outputs/*.json, /pipeline API -> the extension highlights the flagged claims of every answer
```

## Criteria (`gisun/criteria.py`)
| id | name | question ("met" = problem present) | tools | open |
|---|---|---|---|---|
| C1 | unsourced_statistic | statistic or other quantitative claim with no specific source nearby? | find_attribution, context_window | numberless records / trends / comparisons |
| C2 | statistic_contradicted | does a reliable source contradict the number? | search, read_source, compare_numbers | |
| C3 | loaded_language | slanted wording where neutral would do? | context_cues, wordlist_lookup | yes |
| C4 | overgeneralization | sweeping absolute claim? | context_cues | yes |
| C5 | vague_attribution | "experts say" instead of a source? | find_attribution, context_window | yes |
| C6 | unsupported_causal_claim | cause-effect with no evidence? | find_attribution, context_window | yes |

Each criterion also has a deterministic `rule`, used in `rules_only` mode and as the
fallback when an agent fails (`by: "rules"` in the output).

**Which claims get which criteria.** `applies(claim)` is the rule gate: C1 for a statistic,
C3/C4/C5 for a word-list hit, C6 for causal wording, C2 for a number `compare_numbers` can
read (not "most Americans"). In model modes, the **open** criteria (C3-C6) also run on every
other factual sentence, including ones no detector flagged (`detector_hit: false` in the
output), because the agents can only catch what the rules miss if they see those sentences.
`rules_only` keeps the gates (the rules have nothing to say about unflagged sentences), so it
stays the same baseline. Turn this off with `GISUN_OPEN_CRITERIA=0`.

**C2 compares like with like.** A source figure only counts if it is about the same year as
the claim: the rule reads only source sentences that mention the claim's year, and the Check
agent rejects a "contradicted" verdict unless its source quote comes from such a sentence. A
claim with no year can't be contradicted (it's "undetermined"). The guidance also asks the
agent to match measure (U-3 vs U-6), place and unit (percent vs percentage points).

**Quantitative claims without numbers.** "The highest ever", "a record low", "skyrocketed",
"outpaced inflation" (the statistic-formats reference's "claims without explicit numbers") make a
claim quantitative with no digits. In model modes C1 also runs on those (the `quantitative` cue in
extract_claims.py); `rules_only` keeps its narrower gate. C2 only runs on values it can compare
(percentages, amounts, counts, ratios), not on scores, rankings or research statistics.

**Scoring.** C1 and C5 usually describe the same missing source, so together they add at
most 2 points ("Studies show 40%" is one attribution problem, not two).

## Agents
| agent | file | decides | model? |
|---|---|---|---|
| Plan | agents/plan.py | criteria per claim; may drop (with reason) or add; then the C2 funnel | yes, falls back to rules |
| Task | agents/task.py | one criterion for one claim; chooses its own tools | yes |
| Debug | agents/debug.py | retries technical failures / step-budget overruns | no |
| Judge | agents/judge.py | approves or sends back with concrete problems (max 1 revision); can be a different model (`GISUN_JUDGE_MODEL`) | yes |
| Check | agents/check.py | schema; every quote must be in the response or a source **opened in this run**; C2 needs compare_numbers, must agree with it, and a contradiction must come from a same-year source sentence | no |

Every criterion the Plan agent or the funnel drops is logged in the result's `plan.notes`.

## Run
```bash
# laptop (Ollama)
GISUN_MODEL=qwen2.5:7b python -m gisun.pipeline --text "..." --mode full
# no model
python -m gisun.pipeline --text "..." --mode rules_only
# browser: start the backend, load the extension, click any highlight (see README)
```

| setting | default | meaning |
|---|---|---|
| `GISUN_MODEL` / `GISUN_BACKEND` / `GISUN_BASE_URL` | qwen2.5:3b / ollama / localhost:8001 | task / plan model |
| `GISUN_JUDGE_MODEL` / `GISUN_JUDGE_BASE_URL` | same as above | a different model for the Judge |
| `GISUN_OPEN_CRITERIA` | 1 | run C3-C6 on unflagged sentences in model modes |
| `GISUN_C2_MAX_CLAIMS` | 5 | how many claims get the C2 source check |

### On the Hamilton CS HPC (vLLM)
One-time setup on the login node (`ssh <name>@150.209.91.65`), everything under `/hpc/<name>`
because the home folder is small:
```bash
mkdir /hpc/<name> && cd /hpc/<name>
# Miniconda into /hpc/<name>/miniconda3, then:
echo 'export HF_HOME=/hpc/<name>/hf_cache' >> ~/.bashrc
echo 'export PIP_CACHE_DIR=/hpc/<name>/.cache/pip' >> ~/.bashrc
git clone https://github.com/gka-90/GiSuN.git && cd GiSuN
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main   # and .../pkgs/r
conda create -n ai-guardrail python=3.11 -y && conda activate ai-guardrail
pip install -r requirements.txt vllm
hf download Qwen/Qwen2.5-32B-Instruct-AWQ
```
If pip keeps failing on one file at the same byte (campus network), `wget` that file and
`pip install` it directly, then re-run the full install.

Each run: `cd /hpc/<name>/GiSuN && git pull && sbatch hpc/run_eval.slurm`, then
`tail -f logs/gisun-eval_<job>.out`. The script handles what broke the first attempts:

- **GPU.** Nodes 1-5 have one 16 GB RTX 5070 Ti (too small for 32B; use 14B or 7B AWQ with
  `--gres=gpu:1`). cs-hpc-node-6 has five 96 GB RTX PRO 6000 Blackwell; the script asks for
  one of those by default. It's shared, so keep jobs short.
- **No `nvcc` on the nodes.** FlashInfer's sampler compiles with it, so the script sets
  `VLLM_USE_FLASHINFER_SAMPLER=0`.
- **Offline model.** `HF_HUB_OFFLINE=1` loads the downloaded copy; download on the login node first.
- **`logs/` must exist** before `sbatch` (it's in the repo).

**Use the HPC model from a laptop** (agent highlights in the extension, speed tests):
`sbatch hpc/serve_model.slurm` on the server; once its log says `Application startup complete`,
open a tunnel on the laptop with `ssh -N -L 8011:cs-hpc-node-6:8011 <name>@150.209.91.65` and
start the backend with `GISUN_BACKEND=openai_compat GISUN_BASE_URL=http://localhost:8011/v1
GISUN_MODEL=Qwen/Qwen2.5-32B-Instruct-AWQ GISUN_PARALLEL=8 uvicorn server:app --port 8000`.
`scancel` the job when done.

Qwen's `generation_config.json` adds `top_k=20, top_p=0.8, repetition_penalty=1.05` to our
`temperature=0.2`; report these with results.

## Evaluation
| RQ | script | measures |
|---|---|---|
| RQ1 | evaluation/evaluate.py | criterion-level accuracy / P / R / F1 |
| RQ2 | evaluation/evaluate.py | claim risk agreement |
| RQ3 | evaluation/run_ablation.py | full / no_judge / no_debug / task_only / **rules_only** |
| RQ4 | (todo) | C2 retrieval: was the right source found (Recall@k) |
| agreement | evaluation/agreement.py | Cohen's kappa between two people's labels, per criterion |
| baseline | baseline/zero_tool.py | one call, no tools |

A gold pair a mode never ran (the Plan agent or funnel dropped the criterion) counts as a
miss and is reported as `not_run`. Read F1 next to it: a mode can lose points by skipping
checks, not only by deciding wrongly.

Run RQ3 once per model on the HPC for the model-size curve, including the size the extension
actually runs on a laptop.

### Results so far (4-item example set, 15 gold pairs: a smoke test, not evidence)
`rules_only`: F1 0.84, but **C2 F1 0.0** (rules can't verify numbers) and C1 misses "The 2020
Census counted ..." (no attribution verb).

Qwen2.5-32B-Instruct-AWQ, vLLM 0.22.1, one RTX PRO 6000 (Oct 4, 2026, before the open-criteria change):

| mode | F1 | accuracy | sec / answer | pairs run (of 15) |
|---|---|---|---|---|
| task_only | **0.952** | **0.933** | 6.4 | 15 |
| rules_only | 0.842 | 0.800 | 0.0 | 15 |
| full | 0.824 | 0.800 | 14.6 | 10 |
| no_judge | 0.750 | 0.733 | 5.8 | 7 |
| no_debug | 0.750 | 0.733 | 7.6 | 6 |

task_only beat the rules by 2 pairs. The modes with the Plan agent ran only 6-10 of the 15
gold pairs, because the Plan agent dropped criteria; their lower scores mostly measure that.

## Tests (no model)
`python -m unittest tests.test_pipeline`: a scripted fake model checks the full flow,
rejection of an invented quote, judge revisions, rule fallback when the backend is down,
open criteria on unflagged sentences, the same-year C2 rules, the C1+C5 cap and the C2 funnel.

## Not done yet
Full list with priorities: *GiSuN: open problems and proposed solutions* (Fall 2026).
- `data/reference_corpus.json` is 3 SAMPLE entries: replace with real snapshots for 2-3 domains
  (BLS, Census, World Bank) or run SearXNG on the HPC (`GISUN_SEARCH=searxng`). (#6)
- `datasets/gold_example.json` is 4 hand-made items: build 50+ real ChatGPT answers, labeled by both
  of you with written guidelines; check agreement with `evaluation/agreement.py`. (#9, #10)
- RQ4: label the right source per C2 claim and measure Recall@k. (#8)
- The Plan agent ranks nothing yet: the C2 funnel uses extract_claims' rule score. (#3)
- Loaded language: merge a larger lexicon (e.g. Recasens et al. 2013) into bias_wordlist.json. (#4)
- C2 fields (what/where/when/unit) are only partly enforced: the year is checked in code; measure,
  place and unit are in the guidance only. (#7)
- Extension: let the user overrule a decision and recompute with scoring.py.
- Quiz: use a C2-contradicted claim as the "lie". (#19)
