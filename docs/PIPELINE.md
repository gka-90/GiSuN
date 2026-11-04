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
| C2 | statistic_contradicted | does a reliable source give a different figure? | lookup_statistic, compare_numbers | |
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

**C2: does a reliable source give a different figure?** Four steps (related work: Vlachos &
Riedel 2015 check country statistics against a knowledge base; DataGemma 2024 grounds an LLM's
numbers in Data Commons; FEVER's SUPPORTED / REFUTED / NOTENOUGHINFO = our not_met / met /
undetermined).
1. *Pin the number down.* The Task agent submits `claim_fields`: value, measure, place, period
   (`2020` or `2020-04`) and hedge (`none` / `approx` / `at_least` / `at_most`). Each may come
   from the claim, the two sentences before it, or the user's question (the claim's own words
   win). If the measure, place or time isn't stated in any of them: `undetermined`.
   Plain "unemployment rate" means U-3.
2. *Look it up* (`gisun/tools/retrieval.py`, `lookup_statistic`): BLS for US jobs and inflation,
   Census for US population and income, World Bank for countries, Data Commons for the rest.
   `data/stat_series.json` says which series answers which measure (a few fixed legal values,
   like the federal minimum wage, are *static entries* with a valid-from date and no API call);
   a measure with no entry
   gets no figure, so C2 never compares against a close-enough series (U-6 for "unemployment",
   an annual average for a monthly claim). Cache first (`data/stat_cache.json`, with the query
   date), then the API.
3. *Compare* (`compare_numbers`): no hedge = after rounding the official figure to the claim's
   precision, at most one unit off in the claim's last digit ("14.7%" matches 14.7 and 14.8, not
   14.9). The one unit is for official revisions and rounding: BLS first published April 2020
   unemployment as 14.7% and later revised it to 14.8%, so an answer quoting the first release
   is not wrong, and a figure rounded twice (by the source, then by the writer) can land one
   unit away. About / roughly / around / nearly = within 10%; over / more than / at
   least = official at or above, under / less than the other way; a range = official inside it.
   All official figures match -> `not_met`, none -> `met`, official sources disagree with each
   other -> `undetermined`, with every figure listed.
4. *Evidence for a human.* Each C2 evidence item cites a `record_id` the lookup returned; the
   saved decision carries the fetched record (source, series ID, value with unit and period,
   query date). The Check agent rejects a decision whose fields aren't in the text, whose hedge
   isn't the sentence's, that cites a figure not fetched in this run, leaves out a figure the
   lookup returned, skips compare_numbers, or disagrees with the tolerance rules.

The rule (`rules_only`) does the same steps with no model: measure from the catalog aliases,
place and period from the text, one of each or `undetermined`.

