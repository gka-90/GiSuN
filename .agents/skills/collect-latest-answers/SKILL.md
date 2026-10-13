---
name: collect-latest-answers
description: Collect answers from the latest OpenAI model to the GiSuN test questions by running each question in a fresh, isolated `codex exec` session, record them as a dataset, and run GiSuN on them. Use when asked to get current/latest model answers, re-ask the 65 questions, or build test data with Codex.
---

# Collect latest-model answers

Each question is sent to a **new** `codex exec` session started in an empty folder, so every answer is
independent and sees nothing from this repo. Answers come from the model your Codex login uses
(the latest OpenAI model unless you pass `--model`). No API key is needed.

## Steps (run from the repo root)

1. Try 3 questions first:
   ```bash
   python .agents/skills/collect-latest-answers/scripts/collect_codex.py --limit 3
   ```
   Defaults: questions from `datasets/prompts_same_as_candidates.json` (the same 65 WildChat/HC3
   questions, so old and new answers can be compared), output
   `datasets/collected/codex_latest_<date>.json`. It resumes: answered ids are skipped.
2. If those look like normal chatbot answers, run the rest (drop `--limit`). Report progress and any failures.
   Options: `--model <name>`, `--prompts <file>`, `--out <file>`, `--timeout 300`.
3. Quick rules-only check on the laptop:
   ```bash
   python .claude/skills/gisun-chatgpt-test/scripts/analyze.py datasets/collected/codex_latest_<date>.json
   ```
4. Agent analysis on the HPC (tell the user): commit and push the json, then on the HPC
   `git pull && DATA=datasets/collected/codex_latest_<date>.json sbatch hpc/run_chatgpt_test.slurm`.
5. Report: answers collected / failed, model name recorded, and that these are answers from
   `codex exec` (latest OpenAI model, Codex's own system prompt), not the chatgpt.com web app.

## Rules
- Never answer the questions yourself and never edit recorded answers; only the script writes them.
- Each `codex exec` runs read-only (`--sandbox read-only`) in an empty temp folder with `--ephemeral`.
- If `codex` is not on PATH or not logged in, stop and tell the user to run `codex login`.
