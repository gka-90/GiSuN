# GiSuN

A Chrome extension that helps users engage more critically with AI chatbot output by detecting and highlighting unverified statistics and biased phrasing, and priming critical reading with a prebunking banner and a one-time gate question.

Built as a semester-long CS senior seminar project at Hamilton College.

## What it does

- **Detects** numeric/statistical claims and biased or contested phrasing in chatbot responses (currently targeting ChatGPT)
- **Highlights claims chosen by the agents**: when an answer finishes, the multi-agent pipeline checks every claim against C1-C6 (see [docs/PIPELINE.md](docs/PIPELINE.md)); the claims it flags are underlined in their risk colour, and the exact words the agents pointed to ("job-killing", "12%") are filled in. Claims with no problem stay unmarked. Hover for the reasons, click for the full verdict. Highlights are warnings ("worth checking"), not verdicts; only the C2 source check can say a source gives a different figure
- **Falls back to rule highlights** (numbers and listed words, instant) when the agents can't run, and says so under the answer
- **Interacts** with the user via one of two modes: a quiet hover tooltip (citation mode) or a blocking modal (in-your-face mode)
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
```

That diagram is the **fallback**. Normally the agents decide the highlights:

```
new assistant response  ──►  processResponse(): "GiSuN is checking the claims in this answer…"
                                  │  POST /pipeline {text, question}  ──►  gisun/ pipeline (agents, C1-C6)
                                  │  ◄── poll GET /pipeline/{id} until done (one answer at a time)
                                  ▼
                             render_claims()  → underline medium/high-risk claim sentences,
                                                fill in the words the agents quoted as evidence
                             status note: "GiSuN: 3 claims worth checking (1 high risk)"
                             hover = reasons, click = panel with the full verdict and source quotes
                             (if /pipeline fails: the /verify rule highlights above, with a note)
