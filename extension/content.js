// Flow: observe_dom_for_new_response() -> background.js (POST /verify)
//       -> render_highlights() -> handle_interaction_mode()
// Click a highlight -> deepCheck() -> background.js (POST /pipeline, poll) -> per-claim verdict panel

// Old ChatGPT layout used data-message-author-role; the 2026 layout (chatgpt.com/uc/...) uses data-message-role
const RESPONSE_SELECTOR = '[data-message-author-role="assistant"], [data-message-role="assistant"]';
// The user's messages, to send the question along with the deep check
const USER_SELECTOR = '[data-message-author-role="user"], [data-message-role="user"]';
const MARKDOWN_SELECTOR = ".markdown, [data-assistant-markdown]";
// ChatGPT's prompt box is a contenteditable div (#prompt-textarea); older layouts used a real <textarea>
const PROMPT_INPUT_SELECTOR = '#prompt-textarea, form textarea, form [contenteditable="true"]';
const SEND_BUTTON_SELECTOR = '[data-testid="send-button"], button[aria-label*="Send"]';
const STREAM_DONE_MS = 1500; // no changes for this long = response finished streaming
const SELF_TEST_MS = 15000; // warn if the page has conversation turns but none match our selectors
// Bare years are context, not claims; highlighting every year trains users to ignore highlights.
// They still reach the backend, so the deep check sees them.
const QUIET_TYPES = new Set(["year"]);
// Plain-language names for the pipeline criteria, shown in the deep-check panel
const CRITERION_LABELS = {
  C1: "No source for the number",
  C2: "A source gives a different figure",
  C3: "Loaded wording",
  C4: "Sweeping generalization",
  C5: "Vague source (\"experts say\")",
  C6: "Cause and effect without evidence",
};
const BLOCK_TAGS = new Set([
  "P", "LI", "H1", "H2", "H3", "H4", "H5", "H6", "PRE", "BLOCKQUOTE", "TR", "TD", "TH", "DIV",
]);

let currentMode = "citation"; // "citation" | "in_your_face"
let deepMode = "full"; // pipeline mode for the deep check; "rules_only" needs no model
const pendingTimers = new Map();
const processedText = new WeakMap();
const deepChecks = new WeakMap(); // response container -> { text, promise }, so a second click reuses the run
let offlineNoticeShown = false;

// Detect new responses

function observe_dom_for_new_response() {
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      const target = m.target.nodeType === Node.ELEMENT_NODE ? m.target : m.target.parentElement;
      const response = target?.closest(RESPONSE_SELECTOR);
      if (response) scheduleCheck(response);

      for (const node of m.addedNodes) {
        if (node.nodeType !== Node.ELEMENT_NODE) continue;
        if (node.matches(RESPONSE_SELECTOR)) scheduleCheck(node);
        node.querySelectorAll(RESPONSE_SELECTOR).forEach(scheduleCheck);
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  // Responses already on the page when the script loads never trigger a mutation
  document.querySelectorAll(RESPONSE_SELECTOR).forEach(scheduleCheck);
}

// ChatGPT streams text in piece by piece, so wait until a response stops changing
function scheduleCheck(response) {
  clearTimeout(pendingTimers.get(response));
  pendingTimers.set(response, setTimeout(() => {
    pendingTimers.delete(response);
    processResponse(response);
  }, STREAM_DONE_MS));
}

async function processResponse(response) {
  const container = response.querySelector(MARKDOWN_SELECTOR) ?? response;
  const { text } = buildTextMap(container);
  // Our own highlighting also triggers the observer; the text is unchanged, so skip it
  if (!text.trim() || processedText.get(response) === text) return;
  processedText.set(response, text);

  const { flags: allFlags, source } = await requestFlags(text);
  if (buildTextMap(container).text !== text) return;
  if (source === "fallback") showOfflineNotice();

  const flags = allFlags.filter((f) => !QUIET_TYPES.has(f.type));
  render_highlights(container, flags);
  handle_interaction_mode(currentMode, container, flags);
}

function requestFlags(text) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "verify", text }, (res) => {
      if (chrome.runtime.lastError) {
        console.warn("[GiSuN]", chrome.runtime.lastError.message);
        resolve({ flags: [], source: "error" });
      } else {
        resolve({ flags: res?.flags ?? [], source: res?.source });
      }
    });
  });
}

