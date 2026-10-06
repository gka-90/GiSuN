// Relays requests from content.js to the FastAPI backend:
//   "pipeline" -> POST /pipeline, then polls GET /pipeline/{id} (the agents: they decide the highlights)
//   "verify"   -> POST /verify (instant rule flags; only used when the agents can't run)

const BACKEND_URL = "http://localhost:8000";
const PIPELINE_POLL_MS = 2000;
const PIPELINE_TIMEOUT_MS = 4 * 60 * 1000; // a laptop model can take minutes on a long answer

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "verify") {
    verify(msg.text).then(sendResponse);
    return true;
  }
  if (msg.type === "pipeline") {
    runPipeline(msg)
      .then((result) => sendResponse({ result }))
      .catch((err) => sendResponse({ error: err.message }));
    return true;
  }
});

// Rule flags from the backend; if it is down, the small built-in detectors below (source: "fallback")
async function verify(text) {
  try {
    const res = await fetch(`${BACKEND_URL}/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return { flags: (await res.json()).flags, source: "server" };
  } catch (err) {
    console.warn("[GiSuN] backend unreachable, using fallback flags:", err.message);
    return { flags: fallbackFlags(text), source: "fallback" };
  }
}

// The pipeline runs in the background on the server; poll until it is done.
async function runPipeline({ text, question, mode }) {
  const start = await fetch(`${BACKEND_URL}/pipeline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, question: question ?? "", mode: mode ?? "full" }),
  });
  if (!start.ok) throw new Error(`backend returned HTTP ${start.status}`);
  const { job_id: jobId } = await start.json();

  const deadline = Date.now() + PIPELINE_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const res = await fetch(`${BACKEND_URL}/pipeline/${jobId}`);
    if (!res.ok) throw new Error(`backend returned HTTP ${res.status}`);
    const job = await res.json();
    if (job.status === "done") return job.result;
    if (job.status === "error") throw new Error(job.error);
    await new Promise((resolve) => setTimeout(resolve, PIPELINE_POLL_MS));
  }
  throw new Error("the deep check timed out");
}

//TEMP fallback detectors (same patterns as the Python versions)

const NUMERIC_PATTERNS = {
  percentage: /\d+(?:\.\d+)?%/g,
  dollar_amount: /\$\d+(?:,\d{3})*(?:\.\d+)?\s?(?:[BbMmKk](?:illion)?)?/g,
  year: /\b(?:19|20)\d{2}\b/g,
};

const TEST_BIAS_TERMS = {
  emotionally_charged_terms: ["crisis", "catastrophe", "unprecedented", "shocking"],
  absolutist_or_overgeneralizing_terms: ["everyone knows", "always", "never"], // same name as bias_wordlist.json
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
