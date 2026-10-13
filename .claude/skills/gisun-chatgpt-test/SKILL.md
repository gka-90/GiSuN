---
name: gisun-chatgpt-test
description: Test GiSuN on real ChatGPT answers (WildChat / HC3 candidates) and run the full automatic check suite. Use when asked to test GiSuN on ChatGPT output, run the 50/65 prompts, check for false positives or misses, or test the code before a commit.
---

# GiSuN ChatGPT test

The repo already has real ChatGPT answers: `datasets/candidates_wildchat.json` (50) and
`datasets/candidates_hc3.json` (15), each `{id, domain, question, text}`. Use them; do not write
answers yourself and do not call ChatGPT.

Run everything from the repo root, with the project's Python environment (the one where
`pip install -r requirements.txt` was run).

## 1. Code checks
```bash
python -m evaluation.run_all
```
Unit tests, gold-file format checks, and RQ1-RQ3 (rules_only always; model modes only if the backend
answers). Report: `evaluation/outputs/report_<time>/report.md`.

## 2. Run GiSuN on the real ChatGPT answers
```bash
python .claude/skills/gisun-chatgpt-test/scripts/analyze.py datasets/candidates_wildchat.json datasets/candidates_hc3.json
```
Default `rules_only` (no model). Add `--mode full` to use the agents (needs Ollama or the HPC tunnel).
Report: `test_reports/chatgpt_<mode>.json` + `.md`.

## 2b. Agent modes with a bigger Qwen on the HPC
rules_only needs no model and runs anywhere. For `--mode full` use the HPC (32B on the 96 GB node):
```bash
sbatch hpc/run_chatgpt_test.slurm                          # Qwen2.5-32B, full + rules_only
MODES="full task_only" sbatch hpc/run_chatgpt_test.slurm   # several modes
squeue -u $USER ; tail -f logs/gisun-chatgpt_<jobid>.out
```
Results: `test_reports/chatgpt_<mode>_<model>.json`. Compare C3/C4 `met` counts and the examples
against `chatgpt_rules_only` — fewer false positives (e.g. "always consult a doctor", "Watergate scandal")
is the evidence that agents help. analyze.py refuses to run an agent mode if the model is unreachable.

## 3. Report to the user
Briefly: tests passed/failed; per domain the average claims and how many answers are high/medium/low;
the most-flagged terms (frequent terms are the likely false-positive sources); answers with numbers
but no C1 decision (possible misses). Quote the sentence for each example.

## Rules
- Never edit tests, gold labels, or candidate answers to make results look better.
- A failure caused by a missing package or an unreachable model is an environment problem: say so,
  don't change code for it.
- These answers are unlabeled; flags here are not accuracy. Accuracy comes from `datasets/gold.json`
  after both annotators label (`python -m evaluation.annotate`).