// Tell the user once instead of quietly showing the much weaker fallback highlights
function showOfflineNotice() {
  if (offlineNoticeShown) return;
  offlineNoticeShown = true;
  const note = makeEl("div", "gisun-offline",
    "GiSuN's backend isn't running, so only a few basic patterns are highlighted. " +
    "Start it with: uvicorn server:app --port 8000 (click to dismiss)");
  note.setAttribute("role", "status");
  note.addEventListener("click", () => note.remove());
  document.body.appendChild(note);
  setTimeout(() => note.remove(), 15000);
}

// Builds the plain text sent to the backend, plus a map from text offsets back to DOM text nodes.

function buildTextMap(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const segments = [];
  let text = "";
  let lastBlock = null;

  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const block = closestBlock(node, root);
    if (lastBlock && block !== lastBlock && !/\s$/.test(text)) text += "\n";
    lastBlock = block;
    segments.push({ node, start: text.length });
    text += node.data;
  }
  return { text, segments };
}

function closestBlock(node, root) {
  for (let el = node.parentElement; el && el !== root; el = el.parentElement) {
    if (BLOCK_TAGS.has(el.tagName)) return el;
  }
  return root;
}

// Highlight flags

function render_highlights(container, flags) {
  clearHighlights(container);
  const { text, segments } = buildTextMap(container);

  // Work backwards so splitting text nodes doesn't shift the offsets of flags still to come
  const sorted = [...flags].sort((a, b) => b.start_index - a.start_index);
  let lastStart = Infinity;

  for (const flag of sorted) {
    if (flag.end_index > lastStart) continue;
    if (text.slice(flag.start_index, flag.end_index) !== flag.matched_value) {
      console.warn("[GiSuN] flag offsets don't match the page text, skipping:", flag);
      continue;
    }
    lastStart = flag.start_index;

    //a flag can span several text nodes (e.g. "8.<b>5%</b>"), so wrap each piece
    for (let i = segments.length - 1; i >= 0; i--) {
      const { node, start } = segments[i];
      const a = Math.max(flag.start_index, start) - start;
      const b = Math.min(flag.end_index, start + node.data.length) - start;
      if (a < b) wrapRange(node, a, b, flag);
    }
  }
}

function wrapRange(node, a, b, flag) {
  if (b < node.data.length) node.splitText(b);
  const target = a > 0 ? node.splitText(a) : node;
  const mark = document.createElement("mark");
  mark.className = `gisun-flag gisun-${flagKind(flag)}`;
  mark.dataset.gisunLabel = flagLabel(flag);
  target.parentNode.insertBefore(mark, target);
  mark.appendChild(target);
}

function clearHighlights(container) {
  container.querySelectorAll("mark.gisun-flag").forEach((mark) => mark.replaceWith(...mark.childNodes));
}

// "risk" = loaded/biased phrasing, "citation" = number that needs a source
function flagKind(flag) {
  return flag.type === "bias_framing" ? "risk" : "citation";
}

// Warnings, not verdicts (open problem #14): the rules can't tell whether a claim is true,
// only that it is worth a second look. Only the deep check's C2 can say a source disagrees.
function flagLabel(flag) {
  if (flag.type === "bias_framing") {
    if (flag.category === "vague_or_unsourced_attribution") {
      return "Vague source: who exactly says this? Worth checking before you rely on it.";
    }
    return `Possibly loaded wording (${(flag.category ?? "bias").replace(/_/g, " ")}): how else could this be put?`;
  }
  if (flag.type === "quantity") {
    return "A sweeping quantity with no number or source: worth checking how many, and according to whom.";
  }
  const kind = flag.type.replace(/_/g, " ");
  return `${kind[0].toUpperCase()}${kind.slice(1)} with no source given: worth checking before you rely on it.`;
}

//Interaction modes

function handle_interaction_mode(mode, container, flags) {
  container.dataset.gisunMode = mode;
  if (mode === "in_your_face" && flags.length > 0) showModal(flags);
}

