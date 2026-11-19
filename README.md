# GiSuN

A Chrome extension that helps people read chatbot answers critically. When ChatGPT finishes an answer, GiSuN checks each claim for six common problems, opens the sources the answer cites to see whether its numbers are really there, compares numbers with official statistics, and highlights what is worth a second look.

Built by Gideon Kobea and Suning Hong for the CS Senior Seminar at Hamilton College, Fall 2026.

## What it checks

Every sentence is checked against six criteria (C1–C6). "Met" always means the problem is there.

| | Question | Example |
|---|---|---|
| **C1** | Does it say where the number came from? | "averaged 12%" with no source |
| **C2** | Is the number actually right? | BLS says 8.1%, not 12% |
| **C3** | Does the wording take a side? | "job-killing" |
| **C4** | Does it claim "always" or "everyone" without support? | "everyone agrees" |
| **C5** | Does it hide behind "experts say"? | "studies show", "is widely considered" |
| **C6** | Does it claim cause and effect without evidence? | "the lockdowns caused it" |

C3 and C4 adapt to the reader: a 5-question quiz when the extension is set up picks strict rules (C3 and C4 shown separately) or general rules (one "worth checking" flag).

### Checking a number: three steps

The question a reader actually has about a number is "is it really in the source it cites, and is it right?" GiSuN answers it in three steps:

```
  number in the answer
        │
  1. C1  Is there a source?            text only (agent): a cited link, a named organisation,
        │                                a source list at the end, or nothing / something vague
        │
  2. Citation check  Is the number      code only, no model: the extension sends the answer's links
        │  on the cited page?              (ChatGPT's citation chips); the backend opens each page
        │                                  (HTML or PDF) and looks for the number, rounded to the
        │                                  claim's precision -> found / not found / couldn't open
        │
  3. C2  Does it match official data?   agent pins down measure, place and period; code compares
                                           with BLS, Census, FRED, CDC, World Bank or Data Commons.
                                           If the answer cites one of those sites, C2 checks that
                                           source first.
```

The user sees two lines per number:

- **Source:** found on the cited page / not found on the cited page / couldn't open it / named but no link / no source
- **Official data:** matches / conflicts / couldn't be checked

The strongest warning is a number that cites a source, isn't on that page, and conflicts with official data.

The three steps answer different questions. The citation check says whether the answer **quotes its source faithfully**; C2 says whether the number is **actually right**, and still works when there is no link, when the cited page is a blog or an old article, and when the wording needs tolerance rules ("about 4%", "more than 3 million"). Neither step lets a model decide whether two numbers match: that is always code.

## How it works

```
ChatGPT answer ──► extension (content.js)
                     │  text + question + links with their positions
                     ▼
                   backend (server.py, localhost:8000)
                     POST /pipeline ──► gisun/pipeline.py
                        preprocess      detectors, sentences, sources named in the text, links -> sentences
                        Plan agent      which criteria for which sentence
                        Task agents     C1–C6 with tools; Check rejects decisions the evidence doesn't back;
                                        Debug retries failures; Judge reviews
                        citation check  open the cited pages, look for the numbers (no model)
                        scoring         claim risk + the two lines per number
                     ◄── poll GET /pipeline/{id}
                     ▼
                   highlights: risky claims underlined; hover = reasons; click = full verdict,
                   source lines and official figures
```

The model is Qwen2.5-32B-Instruct-AWQ served with vLLM on the Hamilton CS HPC (or a small Qwen2.5 through Ollama on a laptop). Everything is self-hosted: no cloud model API. An answer takes roughly 10–40 seconds on the HPC model, about 7–12 seconds per claim.

When the agents can't run, `/verify` gives instant rule-only highlights (numbers and a 269-term word list) and the page says so. Design, criteria, tools and run commands are in **[docs/PIPELINE.md](docs/PIPELINE.md)**; labeling rules are in **[docs/labeling_rules.md](docs/labeling_rules.md)**.

## Results so far

All runs: Qwen2.5-32B-Instruct-AWQ on the Hamilton HPC.

**C2 on a test set built from official figures** (`datasets/gold_c2_catalog.json`, 180 sentences: each official figure written exact, 20% off, "about" and "more than" variants): precision 1.00, recall 0.97, **F1 0.98**. No number was ever judged in the wrong direction; the 8 misses were "couldn't decide".

**C2 on real answers:** of 68 numeric claims in 50 Claude answers, 2 could be checked against an official figure; 65% of the rest are measures outside the catalog (vaccine effectiveness, polls, crime, home prices). This is why the citation check was added.

**C1 on public sentences** (`gold_public_1.json`, 67 rows): F1 **0.65 → 0.75–0.81** after counting Wikipedia-style "(Source: …)" citations as sources, treating encyclopedia-style numbers as statistics, and rejecting a "no source" decision when the source detector finds one. The C1 labels of this set were relabeled by our rules (AI-assisted, reviewed by Suning; 11 of 67 changed); against the original labels the latest run scores 0.75, against ours 0.81.

