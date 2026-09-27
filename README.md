# GiSuN

A Chrome extension that helps users engage more critically with AI chatbot output by detecting and highlighting unverified statistics and biased phrasing, and reinforcing critical-reading habits through short interactive exercises.

Built as a semester-long CS senior seminar project at Hamilton College.

## What it does

- **Detects** numeric/statistical claims and biased or contested phrasing in chatbot responses (currently targeting ChatGPT)
- **Highlights** flagged content directly on the page, with distinct visual styles for risk warnings vs. citations
- **Interacts** with the user via one of two modes: a quiet hover tooltip (citation mode) or a blocking modal (in-your-face mode)
- **Teaches** critical reading through a "Two Truths and a Lie" quiz generated from the chatbot's response

## Tech stack

- Chrome Extension (Manifest V3), vanilla JavaScript
- `MutationObserver` for detecting new chatbot responses
- Regex for numeric/statistic detection
- A curated JSON word list for bias/framing detection
- **Ollama running Qwen2.5 locally** (per course requirement — no cloud API, no account/API key needed) for quiz generation
- CSS for highlight and modal/tooltip styling

## Project status



### Done 9/26/2026
- [x] `detect_numeric_claims()` — Regex-based detection of percentages, dollar amounts, and years. No model needed, fast and stable.
- [x] `detect_bias_framing()` — Word-list based detection (81 terms across 5 categories: political framing, emotionally charged language, event framing, absolutist claims, identity/group terms). No model needed.
- [x] `generate_two_truths_and_a_lie()` — Local Qwen2.5 generation with JSON cleanup, validation, retry (up to 2x), and fallback to a curated word bank. Extensively tested (~20 runs) — see `Qwen_Local_Model_Test_Log.md` for findings and `Demo_Strategy_Two_Truths_and_a_Lie.md` for how this gets presented at demo time.

### Known limitations (documented, not bugs)
- Local model (Qwen2.5:1.5b/3b) output for quiz generation is not 100% reliable — roughly 1/4 to 1/3 of raw generations are fully clean; validation/retry/fallback handles this but cannot guarantee semantic correctness (e.g. `false_index` matching the explanation), only format correctness.
- Word-list bias detection cannot catch phrasing outside the list, doesn't account for context/negation/quotation, and is English-only.

## Setup

### 1. Python environment
```bash
conda create -n ai-guardrail python=3.11
conda activate ai-guardrail
conda install pip
pip install ollama
```

### 2. Local LLM (Ollama + Qwen)
```bash
brew install ollama
brew services start ollama
ollama pull qwen2.5:1.5b   # 8GB RAM machines
# or
ollama pull qwen2.5:3b     # 16GB RAM machines
```

### 3. Chrome extension (once built)
1. Go to `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**, select this project's folder
4. Open [chatgpt.com](https://chatgpt.com) and ask a question — the extension should activate automatically

## Project structure

```
/
├── manifest.json                          # Extension config (Manifest V3) -- TODO
├── content.js                             # DOM observer + rendering -- TODO
├── styles.css                             # Highlight, tooltip, modal styles -- TODO
├── quiz_generator.py                      # Two Truths and a Lie: Qwen call + validation + fallback
├── detect_numeric_claims.py               # Regex-based numeric/stat detection
├── detect_bias_framing.py                 # Word-list based bias detection
├── bias_wordlist.json                     # Curated word list (81 terms, 5 categories)
├── Qwen_Local_Model_Test_Log.md           # Test results for local model reliability
├── Demo_Strategy_Two_Truths_and_a_Lie.md  # How to present the quiz feature at demo time
└── SRS.md                                 # Full Software Requirements Specification
```







## Team

Two-person team, Hamilton College CS Senior Seminar, Fall 2026.

## License

Course project — not licensed for external use.