function setupTooltip() {
  const tip = makeEl("div", "gisun-tooltip");
  tip.hidden = true;
  document.body.appendChild(tip);

  document.addEventListener("mouseover", (e) => {
    const mark = e.target.closest?.("mark.gisun-flag");
    if (!mark || mark.closest("[data-gisun-mode]")?.dataset.gisunMode !== "citation") {
      tip.hidden = true;
      return;
    }
    const rect = mark.getBoundingClientRect();
    tip.textContent = `${mark.dataset.gisunLabel} Click for a deep check.`;
    tip.style.left = `${rect.left}px`;
    tip.style.top = `${rect.bottom + 6}px`;
    tip.hidden = false;
  });
  window.addEventListener("scroll", () => { tip.hidden = true; }, true);
}

// Blocking modal; if one is already open, new flags are added to it instead of stacking modals
function showModal(flags) {
  let overlay = document.querySelector(".gisun-overlay");
  if (!overlay) {
    overlay = makeEl("div", "gisun-overlay");
    const modal = makeEl("div", "gisun-modal");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    const button = makeEl("button", "gisun-modal-ok", "I'll check these");
    button.type = "button";
    button.addEventListener("click", () => overlay.remove());

    modal.append(
      makeEl("h2", "", "Read this response critically"),
      makeEl("p", "", "This response contains claims worth checking before you rely on them:"),
      makeEl("ul", "gisun-modal-list"),
      button,
    );
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    button.focus();
  }

  const list = overlay.querySelector(".gisun-modal-list");
  for (const flag of flags) {
    list.appendChild(makeEl("li", `gisun-${flagKind(flag)}`, `"${flag.matched_value}": ${flagLabel(flag)}`));
  }
}

// Deep check (open problem #15): clicking a highlight runs the multi-agent pipeline on the whole
// answer once (cached per response) and shows that claim's per-criterion verdict.

function setupDeepCheck() {
  document.addEventListener("click", (e) => {
    const mark = e.target.closest?.("mark.gisun-flag");
    const container = mark?.closest("[data-gisun-mode]");
    if (container) deepCheck(mark, container);
  });
  // The panel is fixed to the viewport, so close it when the conversation scrolls under it
  window.addEventListener("scroll", (e) => {
    if (!e.target.closest?.(".gisun-deep")) document.querySelector(".gisun-deep")?.remove();
  }, true);
}

// Shows the panel right away, then fills it when the (shared, cached) pipeline run for this answer is done
function deepCheck(mark, container) {
  const panel = showDeepPanel(mark);
  setPanel(panel, [makeEl("p", "", "Deep check running: the agents check every claim in this answer. " +
    "This can take a minute.")]);

  const { text, segments } = buildTextMap(container);
  let job = deepChecks.get(container);
  if (!job || job.text !== text) {
    job = { text, promise: requestPipeline(text, findQuestion(container)) };
    deepChecks.set(container, job);
  }
  // Where the clicked highlight starts in the answer text, to pick the right claim
  const first = document.createTreeWalker(mark, NodeFilter.SHOW_TEXT).nextNode();
  const offset = segments.find((s) => s.node === first)?.start ?? -1;

  job.promise.then((res) => {
    if (!panel.isConnected) return;
    if (res.error) {
      deepChecks.delete(container); // let the next click retry
      setPanel(panel, [makeEl("p", "", `The deep check failed: ${res.error}. Is the backend running?`)]);
      return;
    }
    renderDeepResult(panel, findClaim(res.result, mark.textContent, text, offset), res.result);
  });
}

// background.js does the POST and the polling; resolves with { result } or { error }
function requestPipeline(text, question) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "pipeline", text, question, mode: deepMode }, (res) => {
      resolve(chrome.runtime.lastError ? { error: chrome.runtime.lastError.message } : res ?? { error: "no reply" });
    });
  });
}

// The user's question is the closest user message before this response
function findQuestion(container) {
  const before = [...document.querySelectorAll(USER_SELECTOR)]
    .filter((u) => u.compareDocumentPosition(container) & Node.DOCUMENT_POSITION_FOLLOWING);
  return before.at(-1)?.innerText.trim() ?? "";
}

// The claim whose sentence contains the clicked text at the clicked position
// (the same sentence can appear twice in one answer)
function findClaim(result, markText, text, offset) {
  const candidates = result.claims.filter((c) => c.sentence.includes(markText));
  const covers = (c) => {
    for (let i = text.indexOf(c.sentence); i !== -1; i = text.indexOf(c.sentence, i + 1)) {
      if (offset >= i && offset < i + c.sentence.length) return true;
    }
    return false;
  };
  return candidates.find(covers) ?? candidates[0];
}