**C3, C5, C6 on public sentences:** precise but conservative (precision 0.80–1.00, recall 0.21–0.32). Most misses come from the model applying a narrower definition than our rules, e.g. not counting "is generally considered" as vague attribution.

## Project status

Done:
- Detectors: numbers and statistics (131/140 examples of *Statistic Formats for Claim Detection*), 269-term bias word list, sentence splitting, source detection (including "(Source: …)" citations and "an assessment by X").
- Multi-agent pipeline (Plan / Task / Check / Debug / Judge) on C1–C6 with deterministic scoring, served by `/pipeline`.
- C2 against six official sources (BLS, Census, FRED, CDC, World Bank, Data Commons; 43 series), cached, with hedge-aware tolerances and a reason code for every undecided result.
- Citation check: links in the answer are tied to their sentences, the cited pages are opened, and the numbers are looked up by code (`gisun/tools/citations.py`).
- Extension: agent-decided highlights, details panel with the two source lines, citation / in-your-face modes, C3/C4 calibration quiz, prebunking banner, gate question.
- Evaluation: our 50 Claude answers labeled by both of us; public test sets for C1, C2, C3, C5, C6; LOGIC set for C4; the 180-sentence C2 set.

### TODO (v1.0)
- [ ] Test the citation check on the live ChatGPT page: confirm the citation chips are `<a href>` links inside the answer (`collectCitations()` in `extension/content.js`).
- [ ] C2: record a span of years ("during his eight years in office") as undecided instead of forcing a single-year comparison, and act on the Judge's objections.
- [ ] C2: map measure names the agent writes differently ("car accident deaths" → motor vehicle traffic deaths); add state unemployment from BLS directly; add FRED and CDC series to the 180-sentence test set.
- [ ] C1: reject "no source" when a citation ends the same sentence, without the current escape hatch; reword the guidance so "reference facts" isn't read as "no source needed".
- [ ] C5: make the agent address "is considered / allegedly" phrases the detector already finds (same kind of check as C1).
- [ ] Rerun `gold_answers.json` and public parts 2 and 3 with the current code (held-out check of the C1 changes).
- [ ] List the sources of the non-C2 rows of `gold_public_{1,2,3}.json`.
- [ ] Speed: one call per sentence for C3–C6, more parallel requests, show claims as they finish.
- [ ] Replace the placeholder gate question (top of `extension/gate.js`); options page for the modes.

### Known limitations
- The citation check finds a number on the cited page; it can't tell whether that number means the same thing. Pages behind a login or paywall, scanned PDFs and pages built by JavaScript can't be read ("couldn't open it").
- C2 covers official recurring statistics only (43 series). One-off studies, polls and viral claims are outside it by design.
- For C1 and C3–C6 the model makes the final call; the checks can reject decisions without evidence, but a model can still argue its way to the wrong answer. Only C2's comparison is decided by code.
- ChatGPT changes its page layout often. If highlights or links stop working, check the selectors at the top of `extension/content.js`.

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
Covers numeric detection edge cases, sentence splitting, source detection (`gisun/tools/attribution.py`), C2 lookups and comparisons, the pipeline flow with a scripted fake model (`tests/test_pipeline.py`), the C6 pre-filter and guidance (`tests/test_c6.py`), the citation check (`tests/test_citations.py`), guidance vs the labeling rules (`tests/test_labeling_rules.py`), forced criteria (`tests/test_forced.py`), the Plan agent's keep rule (`tests/test_plan_keep.py`) and the two test-set scripts (offline). Run it after touching any regex. `python -m pytest -q` runs the same tests.