```

With a model on the HPC (docs/PIPELINE.md, "Use the HPC model from a laptop") an answer takes roughly 10-40 s; with no model reachable, the pipeline's rules decide every criterion (a few seconds) and the note says so.

`/verify` drops loaded words that are negated, quoted or only mentioned ("not a crisis"), and the rule highlights skip bare years (they are context, not claims). Highlighting everything trains users to ignore highlights.

If the backend isn't running, `background.js` falls back to a small built-in set of regexes and bias terms so the extension still highlights something, and the page shows a notice saying so. The fallback word list is much smaller than `bias_wordlist.json`.

### Agent layer → [docs/PIPELINE.md](docs/PIPELINE.md)

`/verify` stays model-free so highlights appear instantly. The model-based analysis is the **multi-agent pipeline** in `gisun/` (Plan / Task / Debug / Judge / Check agents, per-criterion decisions, deterministic scoring), served as `POST /pipeline` + `GET /pipeline/{id}`, which the extension calls for every answer. See **[docs/PIPELINE.md](docs/PIPELINE.md)** for the design, criteria, run commands, the Hamilton HPC setup and evaluation.

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

- `type`: `percentage` | `percentage_points` | `dollar_amount` | `currency_amount` | `count` | `ratio` | `quantity` ("most Americans", "nearly half", "tens of thousands") | `score` (polls, ratings, sports: "rated 4.7 stars", "a 10-2 record") | `statistic` (research: "p < 0.05", "n = 1,200") | `ranking` ("top 10", "the second-largest") | `year` | `bias_framing`
- What counts as a statistic follows *Statistic Formats for Claim Detection* (Oct 5, 2026): its examples are tests in `tests/test_numeric_edge_cases.py` (131 of its 140 positive examples are caught; the rest, like a bare "about 500" or "twenty-five", are left out on purpose, and none of its look-alikes are flagged)
- `category`: only present on `bias_framing` flags (the word-list category)
- `start_index` / `end_index`: offsets into the response text, in **UTF-16 code units** so they match JavaScript string indexing (Python code-point offsets would drift after any emoji). `server.py` does this conversion.

## Tech stack

- Chrome Extension (Manifest V3), vanilla JavaScript
- `MutationObserver` for detecting new chatbot responses
- FastAPI + uvicorn for the local `/verify` backend
- Regex for numeric/statistic detection
- A curated JSON word list for bias/framing detection
- **Ollama running Qwen2.5 locally** (per course requirement — no cloud API, no account/API key needed) for the pipeline on a laptop
- **vLLM on the Hamilton CS HPC** (Qwen2.5-32B-Instruct-AWQ on an RTX PRO 6000) for evaluation runs; still self-hosted, no cloud API
- CSS for highlight and modal/tooltip styling

## Project status

Done so far (details in git history and docs/PIPELINE.md):
- Tier 1 detectors: numbers and statistics (131/140 examples of *Statistic Formats for Claim Detection*), bias word list (269 terms), sentence splitting, source detection.
- Chrome extension: agent-decided highlights, citation / in-your-face modes, prebunking banner, gate question.
- Multi-agent pipeline (Plan / Task / Check / Debug / Judge) on C1-C6 with deterministic scoring, served by `/pipeline`; runs on the Hamilton HPC (Qwen2.5-32B-Instruct-AWQ, vLLM).
- C2 checks numbers against official statistics (BLS, Census, World Bank, Data Commons), cached, with hedge-aware tolerances. API keys go in `.env` (git-ignored).
- Evaluation: 184 agent decisions on 50 Claude answers labeled by both of us (disagreements settled 10/27); public test sets for C1, C2, C3, C5, C6; our own insertion set including C4.
- First full gold runs (11/3/2026, Qwen2.5-32B, full mode): on our 184 labeled rows precision 0.59 (C6 worst: 28 of 34 flags wrong); on public part 1 precision 0.71 but recall 0.17, because the Plan agent dropped 261 of 367 gold pairs. Details in docs/PIPELINE.md, "First full gold runs".
- Fixes after that run (11/4/2026): the C3-C6 guidance now follows docs/labeling_rules.md word for word; a C6 pre-filter decides headings, fragments and reported viewpoints ("Critics argue...") without the agent; the Plan agent can no longer drop C1 for a sentence with a number or C5 for "is believed / is regarded as / allegedly / studies show"; `GISUN_FORCE_CRITERIA=1` makes every labeled criterion run, and the evaluation reports routed vs forced numbers and how many gold pairs the Plan agent dropped per criterion; new test sets `datasets/gold_c4_logic.json` (LOGIC, 100 faulty generalizations vs 100 other fallacies, built by Gideon; false causality and slippery slope left out) and `datasets/gold_c2_us.json` (QuanTemp claims the series catalog can look up: none).
- Two Truths and a Lie was built as a separate agent and removed on 11/3/2026 (it was never connected to the extension); see git history before that date.

### TODO
- [ ] Speed: an answer takes roughly 10-40 s on the HPC model (one model conversation per claim and criterion). Ideas: one call per sentence for C3-C6, `task_only` in the extension, more parallel requests, showing claims as they finish.
- [ ] Suggestions for unsourced numbers (where to look), instead of only "no source".
- [ ] Popup/options page to switch between citation and in-your-face mode and pick the deep-check mode (right now both live only in `chrome.storage.sync`: `mode`, default `citation`; `deepMode`, default `full`).
- [ ] Replace the placeholder gate question (`GATE_QUESTION` / `GATE_OPTIONS` / `GATE_CORRECT_INDEX` / `GATE_WRONG_MESSAGE` at the top of `extension/gate.js`).
- [ ] Prebunk: classify the question with the model instead of keywords (TODO in `extension/prebunk.js`).
- [ ] Re-run the 50 answers on the HPC with the C2 API keys and label the C2 decisions.
- [ ] Rerun after the 11/4 changes: `gold_answers.json` (normal routing), `gold_public_1.json` with `FORCE=1`, `gold_c4_logic.json` (commands in docs/PIPELINE.md, "On the Hamilton CS HPC"). Then parts 2 and 3.
- [ ] C2 test set from the catalog's own measures: QuanTemp has no claim the catalog can check (0 of 200), so it can't measure C2.
- [ ] Settle three labels that contradict docs/labeling_rules.md (two C4 rows, one C6 fragment; listed in docs/PIPELINE.md, "Not done yet"), and add the agentless C5 cues ("is considered", "is regarded as", "allegedly") to the C5 rules.
- [ ] Spot-check the LOGIC C4 labels: about 10 of the 50 "faulty generalization" items are slippery-slope arguments.
- [ ] `/verify` still returns raw flags; only the pipeline uses `extract_claims()` (`gisun/preprocess.py`).

### Known limitations (documented, not bugs)
- Agent self-checks are mechanical: they catch verdicts with no detector evidence, ungrounded or copied reasons, but they can't prove a reason is actually correct. The model can also refuse a correct rejection (e.g. insisting "according to the Bureau of Labor Statistics" isn't a source), in which case rules decide that claim.
- Numbers: the highlight doesn't know about sources; the deep check's C1 looks for a source in the same and the two previous sentences, but not after the number ("14.8%. Source: BLS" on the next line isn't linked). Figures of speech that look like statistics ("gave half of the effort") are flagged too; a "not a claim" verdict was tried and removed because qwen2.5:3b used it to wave through real statistics. Plain small numbers ("3 cats"), temperatures and other units aren't detected. The extension's offline fallback in `background.js` still has only the old 3 patterns (the page now says when it's in use).
- Agent highlights on a laptop: the full pipeline with a 1.5-3B model can take minutes per answer (the extension waits up to 4, and checks one answer at a time). Point the backend at the HPC model (docs/PIPELINE.md), or set `chrome.storage.sync.set({deepMode: "rules_only"})` for model-free, rules-decided highlights.
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

### 3. Local LLM (Ollama + Qwen) — needed for `/pipeline`
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
Covers numeric detection edge cases, sentence splitting, source detection (`gisun/tools/attribution.py`), C2 lookups and comparisons, the pipeline flow with a scripted fake model (`tests/test_pipeline.py`), the C6 pre-filter and guidance (`tests/test_c6.py`), guidance vs the labeling rules (`tests/test_labeling_rules.py`), forced criteria (`tests/test_forced.py`), the Plan agent's keep rule (`tests/test_plan_keep.py`) and the two test-set scripts (offline). Run it after touching any regex. `python -m pytest -q` runs the same tests.

### 4. Chrome extension
1. Go to `chrome://extensions`
2. Turn on **Developer mode** (toggle in the top-right corner). The **Load unpacked** button only appears after this.
3. Click **Load unpacked** and select the **`extension/`** folder (not the project root — `manifest.json` lives in `extension/`)
4. Open [chatgpt.com](https://chatgpt.com) (refresh any tab that was already open). Answer the gate question first. Then ask something with numbers, e.g. *"Give me 3 statistics about US unemployment with years and percentages."* Highlights appear ~1.5s after the response finishes.
5. **Agent highlights:** under each answer a note says "GiSuN is checking the claims in this answer…"; when the agents finish, the flagged claims are underlined (hover = reasons, click = full verdict). For real agent decisions a model must be running (step 3, or the HPC model, docs/PIPELINE.md); without one the rules decide. `chrome.storage.sync.set({deepMode: "rules_only"})` in the extension's service worker console skips the model entirely.
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
- **Only "basic rule highlights" / "agents couldn't check this answer"** — `/pipeline` failed: is the backend running (step 2)? The note under the answer gives the error.
- **"Checking…" for a long time** — the agents are slow with a small laptop model, and answers are checked one at a time. Use the HPC model, or `deepMode: "rules_only"` to test without a model.
- **Console warns that no response matches `RESPONSE_SELECTOR`** — ChatGPT changed its layout; update the selectors at the top of `content.js`.
- **VS Code says `Import "fastapi" could not be resolved`** — select the `ai-guardrail` interpreter (Cmd+Shift+P → *Python: Select Interpreter*).

## Project structure

```
/
├── README.md
├── server.py                    # FastAPI backend (uvicorn server:app): /verify + /pipeline from gisun/api.py
├── requirements.txt
│
├── gisun/                       # The checker: Tier 1 detectors + multi-agent pipeline
│   ├── detectors/               # Tier 1, no model
│   │   ├── numeric.py           #   detect_numeric_claims(): percentages, amounts, counts, ratios, years
│   │   ├── bias.py              #   detect_bias_framing(): word-list matching (data/bias_wordlist.json)
│   │   ├── claims.py            #   extract_claims(): flags -> scored, de-duplicated claims
│   │   └── sentences.py         #   sentence splitting shared by the detectors
│   ├── preprocess.py            # detectors -> claims with context and attribution
│   ├── criteria.py              # C1-C6 criteria and their deterministic rules
│   ├── agents/                  # plan, task, debug, judge, check, loop, toolbox
│   ├── tools/                   # attribution, language (context cues), numbers (C2 tolerances), retrieval (statistics APIs)
│   ├── scoring.py               # claim / response risk from criterion decisions
│   ├── pipeline.py              # entry point (python -m gisun.pipeline), modes, phases
│   ├── api.py                   # POST /pipeline, GET /pipeline/{id} (background jobs + cache)
│   └── llm.py, config.py        # model backend (Ollama / OpenAI-compatible) and settings
│
├── extension/                   # Chrome extension (Manifest V3): background.js, content.js, prebunk.js, gate.js, styles.css
│
├── data/                        # Data the code reads at run time
│   ├── bias_wordlist.json       #   curated word list (269 terms, 6 categories)
│   ├── stat_series.json         #   which official series (BLS, Census, World Bank, Data Commons) answers which C2 measure
│   └── stat_cache.json          #   cached API responses with their query dates
│
├── evaluation/                  # Measuring GiSuN
│   ├── evaluate.py              #   RQ1/RQ2: criterion accuracy / P / R / F1, risk agreement
│   ├── run_ablation.py          #   RQ3: full / no_judge / no_debug / task_only
│   ├── run_all.py               #   tests + gold-file checks + RQ1-RQ3 in one go
│   ├── zero_tool.py             #   one-call, no-tools baseline
│   ├── datasets/                #   build test sets: collect, external_testset, own_insertion_set, c4_testset,
│   │                            #   c2_us_testset (-> gold_c2_us.json)
│   └── labeling/                #   annotate, worksheets (make_worksheet, make_agent_worksheet, split_worksheet),
│                                #   agreement (Cohen's kappa), finalize_labels
├── datasets/                    # Only what runs need: gold_example.json (tests, run_all),
│                                #   collected/claude_2026-10-12.json (the 50 answers the HPC run checks),
│                                #   gold_answers.json, gold_labels_combined.json, gold_public_{1,2,3}.json,
│                                #   gold_combined.json, gold_c4_logic.json, gold_c2_us.json (HPC gold sets).
│                                #   Everything else (labels, C4 and insertion sets, candidates) was moved out
│                                #   of the repo on 11/3/2026; it is in git history before that date.
├── tests/                       # Unit tests, no model (python -m unittest discover tests)
├── hpc/                         # Hamilton HPC Slurm jobs (vLLM), see docs/PIPELINE.md
│
├── docs/
│   ├── PIPELINE.md              # Multi-agent pipeline: design, criteria, run, evaluation
│   ├── labeling_rules.md        # Strict per-criterion labeling rules
│   └── annotation_guide.md      # Gold-set annotation workflow (merge, adjudication)
│
├── logs/                        # Slurm job logs (folder must exist before sbatch)
└── .env                         # API keys (git-ignored, create it yourself; see gisun/config.py)

Run results go to evaluation/outputs/ (git-ignored). Raw downloads (HC3, WildChat) go to datasets/raw/
(git-ignored); evaluation/datasets/collect.py re-downloads them if needed. Scripts in evaluation/datasets/ and
evaluation/labeling/ read files that are no longer in datasets/: copy them back before running those.
```

## Team

Two-person team, Hamilton College CS Senior Seminar, Fall 2026.

## License

Course project — not licensed for external use.