// Risk level, the problems found (with any source quotes), what was fine and what couldn't be checked
function renderDeepResult(panel, claim, result) {
  const footer = makeEl("p", "gisun-deep-meta",
    result.model ? `Checked by ${result.model} (${result.mode} mode).` : `Checked by rules only (${result.mode}).`);
  if (!claim) {
    setPanel(panel, [makeEl("p", "", "The deep check didn't treat this sentence as a factual claim " +
      "(it looked like a question, advice or filler)."), footer]);
    return;
  }

  const { risk, unverified } = claim.score;
  const heading = makeEl("p", `gisun-deep-risk gisun-deep-${risk}`,
    `${risk[0].toUpperCase()}${risk.slice(1)} risk${unverified ? ", unverified number" : ""}`);
  const entries = Object.entries(claim.criteria);
  const labelsWhere = (decision) => entries.filter(([, d]) => d.decision === decision).map(([cid]) => CRITERION_LABELS[cid] ?? cid);
  const problems = entries.filter(([, d]) => d.decision === "met");
  const fine = labelsWhere("not_met");
  const unknown = labelsWhere("undetermined");

  const list = makeEl("ul", "gisun-deep-list");
  for (const [cid, d] of problems) {
    const item = makeEl("li", "", `${CRITERION_LABELS[cid] ?? cid}: ${d.reasoning}`);
    for (const e of d.evidence ?? []) {
      if (e.source && e.source !== "response") item.appendChild(makeEl("div", "gisun-deep-source", `Source (${e.source}): "${e.quote}"`));
    }
    if (d.by === "rules" && result.model) {
      item.appendChild(makeEl("div", "gisun-deep-meta", "Decided by the rules (the agent didn't finish)."));
    }
    list.appendChild(item);
  }

  const children = [heading];
  children.push(problems.length ? list : makeEl("p", "", "No problems found in this sentence."));
  if (fine.length) children.push(makeEl("p", "gisun-deep-meta", `Checked and fine: ${fine.join(", ")}.`));
  if (unknown.length) children.push(makeEl("p", "gisun-deep-meta", `Couldn't check: ${unknown.join(", ")}.`));
  children.push(footer);
  setPanel(panel, children);
}

// One panel at a time, placed under the clicked highlight and kept inside the window
function showDeepPanel(mark) {
  document.querySelector(".gisun-deep")?.remove();
  const panel = makeEl("div", "gisun-deep");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "GiSuN deep check");
  const close = makeEl("button", "gisun-deep-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "Close");
  close.addEventListener("click", () => panel.remove());
  panel.append(close, makeEl("div", "gisun-deep-body"));

  const rect = mark.getBoundingClientRect();
  panel.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 392))}px`;
  panel.style.top = `${Math.min(rect.bottom + 8, window.innerHeight - 200)}px`;
  document.body.appendChild(panel);
  return panel;
}

function setPanel(panel, children) {
  panel.querySelector(".gisun-deep-body").replaceChildren(...children);
}

// Open problem #18: ChatGPT changes its markup often; say so instead of failing silently
function selfTest() {
  setTimeout(() => {
    if (document.querySelector(RESPONSE_SELECTOR)) return;
    const turns = document.querySelectorAll('article, [data-testid^="conversation-turn"]');
    if (turns.length) {
      console.warn(`[GiSuN] ${turns.length} conversation turns on the page, but none match RESPONSE_SELECTOR. ` +
        "ChatGPT's layout has probably changed: update the selectors at the top of content.js.");
    }
  }, SELF_TEST_MS);
}

// Built with createElement/textContent instead of innerHTML: chatgpt.com blocks innerHTML
function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text) el.textContent = text;
  return el;
}

//begin

// Set from the service-worker console, e.g. chrome.storage.sync.set({deepMode: "rules_only"})
chrome.storage.sync.get({ mode: "citation", deepMode: "full" }, (stored) => {
  currentMode = stored.mode;
  deepMode = stored.deepMode;
});
chrome.storage.onChanged.addListener((changes) => {
  if (changes.mode) currentMode = changes.mode.newValue;
  if (changes.deepMode) deepMode = changes.deepMode.newValue;
});

setupTooltip();
setupDeepCheck();
observe_dom_for_new_response();
selfTest();
