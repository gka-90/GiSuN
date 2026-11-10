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
Unit tests, gold-file format checks, and RQ1-RQ3 (needs a model backend; without one only tests and checks run). Report: `evaluation/outputs/report_<time>/report.md`.

## 2. Run GiSuN on the real ChatGPT answers
```bash
python .claude/skills/gisun-chatgpt-test/scripts/analyze.py datasets/candidates_wildchat.json datasets/candidates_hc3.json
```
Default `--mode full` (needs Ollama or the HPC tunnel).
Report: `evaluation/outputs/chatgpt_<mode>.json` + `.md`.

## 2b. Agent modes with a bigger Qwen on the HPC
For `--mode full` use the HPC (32B on the 96 GB node):
```bash
sbatch hpc/run_chatgpt_test.slurm                          # Qwen2.5-32B, full
MODES="full task_only" sbatch hpc/run_chatgpt_test.slurm   # several modes
squeue -u $USER ; tail -f logs/gisun-chatgpt_<jobid>.out
```
Results: `evaluation/outputs/chatgpt_<mode>_<model>.json`. Compare `task_only` and `full`; each C2 result has `c2_status` and each decision `by` (agent, prefilter, failed). analyze.py refuses to run an agent mode if the model is unreachable.

## 3. Report to the user
Briefly: tests passed/failed; per domain the average claims and how many answers are high/medium/low;
the most-flagged terms (frequent terms are the likely false-positive sources); answers with numbers
but no C1 decision (possible misses). Quote the sentence for each example.

## Rules
- Never edit tests, gold labels, or candidate answers to make results look better.
- A failure caused by a missing package or an unreachable model is an environment problem: say so,
  don't change code for it.
- These answers are unlabeled; flags here are not accuracy. Accuracy comes from `datasets/gold.json`
  after both annotators label (`python -m evaluation.labeling.annotate`).
