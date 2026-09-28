// Relays response text from content.js to the FastAPI backend (POST /verify).

const VERIFY_URL = "http://localhost:8000/verify";

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type !== "verify") return;

  fetch(VERIFY_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: msg.text }),
  })
    .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
    .then((data) => sendResponse({ flags: data.flags, source: "server" }))
    .catch((err) => {
      console.warn("[GiSuN] backend unreachable, using fallback flags:", err.message);
      sendResponse({ flags: fallbackFlags(msg.text), source: "fallback" });
    });

  return true;
});

//TEMP fallback detectors (same patterns as the Python versions)

const NUMERIC_PATTERNS = {
  percentage: /\d+(?:\.\d+)?%/g,
  dollar_amount: /\$\d+(?:,\d{3})*(?:\.\d+)?\s?(?:[BbMmKk](?:illion)?)?/g,
  year: /\b(?:19|20)\d{2}\b/g,
};

const TEST_BIAS_TERMS = {
  emotionally_charged_terms: ["crisis", "catastrophe", "unprecedented", "shocking"],
  absolutist_claims: ["everyone knows", "always", "never"],
  loaded_political_terms: ["radical left", "radical right", "regime"],
};

function sentenceAt(text, start, end) {
  let s = 0;
  let e = text.length;
  for (const m of text.matchAll(/[.!?]\s+/g)) {
    const boundary = m.index + m[0].length;
    if (boundary <= start) s = boundary;
    else if (boundary >= end) { e = boundary; break; }
  }
  return text.slice(s, e).trim();
}

function fallbackFlags(text) {
  const flags = [];
  const add = (m, type, extra = {}) => flags.push({
    sentence: sentenceAt(text, m.index, m.index + m[0].length),
    matched_value: m[0],
    start_index: m.index,
    end_index: m.index + m[0].length,
    type,
    ...extra,
  });

  for (const [type, pattern] of Object.entries(NUMERIC_PATTERNS)) {
    for (const m of text.matchAll(pattern)) add(m, type);
  }
  for (const [category, terms] of Object.entries(TEST_BIAS_TERMS)) {
    for (const term of terms) {
      const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      for (const m of text.matchAll(new RegExp(`\\b${escaped}\\b`, "gi"))) {
        add(m, "bias_framing", { category });
      }
    }
  }
  return flags.sort((a, b) => a.start_index - b.start_index);
}
