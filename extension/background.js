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
// Cited pages are opened here, in the user's browser: sites such as bls.gov refuse a script on the
// server (HTTP 403) but serve a browser. Only the visible text is sent on. A PDF or a page that
// fails is left to the backend, which tries it itself and reports why it couldn't.
const PAGE_TIMEOUT_MS = 6000;
const PAGE_MAX_CHARS = 400000;
const pageCache = new Map(); // url -> {text} | {error}

async function readPage(url) {
  if (pageCache.has(url)) return pageCache.get(url);
  let out;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(PAGE_TIMEOUT_MS), credentials: "omit" });
    const kind = res.headers.get("content-type") ?? "";
    if (!res.ok) out = { error: `HTTP ${res.status}` };
    else if (kind.includes("pdf")) out = { error: "pdf" }; // the backend reads PDFs
    else out = { text: htmlToText(await res.text()).slice(0, PAGE_MAX_CHARS) };
  } catch (e) {
    out = { error: e.name === "TimeoutError" ? "timed out" : e.message };
  }
  pageCache.set(url, out);
  return out;
}

// No DOMParser in a service worker: drop scripts, styles and tags, decode the common entities
function htmlToText(html) {
  return html
    .replace(/<(script|style|noscript|svg)[\s\S]*?<\/\1>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n))
    .replace(/\s+/g, " ");
}

async function withPageText(citations) {
  const urls = [...new Set((citations ?? []).map((c) => c.url))];
  const pages = new Map(await Promise.all(urls.map(async (u) => [u, await readPage(u)])));
  return (citations ?? []).map((c) => {
    const p = pages.get(c.url);
    return p?.text ? { ...c, text: p.text } : { ...c, browser_error: p?.error };
  });
}

async function runPipeline({ text, question, mode, c34Mode, citations }) {
  citations = await withPageText(citations);
  const start = await fetch(`${BACKEND_URL}/pipeline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // c34_mode: the user's C3/C4 mode from the quiz (calibration.js); only the mode is sent, never the answers
    body: JSON.stringify({ text, question: question ?? "", mode: mode ?? "full", c34_mode: c34Mode ?? "strict", citations: citations ?? [] }),
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
  absolutist_or_overgeneralizing_terms: ["everyone knows", "always", "never"], // same name as data/bias_wordlist.json
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