**Quantitative claims without numbers.** "The highest ever", "a record low", "skyrocketed",
"outpaced inflation" (the statistic-formats reference's "claims without explicit numbers") make a
claim quantitative with no digits. In model modes C1 also runs on those (the `quantitative` cue in
gisun/detectors/claims.py); `rules_only` keeps its narrower gate. C2 only runs on values it can compare
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
| Check | agents/check.py | schema; every quote must be in the response or an official figure **fetched in this run**; C2: fields stated in the text, all fetched figures cited, compare_numbers used, decision = the tolerance rules' | no |

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
| `GISUN_FORCE_CRITERIA` | 0 | evaluation only: 1 = every criterion a gold label asks about runs (see Evaluation); never affects the extension |
| `GISUN_BLS_KEY` | (none) | BLS key: monthly figures work without it, annual averages need it (500 queries/day vs 25) |
| `GISUN_CENSUS_KEY` / `GISUN_DATACOMMONS_KEY` | (none) | needed for Census / Data Commons; World Bank needs no key |
| `GISUN_STAT_CACHE` / `GISUN_STAT_OFFLINE` | data/stat_cache.json / 0 | API response cache; 1 = cache only (HPC nodes with no internet) |

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
| RQ4 | (todo) | C2 on a validation set: step 1 (measure / place / period / hedge) accuracy, then the decision |
| agreement | evaluation/labeling/agreement.py | Cohen's kappa between two people's labels, per criterion |
| baseline | evaluation/zero_tool.py | one call, no tools |

A gold pair a mode never ran (the Plan agent or funnel dropped the criterion) counts as a
miss and is reported as `not_run`. Read F1 next to it: a mode can lose points by skipping
checks, not only by deciding wrongly.

**Forced criteria** separate the two. With `GISUN_FORCE_CRITERIA=1` (or
`run_ablation --force_criteria`, `run_all --force_criteria`), `run_dataset` passes each item's
gold labels to `pipeline.run(..., force=labels)`: the rules and the Plan agent route as usual, then
every labeled criterion that routing left out is added (C2 brings C1), logged in `plan.notes` with
`"by": "forced"`. `plan.routed` keeps what the routing chose and each added decision has
`"forced": true`, so one run gives both numbers:

| report field | meaning |
|---|---|
| `f1` / `precision` / `recall` | every labeled criterion ran: a miss is a **judgment** miss |
| `routed_f1` / `routed_precision` / `routed_recall` | only what the routing chose (forced decisions count as `not_run`) |
| `routing_missed` | per criterion, gold pairs routing didn't run: `plan_dropped` (Plan agent, reason in `plan.notes`), `not_candidate` (rules never offered it), `funnel`, `no_claim` (the sentence never became a claim), `no_output` |
| `plan_dropped` | per criterion, just the Plan agent's drops |

In a normal run both views are the same. The extension (`server.py`, `api.py`) calls `run()`
without gold labels, so it is never forced. Forced runs go to `ablation_<model>_<time>_forced/`,
and a batch folder can't be resumed with a different setting.

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

## Automated tests
`python -m evaluation.run_all` runs, in one go: the unit tests, a format check of every gold
file, and RQ1-RQ3 on `datasets/gold_example.json` and `datasets/gold.json` (rules_only always;
the model modes only if the model backend answers). Report: `evaluation/outputs/report_<time>/report.md`.
Exit code 1 if a test fails or a gold file is malformed; `--min_f1 0.8` also fails it when
rules_only drops below 0.8 (a guard for detector changes). `--skip_eval` = tests and checks only.

## Gold set from real ChatGPT answers
65 real ChatGPT answers are collected (`datasets/candidates_*.json`: 50 from WildChat-1M, 15
from HC3) with blank labeling files in `datasets/annotation/`. Labeling rules, the merge and
adjudication steps: **[annotation_guide.md](annotation_guide.md)**. Tools:
`evaluation/datasets/collect.py` (download + filter + sample, `pip install pyarrow` for WildChat) and
`evaluation/labeling/annotate.py` (`sheet` / `status` / `merge`).

## Unit tests (no model)
`python -m unittest discover tests`: a scripted fake model checks the full flow,
rejection of an invented quote, judge revisions, rule fallback when the backend is down,
open criteria on unflagged sentences, the C1+C5 cap and the C2 funnel. `tests/test_c2.py`: the
C2 tolerances, API routing, cache, offline mode and the Check agent's C2 rules, with the APIs
answered by `tests/fake_stats.py`.

## Not done yet
Full list with priorities: *GiSuN: open problems and proposed solutions* (Fall 2026).
- C2: get the free BLS, Census and Data Commons keys; fill `data/stat_cache.json` on a machine
  with internet before HPC runs. The Data Commons calls are written from its v2 docs but not yet
  tried with a key. The headline US median household income (CPS ASEC) is not in the catalog. (#6)
- Label the 65 collected real ChatGPT answers (`datasets/annotation/`, see the guide), both
  of you with written guidelines; check agreement with `evaluation/labeling/agreement.py`. (#9, #10)
- RQ4: a C2 validation set: label measure / place / period / hedge and the decision per claim;
  step 1 is the hardest part, so measure it first. (#8)
- The Plan agent ranks nothing yet: the C2 funnel uses extract_claims' rule score. (#3)
- Loaded language: merge a larger lexicon (e.g. Recasens et al. 2013) into data/bias_wordlist.json. (#4)
- Extension: let the user overrule a decision and recompute with scoring.py.
