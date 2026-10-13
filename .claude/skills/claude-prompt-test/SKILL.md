---
name: claude-prompt-test
description: Give Claude a set of test prompts, have Claude answer each one as a chatbot, record the answers, and run GiSuN on them. Use when asked to run the test prompts, generate chatbot answers, record answers, or test GiSuN with Claude.
---

# Claude prompt test

Claude answers 50 test prompts the way a general chatbot would, the answers are saved as a dataset,
and GiSuN is run on them. Run everything from the repo root.

## Prompts
`.claude/skills/claude-prompt-test/prompts.json` has 50 prompts in 7 categories:
statistics (10), sourced (5), controversial (10), absolute (5), causal (8), health_history (6), control (6).
`control` prompts (photosynthesis, Python loops) should get no flags; `statistics` answers should.
The user may give other prompts: add them to a copy of prompts.json with the same fields
(`id`, `category`, `prompt`) and pass that file with `--prompts`.

## Steps

1. Make the answer sheet (fails if it exists, so answers are never overwritten; use a new `--out` name for a new run):
   ```bash
   python .claude/skills/claude-prompt-test/scripts/sheet.py make --out datasets/collected/claude_<date>.md
   ```
2. Answer every prompt in the sheet, pasting each answer between its `<!-- ANSWER START -->` and
   `<!-- ANSWER END -->` markers. Write as a general chatbot answering a student, not as a coding assistant:
   - 120-300 words, prose or a short list, with the specific numbers, dates and claims such an answer
     normally has
   - no web search, no code, no mention of this repo, GiSuN, testing or this skill
   - do not deliberately add or avoid loaded words, sources or statistics; answer naturally
   - each answer independent of the others
   Work in batches of 10 and save the file after each batch, so a long run can resume.
3. Record the answers as a dataset:
   ```bash
   python .claude/skills/claude-prompt-test/scripts/sheet.py import datasets/collected/claude_<date>.md --provider claude --model "<model you are>"
   ```
   Writes `datasets/collected/claude_<date>.json` (`id, category, domain, question, text, provider, model`).
   Report how many prompts are still unanswered.
4. Run GiSuN on the recorded answers (uses the analysis script of the gisun-chatgpt-test skill):
   ```bash
   python .claude/skills/gisun-chatgpt-test/scripts/analyze.py datasets/collected/claude_<date>.json
   ```
   This is the quick rules_only pass (no model). The agent pass (Plan/Task/Judge with Qwen 32B) runs on
   the HPC: commit and push the json, then on the HPC login node
   `git pull && DATA=datasets/collected/claude_<date>.json sbatch hpc/run_chatgpt_test.slurm`.
   Tell the user these two commands; the agent report lands in `test_reports/claude_<date>_full_<model>.md`.
5. Report to the user: answers recorded; per category the average claims and high/medium/low counts;
   suspicious cases with the sentence quoted — any flag on a `control` answer (likely false positive),
   `statistics` answers with no C1 decision (likely miss), and the most-flagged terms.
   State that these are Claude-written answers, not real ChatGPT output.

## Rules
- Never edit recorded answers after import, or tests, to change results.
- Keep each run's sheet and json; they are the record of what Claude answered.