### 4. Chrome extension
1. Go to `chrome://extensions`
2. Turn on **Developer mode** (toggle in the top-right corner). The **Load unpacked** button only appears after this.
3. Click **Load unpacked** and select the **`extension/`** folder (not the project root — `manifest.json` lives in `extension/`)
4. Open [chatgpt.com](https://chatgpt.com) (refresh any tab that was already open). Answer the gate question first. Then ask something with numbers, e.g. *"Give me 3 statistics about US unemployment with years and percentages."* Highlights appear ~1.5s after the response finishes.
5. **Agent highlights:** under each answer a note says "GiSuN is checking the claims in this answer…"; when the agents finish, the flagged claims are underlined (hover = reasons, click = full verdict). A model must be running for this (step 3, or the HPC model, docs/PIPELINE.md): every decision comes from the agents, and without a model only the basic rule highlights appear.
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
- **"Checking…" for a long time** — the agents are slow with a small laptop model, and answers are checked one at a time. Use the HPC model, or `deepMode: "task_only"` for fewer model calls.
- **Console warns that no response matches `RESPONSE_SELECTOR`** — ChatGPT changed its layout; update the selectors at the top of `content.js`.
- **VS Code says `Import "fastapi" could not be resolved`** — select the `ai-guardrail` interpreter (Cmd+Shift+P → *Python: Select Interpreter*).

## Project structure

```
/
├── README.md
├── LICENSE                      # MIT (code and our own data; third-party data keeps its own terms)
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
│   ├── criteria.py              # C1-C6 criteria: question, guidance and tools for the agents
│   ├── agents/                  # plan, task, debug, judge, check, loop, toolbox
│   ├── tools/                   # attribution, citations (open cited pages), language, numbers (C2 tolerances), retrieval (statistics APIs)
│   ├── scoring.py               # claim / response risk from criterion decisions
│   ├── pipeline.py              # entry point (python -m gisun.pipeline), modes, phases
│   ├── api.py                   # POST /pipeline, GET /pipeline/{id} (background jobs + cache)
│   └── llm.py, config.py        # model backend (Ollama / OpenAI-compatible) and settings
│
├── extension/                   # Chrome extension (Manifest V3): background.js, content.js, prebunk.js, gate.js, styles.css
│
├── data/                        # Data the code reads at run time
│   ├── bias_wordlist.json       #   curated word list (269 terms, 6 categories)
│   ├── stat_series.json         #   which official series (BLS, Census, FRED, CDC, World Bank, Data Commons) answers which C2 measure
│   └── stat_cache.json          #   cached API responses with their query dates
│
├── evaluation/                  # Measuring GiSuN
│   ├── evaluate.py              #   RQ1/RQ2: criterion accuracy / P / R / F1, risk agreement
│   ├── run_ablation.py          #   RQ3: full / no_judge / no_debug / task_only
│   ├── run_all.py               #   tests + gold-file checks + RQ1-RQ3 in one go
│   ├── zero_tool.py             #   one-call, no-tools baseline
│   ├── c2_report.py             #   the C2 results (built test set + real answers) in one screen
│   ├── status_report.py        #   any run: decisions per criterion, and why the undecided ones are undecided
│   └── datasets/                #   c2_catalog_testset (-> gold_c2_catalog.json), c2_us_testset (-> gold_c2_us.json)
├── datasets/                    # Only what runs need: gold_example.json (tests, run_all),
│                                #   collected/claude_2026-10-12.json (the 50 answers the HPC run checks),
│                                #   gold_answers.json, gold_labels_combined.json, gold_public_{1,2,3}.json,
│                                #   gold_combined.json, gold_c4_logic.json, gold_c2_us.json, gold_c2_catalog.json (HPC gold sets),
│                                #   gold_public_1_c1_ours.json and relabel/ (C1 rows relabeled by our rules).
│                                #   Everything else (labels, C4 and insertion sets, candidates) was moved out
│                                #   of the repo on 11/3/2026; it is in git history before that date.
├── tests/                       # Unit tests, no model (python -m unittest discover tests)
├── hpc/                         # Hamilton HPC Slurm jobs (vLLM), see docs/PIPELINE.md
│
├── docs/
│   ├── PIPELINE.md              # Multi-agent pipeline: design, criteria, run, evaluation
│   ├── labeling_rules.md        # Strict per-criterion labeling rules
│   └── C3_C4_USER_CALIBRATION.md  # Proposal: per-user calibration of C3 and C4
│
├── logs/                        # Slurm job logs (folder must exist before sbatch)
└── .env                         # API keys (git-ignored, create it yourself; see gisun/config.py)

Run results go to evaluation/outputs/ (git-ignored). Raw downloads (HC3, WildChat) go to datasets/raw/
(git-ignored).
```


## License

The code, the word list (`data/bias_wordlist.json`), the series catalog (`data/stat_series.json`), the
labeling rules and our own labels are released under the MIT License: see [LICENSE](LICENSE).

**Third-party data is not covered by that license** and stays under its original terms. It is in the
repository only to evaluate GiSuN:

| Files | From |
|---|---|
| `datasets/external/logic/edu_all.csv`, `datasets/gold_c4_logic.json` | LOGIC: Jin et al., "Logical Fallacy Detection", Findings of EMNLP 2022, https://github.com/causalNLP/logical-fallacy |
| the C2 rows of `datasets/gold_public_{1,2,3}.json` | QuanTemp: Venktesh et al., SIGIR 2024, https://doi.org/10.1145/3626772.3657874 |
| the other rows of `datasets/gold_public_{1,2,3}.json` | other public datasets (sources to be listed here) |
| `datasets/collected/claude_2026-10-12.json`, the answer texts in `datasets/gold_answers.json` | answers written by Claude and ChatGPT to our prompts |
| `data/stat_cache.json` | responses from the BLS, U.S. Census Bureau, FRED (Federal Reserve Bank of St. Louis), CDC (data.cdc.gov), World Bank and Data Commons APIs. This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis |

The 67 C1 labels in `datasets/gold_public_1.json` were relabeled on 2026-11-18 by applying `docs/labeling_rules.md` (AI-assisted, reviewed by Suning); 11 of 67 changed. The original labels are kept in `datasets/relabel/c1_public1_original_gold.json`.
