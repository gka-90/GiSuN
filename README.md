# GiSuN

A Chrome extension that helps users engage more critically with AI chatbot output by detecting and highlighting unverified statistics and biased phrasing, and reinforcing critical-reading habits through short interactive exercises.

Built as a semester-long CS senior seminar project at Hamilton College.

## What it does

- **Detects** numeric/statistical claims and biased or contested phrasing in chatbot responses (currently targeting ChatGPT)
- **Highlights** flagged content directly on the page, with distinct visual styles for risk warnings vs. citations. Highlights are warnings ("worth checking"), not verdicts: the rules can't tell whether a claim is true
- **Deep check**: clicking a highlight runs the multi-agent pipeline on the whole answer and shows that claim's risk level and the reasons (C1-C6, see [PIPELINE.md](PIPELINE.md)). Only the C2 source check can say a source gives a different figure
- **Interacts** with the user via one of two modes: a quiet hover tooltip (citation mode) or a blocking modal (in-your-face mode)
- **Teaches** critical reading through a "Two Truths and a Lie" quiz on a topic (planned: generated from the chatbot's response itself; today `/quiz` only takes a topic)
- **Prebunks**: when a question is about medicine, history or politics, a banner above the answer warns about that topic's common pitfalls before the user reads it
- **Gates** first use: ChatGPT's input stays disabled until the user answers one critical-reading question correctly

## How it works

```
ChatGPT page                     Extension                           Backend (localhost:8000)
─────────────                    ─────────                           ────────────────────────
new assistant response  ──►  content.js                              server.py
                             observe_dom_for_new_response()          POST /verify
                             (waits 1.5s for streaming to finish)      ├─ detect_numeric_claims()
                                  │                                    └─ detect_bias_framing()
                                  ▼                                          │
                             background.js  ── POST {text} ──────────────────┘
                                  │         ◄─ {flags: [...]} ───────────────
                                  ▼
                             render_highlights()   → <mark> around each flag
                             handle_interaction_mode() → tooltip or modal

click a highlight       ──►  deepCheck()  ── POST /pipeline ──►          gisun/ pipeline (agents, C1-C6)
                             (once per answer, cached)  ◄─ poll GET /pipeline/{id} ─
                             panel: risk, reasons, sources
```

`/verify` drops loaded words that are negated, quoted or only mentioned ("not a crisis"), and the extension doesn't highlight bare years (they are context, not claims; the deep check still sees them). Highlighting everything trains users to ignore highlights.

If the backend isn't running, `background.js` falls back to a small built-in set of regexes and bias terms so the extension still highlights something, and the page shows a notice saying so. The fallback word list is much smaller than `bias_wordlist.json`.

### Agent layer → [PIPELINE.md](PIPELINE.md)

`/verify` stays model-free so highlights appear instantly. The model-based analysis is the **multi-agent pipeline** in `gisun/` (Plan / Task / Debug / Judge / Check agents, per-criterion decisions, deterministic scoring), served as `POST /pipeline` + `GET /pipeline/{id}` and called by the extension's deep check. See **[PIPELINE.md](PIPELINE.md)** for the design, criteria, run commands, the Hamilton HPC setup and evaluation.

The earlier single-agent `/analyze` (`agent/analyzer.py`, `agent/scanner.py`) has been removed. Its evaluation scripts and data are kept in `archive/eval/` (for reference only: they import the removed modules, so they no longer run), and its results in `output/` (`scan_eval_results.json`, `analyze_eval_*.json`, `context_eval_v1_prompt.json`): on 19 claims x 3 runs it matched the rule fallback 100% while taking ~8s vs ~2ms per response.

`agent/` now only holds the quiz agent (the pipeline doesn't do quizzes yet):

**`POST /quiz`** (`agent/quiz_agent.py`): Two Truths and a Lie, with self-checking instead of blind retries.
- The model submits through a `submit_quiz` tool. Each submission is checked for format (same rules as `quiz_generator._validate`, but explained), **focus** (the explanation has to be about the statement at `false_index`), and a **blind solve**: separate model calls see only the three statements and pick the lie (up to 3 calls at different temperatures, 2 must agree). If the majority picks a different one, or no two agree, the model is told and revises the same quiz.
- `verified: true` means a blind-solve majority agreed (every accepted model quiz). If it never passes, a curated quiz from `quiz_static.py` is used (matching the topic when one does) with `verified: false`, since it was never blind-solved. Same model for writing and solving, so their mistakes are correlated: a passed blind solve shows the lie is findable, not that the truths are true.

Small-model robustness built into the loop (`agent/core.py`): tool errors are returned to the model instead of raised; a tool call written as plain JSON text is recovered; when the model answers in prose it gets a nudge naming the next concrete step; a model repeating itself is stopped early; `num_ctx` is raised so the instructions aren't cut off.

Set the model with `GISUN_MODEL` (default `qwen2.5:1.5b` for `/quiz`; the pipeline's defaults are in `gisun/config.py`). **Use 3b or larger** if the machine can run it; 1.5b rarely completes a run and mostly ends in the fallback:
```bash
GISUN_MODEL=qwen2.5:3b uvicorn server:app --port 8000 --reload
```
Each model call times out after `GISUN_TIMEOUT` seconds (default 60); a timed-out quiz run ends in the curated fallback.

### Flag format

Every detector returns flags in the same shape, and `/verify` returns them sorted by position:

```json
{
  "sentence": "Unemployment hit 8.5% in 2020.",
  "matched_value": "8.5%",
  "start_index": 17,
  "end_index": 21,
  "type": "percentage"
}
```

- `type`: `percentage` | `percentage_points` | `dollar_amount` | `currency_amount` | `count` | `ratio` | `quantity` ("most Americans", "the majority of") | `year` | `bias_framing`
- `category`: only present on `bias_framing` flags (the word-list category)
- `start_index` / `end_index`: offsets into the response text, in **UTF-16 code units** so they match JavaScript string indexing (Python code-point offsets would drift after any emoji). `server.py` does this conversion.

## Tech stack

- Chrome Extension (Manifest V3), vanilla JavaScript
- `MutationObserver` for detecting new chatbot responses
- FastAPI + uvicorn for the local `/verify` backend
- Regex for numeric/statistic detection
- A curated JSON word list for bias/framing detection
- **Ollama running Qwen2.5 locally** (per course requirement — no cloud API, no account/API key needed) for quiz generation and the pipeline on a laptop
- **vLLM on the Hamilton CS HPC** (Qwen2.5-32B-Instruct-AWQ on an RTX PRO 6000) for evaluation runs; still self-hosted, no cloud API
- CSS for highlight and modal/tooltip styling

## Project status

### Done 9/26/2026
- [x] `detect_numeric_claims()` — Regex-based detection of percentages, dollar amounts, and years. No model needed, fast and stable. (Extended 10/1, see below.)
- [x] `detect_bias_framing()` — Word-list based detection (269 terms across 6 categories: political framing, emotionally charged language, event framing, absolutist claims, identity/group terms, vague or unsourced attribution; nested matches like "war on" inside "war on women" are collapsed to the longest one in `/verify`). No model needed.
- [x] `generate_quiz()` (Two Truths and a Lie) — Local Qwen2.5 generation with JSON cleanup, validation, retry (up to 2x), and fallback to a curated word bank. Extensively tested (~20 runs); `success_rate_test.py` measures model vs. fallback rates.

### Done 9/28/2026
- [x] `extract_claims()` — Tier 1 claim extraction (no LLM): groups flags by sentence, drops non-claims (questions, filler, advice), scores and de-duplicates the rest. Not wired into `/verify` yet.
- [x] Chrome extension (`extension/`) — `observe_dom_for_new_response()`, `render_highlights()`, `handle_interaction_mode()` (citation tooltip + in-your-face modal).
- [x] `server.py` — FastAPI `POST /verify` wrapping both detectors, returning flags in the shared format.
- [x] Updated for the 2026 ChatGPT layout (`chatgpt.com/uc/...`, `data-message-role="assistant"`, `data-assistant-markdown`); the old layout's selectors are still supported. Responses already on the page at load time are scanned too.

### Done 10/1/2026
- [x] Agent architecture (`agent/`): tool-calling loop with self-check and step trace. `POST /quiz` generates Two Truths and a Lie with format / focus / blind-solve checks and revision instead of blind retries. *(Also `POST /analyze`, which judged each claim using the detectors as tools: since removed and replaced by the pipeline; see below.)* `/verify` is unchanged.
- [x] Numeric edge cases: `detect_numeric_claims()` now also catches spelled-out percents, percentage/basis points, other currencies, "1.2 billion dollars", counts ("40,000", "3 million"), ratios ("one in three", "two-thirds of", "doubled", "3x"), decades and fiscal years; keeps ranges ("5-10%") and signs ("-3%") whole; reads "8,5%" as 8.5%; skips page/version numbers and "100% sure". Sentence splitting (`sentences.py`, shared by both detectors) no longer cuts at "U.S." / "Dr.". Source detection recognizes "(BLS, 2023)", footnotes "[1]", "The BLS reports...", "Source: ...", case-insensitive "According to", while "experts found" / "the report says" don't count. 60+ cases in `tests/test_numeric_edge_cases.py`.
- [x] Scan agent (`agent/scanner.py`, `/analyze` with `"scan": true`): the model proposes slanted wording the word list missed; each proposal must be quoted word-for-word from the text (offsets computed by code), 1-5 words, not already flagged, in one of the 6 categories, and gets `by: "agent"`. **Evaluated and turned off by default**: on 25 labeled sentences x 5 runs with qwen2.5:3b (`archive/eval/eval_scan.py`, draft labels), precision 0% and recall 0% -- it found none of the missed phrases (draconian, job-killing, so-called, ...) and its 25 accepted proposals were all false positives, mostly words next to existing word-list hits in quoted/negated sentences ("peaceful march", "historians still debate"). Removed with `/analyze` when the pipeline replaced it (evaluation kept in `archive/eval/`).
- Tested with qwen2.5:3b at the time: `/quiz` passed on 3/3 topics, one after a blind-solve rejection and revision. (`/analyze`, now removed, gave the same verdicts as the rules in 5/5 runs at ~14s per run; that result is why it was replaced.)

- [x] Prebunking banner (`extension/prebunk.js`): keyword match on the submitted question (Medicine / History / Politics), banner with that category's warnings inserted above the new response, close button, nothing shown when no category matches.
- [x] Gated access check (`extension/gate.js`): until `isPassed` is true in `chrome.storage.local`, the prompt box is disabled (and Enter / the send button blocked) behind a question modal; wrong answers keep it locked, the right one stores `isPassed` and unlocks. A MutationObserver re-disables the box when ChatGPT re-renders it. Both tested in headless Chrome on a mock page (25 checks); not yet on the live ChatGPT page.

### Done 10/4/2026
- [x] First pipeline run on the Hamilton CS HPC: Qwen2.5-32B-Instruct-AWQ served by vLLM 0.22.1 on one RTX PRO 6000 (cs-hpc-node-6). `hpc/run_eval.slurm` fixed for the cluster (paths under `/hpc/<name>`, offline model, no `nvcc` on the nodes, `logs/` folder). On the 4 example items `task_only` got 14/15 gold pairs right vs 12/15 for `rules_only`; the modes with the Plan agent skipped 5-9 pairs. Too few items to conclude anything (see PIPELINE.md).

### Also done 10/4/2026 (from *GiSuN: open problems and proposed solutions*)
- [x] #1 Claim coverage: in model modes every factual sentence is a claim and C3-C6 can run on it, not only sentences a regex or word-list term flagged (`GISUN_OPEN_CRITERIA`).
- [x] #2 Numbers: spelled-out numbers ("forty-two thousand", "forty percent"), quantity words ("most Americans", "the majority of"); `compare_numbers` reads them and "one in three". A line break now ends a sentence, so list items no longer merge (#16).
- [x] #3 Funnel: only the `GISUN_C2_MAX_CLAIMS` most check-worthy claims get the C2 source check; drops are logged in `plan.notes`. Bare years aren't highlighted.
- [x] #4 (part) `/verify` skips loaded words that are negated, quoted or only mentioned.
- [x] #5 C1 + C5 add at most 2 points together.
- [x] #7 C2 only compares against a source figure for the same year; a "contradicted" verdict needs a same-year source quote (rule and Check agent).
- [x] #10 (tool) `evaluation/agreement.py`: Cohen's kappa between two label files. Evaluation reports `not_run` pairs.
- [x] #11 `GISUN_JUDGE_MODEL`: the Judge can use a different model; the Slurm script can serve both.
- [x] #14 Highlight labels are worded as warnings, not verdicts.
- [x] #15 Deep check: click a highlight to run `/pipeline` on the answer and see that claim's risk and reasons.
- [x] #17 Notice on the page when the backend is offline and the fallback is used (fallback category name fixed).
- [x] #18 Self-test: a console warning when the page has conversation turns but no selector matches.
- [x] #20 README drift fixed (this section, `/analyze` entries, TODO list).

### TODO
- [ ] Data, labels and a decision (the highest-priority items): 50+ real answers labeled by both of us with guidelines (#9, #10), real reference data for 2-3 C2 domains (#6), and the product promise (#14). See "Not done yet" in PIPELINE.md.
- [ ] `fetch_citations()` — actually look up sources for flagged numbers outside the deep check (currently the highlight only says it's worth checking).
- [ ] Popup/options page to switch between citation and in-your-face mode and pick the deep-check mode (right now both live only in `chrome.storage.sync`: `mode`, default `citation`; `deepMode`, default `full`).
- [ ] Replace the placeholder gate question (`GATE_QUESTION` / `GATE_OPTIONS` / `GATE_CORRECT_INDEX` / `GATE_WRONG_MESSAGE` at the top of `extension/gate.js`).
- [ ] Prebunk: classify the question with the model instead of keywords (TODO in `extension/prebunk.js`).
- [ ] Labels: replace `datasets/gold_example.json` with 50+ real ChatGPT answers labeled independently by each of us (see PIPELINE.md). The draft labels in `archive/eval/` are by Claude, not by us.
- [ ] Quiz trigger in the extension UI (the `/quiz` endpoint exists).
- [ ] `/verify` still returns raw flags; only the pipeline uses `extract_claims()` (`gisun/preprocess.py`).

### Known limitations (documented, not bugs)
- Local model (Qwen2.5:1.5b/3b) output for quiz generation is not 100% reliable — roughly 1/4 to 1/3 of raw generations are fully clean; validation/retry/fallback handles this but cannot guarantee semantic correctness (e.g. `false_index` matching the explanation), only format correctness.
- Agent self-checks are mechanical: they catch verdicts with no detector evidence, ungrounded or copied reasons, and quizzes whose lie an independent reader can't find, but they can't prove a reason or quiz is actually correct. The model can also refuse a correct rejection (e.g. insisting "according to the Bureau of Labor Statistics" isn't a source), in which case rules decide that claim.
- Numbers: the highlight doesn't know about sources; the deep check's C1 looks for a source in the same and the two previous sentences, but not after the number ("14.8%. Source: BLS" on the next line isn't linked). Figures of speech that look like statistics ("gave half of the effort") are flagged too; a "not a claim" verdict was tried and removed because qwen2.5:3b used it to wave through real statistics. Plain small numbers ("3 cats"), temperatures and other units aren't detected. The extension's offline fallback in `background.js` still has only the old 3 patterns (the page now says when it's in use).
- Deep check on a laptop: the full pipeline with a 3B model can take minutes on a long answer (the extension waits up to 4). Set `chrome.storage.sync.set({deepMode: "rules_only"})` for an instant, model-free check, or point the backend at the HPC (PIPELINE.md).
- Quiz focus check (`_focus_problem` in `agent/quiz_agent.py`) compares content words between the explanation and each statement. If the explanation shares no content words with any statement, or ties between statements, it passes unchecked; only the blind solve can catch a mismatch then.
- Word-list bias detection cannot catch phrasing outside the list and is English-only. Negation / quotation / mention is caught by simple cues (a negator in the 4 words before, an open quote, "so-called", "the term"), not by understanding the sentence.
- ChatGPT changes its DOM often. If highlights stop appearing, the selectors at the top of `extension/content.js` (`RESPONSE_SELECTOR`, `MARKDOWN_SELECTOR`) are the first thing to check.

## Setup

### 1. Python environment
```bash
conda create -n ai-guardrail python=3.11
conda activate ai-guardrail
conda install pip
pip install -r requirements.txt
```
Already have the environment? Just run `conda activate ai-guardrail && pip install -r requirements.txt` (re-run it after pulling if `requirements.txt` changed).

### 2. Backend
Run from the project root and **keep this terminal open** while using the extension:
```bash
conda activate ai-guardrail
uvicorn server:app --port 8000 --reload
```
Check it's up by opening http://localhost:8000/docs (you can try `/verify` from there).

### 3. Local LLM (Ollama + Qwen) — needed for `/quiz` and `/pipeline` (except `mode: rules_only`)
```bash
brew install ollama
brew services start ollama
ollama pull qwen2.5:1.5b   # 8GB RAM machines
# or
ollama pull qwen2.5:3b     # 16GB RAM machines
```

### Tests (no model needed)
```bash
python -m unittest discover tests
```
Covers numeric detection edge cases, sentence splitting, source detection (`gisun/tools/attribution.py`), the quiz agent's self-checks, and the pipeline flow with a scripted fake model (`tests/test_pipeline.py`). Run it after touching any regex.

### 4. Chrome extension
1. Go to `chrome://extensions`
2. Turn on **Developer mode** (toggle in the top-right corner). The **Load unpacked** button only appears after this.
3. Click **Load unpacked** and select the **`extension/`** folder (not the project root — `manifest.json` lives in `extension/`)
4. Open [chatgpt.com](https://chatgpt.com) (refresh any tab that was already open). Answer the gate question first. Then ask something with numbers, e.g. *"Give me 3 statistics about US unemployment with years and percentages."* Highlights appear ~1.5s after the response finishes.
5. **Deep check:** click any highlight. A panel shows the claim's risk and reasons once the pipeline finishes (one run per answer; later clicks on the same answer are instant). With no model running, set `chrome.storage.sync.set({deepMode: "rules_only"})` in the extension's service worker console for an instant rules-only check.
6. **Modal mode:** `chrome.storage.sync.set({mode: "in_your_face"})` in the same console (back: `"citation"`).

After editing anything in `extension/`, click the ↻ reload button on the GiSuN card and refresh the ChatGPT tab.

## Troubleshooting

- **Reset the gate question** (to see it again) — open the extension's service worker console (link on the extension card) and run `chrome.storage.local.remove("isPassed")`, then refresh the ChatGPT tab.
- **Gate doesn't unlock typing / prebunk banner never appears** — ChatGPT changed its prompt box or send button; update `PROMPT_INPUT_SELECTOR` / `SEND_BUTTON_SELECTOR` at the top of `content.js`.

- **No highlights at all** — In the ChatGPT tab's DevTools console, run:
  ```js
  [document.querySelectorAll('[data-message-role="assistant"]').length, document.querySelectorAll('mark.gisun-flag').length]
  ```
  - First number is `0`: ChatGPT changed its layout; update `RESPONSE_SELECTOR` / `MARKDOWN_SELECTOR` in `content.js`.
  - First > 0, second `0`: check the **Errors** button on the extension card.
  - Chrome may ask you to type `allow pasting` before it lets you paste into the console.
- **Only a few bias words get flagged / "backend isn't running" notice** — the backend isn't reachable, so the extension is using its fallback. Open the extension's service worker console (link on the extension card) and look for `backend unreachable, using fallback flags`; start uvicorn (step 2).
- **Deep check says "failed" or takes very long** — the backend must be running; with `deepMode: "full"` it also needs a model (Ollama, step 3). Without one, every decision falls back to the rules after the model calls fail. Use `deepMode: "rules_only"` to test the panel without a model.
- **Console warns that no response matches `RESPONSE_SELECTOR`** — ChatGPT changed its layout; update the selectors at the top of `content.js`.
- **VS Code says `Import "fastapi" could not be resolved`** — select the `ai-guardrail` interpreter (Cmd+Shift+P → *Python: Select Interpreter*).

## Project structure

```
/
├── extension/
│   ├── manifest.json            # Extension config (Manifest V3)
│   ├── content.js               # DOM observer, highlighting, tooltip/modal, deep-check panel; page selectors
│   ├── prebunk.js               # Prebunking banner: category keywords + warnings
│   ├── gate.js                  # Gated access check before first use
│   ├── background.js            # Relays text to /verify and /pipeline (polls); fallback detectors if backend is down
│   └── styles.css               # Highlight, tooltip, modal styles
├── server.py                    # FastAPI backend: /verify, /quiz, + /pipeline router from gisun/api.py
├── PIPELINE.md                  # Multi-agent pipeline: design, criteria, run, evaluation
├── gisun/                       # Multi-agent pipeline
│   ├── pipeline.py              # Entry point (python -m gisun.pipeline), modes, phases
│   ├── api.py                   # POST /pipeline, GET /pipeline/{id} (background jobs + cache)
│   ├── preprocess.py            # Tier 1 detectors -> claims with context
│   ├── criteria.py              # C1-C6 criteria and their deterministic rules
│   ├── scoring.py               # Claim / response risk from criterion decisions
│   ├── llm.py, config.py        # Model backend (Ollama / OpenAI-compatible) and settings
│   ├── agents/                  # plan, task, debug, judge, check, loop, toolbox
│   └── tools/                   # attribution, language (context cues), numbers, retrieval
├── baseline/zero_tool.py        # One-call, no-tools baseline
├── evaluation/                  # evaluate.py (RQ1/RQ2), run_ablation.py (RQ3), agreement.py (Cohen's kappa)
├── datasets/gold_example.json   # 4 hand-made labeled items (to be replaced by 50+ real answers)
├── data/reference_corpus.json   # Sample reference corpus for C2 retrieval
├── hpc/run_eval.slurm           # Hamilton HPC (vLLM) evaluation job, see PIPELINE.md
├── logs/                        # Slurm job logs (folder must exist before sbatch)
├── agent/                       # Quiz only (the pipeline doesn't do quizzes yet)
│   ├── core.py                  # Tool-calling loop with self-check + trace, model call timeout
│   └── quiz_agent.py            # /quiz: Two Truths and a Lie with blind-solve check
├── archive/
│   └── eval/                    # Evaluation of the removed /analyze + scan agents (evidence for the report)
├── requirements.txt             # Python dependencies
├── detect_numeric_claims.py     # Regex-based numeric/stat detection
├── detect_bias_framing.py       # Word-list based bias detection
├── bias_wordlist.json           # Curated word list (269 terms, 6 categories)
├── sentences.py                 # Sentence splitting shared by both detectors
├── extract_claims.py            # Tier 1 claim extraction from flags
├── tests/
│   ├── test_numeric_edge_cases.py  # Detection / sentence / source edge cases
│   ├── test_agent_checks.py     # Quiz agent: blind solve, majority vote, fallback
│   └── test_pipeline.py         # Pipeline flow with a scripted fake model
├── two_truths_one_lie/
│   ├── quiz_generator.py        # Two Truths and a Lie: Qwen call + validation + fallback
│   ├── quiz_static.py           # Fallback word bank only (no model call), for reliable demos
│   └── success_rate_test.py     # Measures model vs. fallback success rates
├── output/                      # JSON results from the scripts above (incl. archived /analyze evals)
└── outputs/                     # Pipeline run results (python -m gisun.pipeline)
```

## Team

Two-person team, Hamilton College CS Senior Seminar, Fall 2026.

## License

Course project — not licensed for external use.
