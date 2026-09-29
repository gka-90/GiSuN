# GiSuN

A Chrome extension that helps users engage more critically with AI chatbot output by detecting and highlighting unverified statistics and biased phrasing, and reinforcing critical-reading habits through short interactive exercises.

Built as a semester-long CS senior seminar project at Hamilton College.

## What it does

- **Detects** numeric/statistical claims and biased or contested phrasing in chatbot responses (currently targeting ChatGPT)
- **Highlights** flagged content directly on the page, with distinct visual styles for risk warnings vs. citations
- **Interacts** with the user via one of two modes: a quiet hover tooltip (citation mode) or a blocking modal (in-your-face mode)
- **Teaches** critical reading through a "Two Truths and a Lie" quiz generated from the chatbot's response

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

If the backend isn't running, `background.js` falls back to a small built-in set of regexes and bias terms so the extension still highlights something. The fallback word list is much smaller than `bias_wordlist.json`.

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

- `type`: `percentage` | `dollar_amount` | `year` | `bias_framing`
- `category`: only present on `bias_framing` flags (the word-list category)
- `start_index` / `end_index`: offsets into the response text, in **UTF-16 code units** so they match JavaScript string indexing (Python code-point offsets would drift after any emoji). `server.py` does this conversion.

## Tech stack

- Chrome Extension (Manifest V3), vanilla JavaScript
- `MutationObserver` for detecting new chatbot responses
- FastAPI + uvicorn for the local `/verify` backend
- Regex for numeric/statistic detection
- A curated JSON word list for bias/framing detection
- **Ollama running Qwen2.5 locally** (per course requirement — no cloud API, no account/API key needed) for quiz generation
- CSS for highlight and modal/tooltip styling

## Project status

### Done 9/26/2026
- [x] `detect_numeric_claims()` — Regex-based detection of percentages, dollar amounts, and years. No model needed, fast and stable.
- [x] `detect_bias_framing()` — Word-list based detection (81 terms across 5 categories: political framing, emotionally charged language, event framing, absolutist claims, identity/group terms). No model needed.
- [x] `generate_quiz()` (Two Truths and a Lie) — Local Qwen2.5 generation with JSON cleanup, validation, retry (up to 2x), and fallback to a curated word bank. Extensively tested (~20 runs); `success_rate_test.py` measures model vs. fallback rates.

### Done 9/28/2026
- [x] `extract_claims()` — Tier 1 claim extraction (no LLM): groups flags by sentence, drops non-claims (questions, filler, advice), scores and de-duplicates the rest. Not wired into `/verify` yet.
- [x] Chrome extension (`extension/`) — `observe_dom_for_new_response()`, `render_highlights()`, `handle_interaction_mode()` (citation tooltip + in-your-face modal).
- [x] `server.py` — FastAPI `POST /verify` wrapping both detectors, returning flags in the shared format.
- [x] Updated for the 2026 ChatGPT layout (`chatgpt.com/uc/...`, `data-message-role="assistant"`, `data-assistant-markdown`); the old layout's selectors are still supported. Responses already on the page at load time are scanned too.

### TODO
- [ ] `fetch_citations()` — actually look up sources for flagged numbers (currently the extension only says "check a source").
- [ ] Popup/options page to switch between citation and in-your-face mode (right now the mode is only stored in `chrome.storage.sync`, default `citation`).
- [ ] Hook up the quiz: a `/quiz` endpoint for `generate_quiz()` and a trigger in the extension UI.
- [ ] Feed `extract_claims()` into the pipeline.

### Known limitations (documented, not bugs)
- Local model (Qwen2.5:1.5b/3b) output for quiz generation is not 100% reliable — roughly 1/4 to 1/3 of raw generations are fully clean; validation/retry/fallback handles this but cannot guarantee semantic correctness (e.g. `false_index` matching the explanation), only format correctness.
- Word-list bias detection cannot catch phrasing outside the list, doesn't account for context/negation/quotation, and is English-only.
- ChatGPT changes its DOM often. If highlights stop appearing, the selectors at the top of `extension/content.js` (`RESPONSE_SELECTOR`, `MARKDOWN_SELECTOR`) are the first thing to check.

## Setup

### 1. Python environment
```bash
conda create -n ai-guardrail python=3.11
conda activate ai-guardrail
conda install pip
pip install ollama fastapi uvicorn
```

### 2. Backend
Run from the project root and **keep this terminal open** while using the extension:
```bash
conda activate ai-guardrail
uvicorn server:app --port 8000 --reload
```
Check it's up by opening http://localhost:8000/docs (you can try `/verify` from there).

### 3. Local LLM (Ollama + Qwen) — only needed for the quiz
```bash
brew install ollama
brew services start ollama
ollama pull qwen2.5:1.5b   # 8GB RAM machines
# or
ollama pull qwen2.5:3b     # 16GB RAM machines
```

### 4. Chrome extension
1. Go to `chrome://extensions`
2. Turn on **Developer mode** (toggle in the top-right corner). The **Load unpacked** button only appears after this.
3. Click **Load unpacked** and select the **`extension/`** folder (not the project root — `manifest.json` lives in `extension/`)
4. Open [chatgpt.com](https://chatgpt.com) (refresh any tab that was already open) and ask something with numbers, e.g. *"Give me 3 statistics about US unemployment with years and percentages."* Highlights appear ~1.5s after the response finishes.

After editing anything in `extension/`, click the ↻ reload button on the GiSuN card and refresh the ChatGPT tab.

## Troubleshooting

- **No highlights at all** — In the ChatGPT tab's DevTools console, run:
  ```js
  [document.querySelectorAll('[data-message-role="assistant"]').length, document.querySelectorAll('mark.gisun-flag').length]
  ```
  - First number is `0`: ChatGPT changed its layout; update `RESPONSE_SELECTOR` / `MARKDOWN_SELECTOR` in `content.js`.
  - First > 0, second `0`: check the **Errors** button on the extension card.
  - Chrome may ask you to type `allow pasting` before it lets you paste into the console.
- **Only a few bias words get flagged** — the backend isn't reachable, so the extension is using its fallback. Open the extension's service worker console (link on the extension card) and look for `backend unreachable, using fallback flags`; start uvicorn (step 2).
- **VS Code says `Import "fastapi" could not be resolved`** — select the `ai-guardrail` interpreter (Cmd+Shift+P → *Python: Select Interpreter*).

## Project structure

```
/
├── extension/
│   ├── manifest.json            # Extension config (Manifest V3)
│   ├── content.js               # DOM observer, highlighting, tooltip/modal
│   ├── background.js            # Relays text to /verify; fallback detectors if backend is down
│   └── styles.css               # Highlight, tooltip, modal styles
├── server.py                    # FastAPI backend: POST /verify
├── detect_numeric_claims.py     # Regex-based numeric/stat detection
├── detect_bias_framing.py       # Word-list based bias detection
├── bias_wordlist.json           # Curated word list (81 terms, 5 categories)
├── extract_claims.py            # Tier 1 claim extraction from flags
├── two_truths_one_lie/
│   ├── quiz_generator.py        # Two Truths and a Lie: Qwen call + validation + fallback
│   ├── quiz_static.py           # Fallback word bank only (no model call), for reliable demos
│   └── success_rate_test.py     # Measures model vs. fallback success rates
└── output/                      # JSON results from running the scripts above
```

## Team

Two-person team, Hamilton College CS Senior Seminar, Fall 2026.

## License

Course project — not licensed for external use.
