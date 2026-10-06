// Flow: observe_dom_for_new_response() -> processResponse()
//   -> background.js (POST /pipeline, poll): the agents check every claim in the answer
//   -> render_claims(): underline the risky claim sentences and mark the words the agents quoted
//   -> handle_interaction_mode(): hover tooltip or blocking modal; click a highlight for details
// Only a "checking..." note is shown while the agents work. If they can't run (backend down,
// pipeline error), the instant rule highlights from POST /verify are shown instead.

// Old ChatGPT layout used data-message-author-role; the 2026 layout (chatgpt.com/uc/...) uses data-message-role
const RESPONSE_SELECTOR = '[data-message-author-role="assistant"], [data-message-role="assistant"]';
// The user's messages, to send the question along with the answer
const USER_SELECTOR = '[data-message-author-role="user"], [data-message-role="user"]';
const MARKDOWN_SELECTOR = ".markdown, [data-assistant-markdown]";
// ChatGPT's prompt box is a contenteditable div (#prompt-textarea); older layouts used a real <textarea>
const PROMPT_INPUT_SELECTOR = '#prompt-textarea, form textarea, form [contenteditable="true"]';
const SEND_BUTTON_SELECTOR = '[data-testid="send-button"], button[aria-label*="Send"]';
const STREAM_DONE_MS = 1500; // no changes for this long = response finished streaming
const SELF_TEST_MS = 15000; // warn if the page has conversation turns but none match our selectors
// Rule highlights only (fallback): bare years are context, not claims; highlighting every
// year trains users to ignore highlights.
const QUIET_TYPES = new Set(["year"]);
// Claims at these risk levels are highlighted; "low" means the agents found no problem
const HIGHLIGHT_RISKS = new Set(["medium", "high"]);
// Plain-language names for the pipeline criteria, shown in tooltips, the modal and the panel
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
let deepMode = "full"; // pipeline mode; "rules_only" needs no model (instant, rules decide everything)
const pendingTimers = new Map();
const processedText = new WeakMap();
const results = new WeakMap(); // response container -> pipeline result, for the click panel
const statusNotes = new WeakMap(); // response -> its "GiSuN is checking..." note
let offlineNoticeShown = false;
// One pipeline run at a time: answers already on the page wait their turn instead of
// all hitting the model at once
let pipelineQueue = Promise.resolve();

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

// The agents decide what gets highlighted; until they finish, only a status note is shown
async function processResponse(response) {
  const container = response.querySelector(MARKDOWN_SELECTOR) ?? response;
  const { text } = buildTextMap(container);
  // Our own highlighting also triggers the observer; the text is unchanged, so skip it
  if (!text.trim() || processedText.get(response) === text) return;
  processedText.set(response, text);
  container.dataset.gisunMode = currentMode;

  setStatus(response, "checking", "GiSuN is checking the claims in this answer…");
  const res = await enqueue(() => requestPipeline(text, findQuestion(container)));
  if (buildTextMap(container).text !== text) return; // the answer changed meanwhile; a new check is scheduled

  if (res.error) {
    await showRuleHighlights(response, container, text, res.error);
    return;
  }
  results.set(container, res.result);
  const flagged = render_claims(container, res.result);
  setStatus(response, "done", summaryMessage(flagged, res.result));
  handle_interaction_mode(currentMode, container, flagged.map(claimModalItem));
}

function enqueue(task) {
  const run = pipelineQueue.then(task, task);
  pipelineQueue = run.catch(() => {});
  return run;
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

// Fallback when the agents can't run: the rule highlights from POST /verify (or, with the
// backend down, background.js's small built-in detectors), with a note saying so
async function showRuleHighlights(response, container, text, error) {
  const { flags: allFlags, source } = await requestFlags(text);
  if (buildTextMap(container).text !== text) return;
  if (source === "fallback") showOfflineNotice();
  const flags = allFlags.filter((f) => !QUIET_TYPES.has(f.type));
  render_highlights(container, flags);
  setStatus(response, "fallback", source === "server"
    ? `GiSuN's agents couldn't check this answer (${error}), so these are the basic rule highlights.`
    : "GiSuN's backend isn't running, so only a few basic patterns are highlighted.");
  handle_interaction_mode(currentMode, container, flags.map(flagModalItem));
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

// A short note under the answer: "checking...", then the summary (or why the rules were used)
function setStatus(response, state, message) {
  let note = statusNotes.get(response);
  if (!note?.isConnected) {
    note = makeEl("div", "gisun-status");
    note.setAttribute("role", "status");
    response.parentNode?.insertBefore(note, response.nextSibling); // next to the answer, like the prebunk banner
    statusNotes.set(response, note);
  }
  note.className = `gisun-status gisun-status-${state}`;
  note.textContent = message;
}

function summaryMessage(flagged, result) {
  // agent_share 0 = every model call failed (no model running), so the rules decided everything
  const how = result.model && result.agent_share ? "" : " (decided by the rules: no model was reachable)";
  if (!flagged.length) return `GiSuN checked this answer: no claims flagged${how}.`;
  const high = flagged.filter((c) => c.score.risk === "high").length;
  return `GiSuN: ${flagged.length} claim${flagged.length > 1 ? "s" : ""} worth checking` +
    `${high ? ` (${high} high risk)` : ""}${how}. Hover a highlight for the reasons, click it for details.`;
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

// Agent highlights: the claims the agents flagged (medium/high risk). Returns those claims.
function render_claims(container, result) {
  clearHighlights(container);
  const { text, segments } = buildTextMap(container);
  const lower = text.toLowerCase();

  // Where each claim's sentence is in the page text (claims come in reading order)
  const placed = [];
  let cursor = 0;
  for (const claim of result.claims) {
    let start = text.indexOf(claim.sentence, cursor);
    if (start < 0) start = text.indexOf(claim.sentence);
    if (start < 0) continue;
    cursor = start + claim.sentence.length;
    if (HIGHLIGHT_RISKS.has(claim.score.risk)) placed.push({ claim, start, end: cursor });
  }

  // 1) Underline each flagged sentence. Last first, so splitting text nodes doesn't move
  //    the offsets of sentences still to come.
  for (const p of [...placed].reverse()) wrapSpan(segments, p.start, p.end, () => claimMark(p.claim));

  // 2) Inside those sentences, mark the exact words the agents quoted as evidence ("job-killing",
  //    "12%"). The Check agent guarantees the quotes are in the answer; match case-insensitively
  //    like it does, and skip a quote that overlaps one already marked.
  const keys = [];
  for (const p of placed) {
    for (const key of keyWords(p.claim)) {
      const at = lower.indexOf(key.quote.toLowerCase(), p.start);
      if (at >= 0 && at + key.quote.length <= p.end) keys.push({ ...key, claim: p.claim, start: at, end: at + key.quote.length });
    }
  }
  keys.sort((a, b) => a.start - b.start || b.end - a.end);
  const kept = keys.filter((k, i) => !keys.slice(0, i).some((o) => o.start < k.end && k.start < o.end));
  const fresh = buildTextMap(container).segments; // the text nodes changed in step 1
  for (const k of kept.reverse()) wrapSpan(fresh, k.start, k.end, () => keyMark(k));

  return placed.map((p) => p.claim);
}

// The words the agents quoted from the answer for each problem they found, merged per quote
function keyWords(claim) {
  const byQuote = new Map();
  for (const [cid, d] of Object.entries(claim.criteria)) {
    if (d.decision !== "met") continue;
    for (const e of d.evidence ?? []) {
      const quote = (e.quote ?? "").trim();
      if (e.source !== "response" || !quote) continue;
      const key = byQuote.get(quote.toLowerCase()) ?? { quote, reasons: [] };
      key.reasons.push(`${CRITERION_LABELS[cid] ?? cid}: ${d.reasoning}`);
      byQuote.set(quote.toLowerCase(), key);
    }
  }
  return [...byQuote.values()];
}

// Rule highlights (fallback only): one <mark> per flag
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
    wrapSpan(segments, flag.start_index, flag.end_index, () => ruleMark(flag));
  }
}

// Wrap text[start:end] in marks. A span can cross several text nodes (e.g. "8.<b>5%</b>"),
// so each piece gets its own mark from makeMark().
function wrapSpan(segments, start, end, makeMark) {
  for (let i = segments.length - 1; i >= 0; i--) {
    const { node, start: nodeStart } = segments[i];
    const a = Math.max(start, nodeStart) - nodeStart;
    const b = Math.min(end, nodeStart + node.data.length) - nodeStart;
    if (a < b) wrapRange(node, a, b, makeMark());
  }
}

function wrapRange(node, a, b, mark) {
  if (b < node.data.length) node.splitText(b);
  const target = a > 0 ? node.splitText(a) : node;
  target.parentNode.insertBefore(mark, target);
  mark.appendChild(target);
}

function clearHighlights(container) {
  // (the text nodes the marks split stay split; their text, and so every offset, is unchanged)
  container.querySelectorAll("mark.gisun-flag, mark.gisun-claim").forEach((mark) => mark.replaceWith(...mark.childNodes));
}

// A flagged claim sentence (underlined in its risk colour)
function claimMark(claim) {
  const mark = makeEl("mark", `gisun-claim gisun-claim-${claim.score.risk}`);
  mark.dataset.gisunClaim = claim.claim_id;
  mark.dataset.gisunLabel = claimLabel(claim);
  return mark;
}

// The words inside a flagged claim that the agents pointed to
function keyMark(key) {
  const mark = makeEl("mark", `gisun-flag gisun-key gisun-key-${key.claim.score.risk}`);
  mark.dataset.gisunClaim = key.claim.claim_id;
  mark.dataset.gisunLabel = key.reasons.join(" ");
  return mark;
}

// A rule flag (fallback only)
function ruleMark(flag) {
  const mark = makeEl("mark", `gisun-flag gisun-${flagKind(flag)}`);
  mark.dataset.gisunLabel = flagLabel(flag);
  return mark;
}

// "High risk: No source for the number; Loaded wording." -- for the tooltip and the modal
function claimLabel(claim) {
  const problems = Object.entries(claim.criteria)
    .filter(([, d]) => d.decision === "met")
    .map(([cid]) => CRITERION_LABELS[cid] ?? cid);
  const risk = claim.score.risk;
  return `${risk[0].toUpperCase()}${risk.slice(1)} risk: ${problems.join("; ")}.`;
}

// "risk" = loaded/biased phrasing, "citation" = number that needs a source
function flagKind(flag) {
  return flag.type === "bias_framing" ? "risk" : "citation";
}

// Warnings, not verdicts (open problem #14): the rules can't tell whether a claim is true,
// only that it is worth a second look. Only the agents' C2 can say a source disagrees.
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

// items: [{ quote, label, kind }] -- flagged claims, or rule flags in the fallback
function handle_interaction_mode(mode, container, items) {
  container.dataset.gisunMode = mode;
  if (mode === "in_your_face" && items.length > 0) showModal(items);
}

function claimModalItem(claim) {
  const quote = claim.sentence.length > 140 ? `${claim.sentence.slice(0, 137)}…` : claim.sentence;
  return { quote, label: claimLabel(claim), kind: claim.score.risk === "high" ? "risk" : "citation" };
}

function flagModalItem(flag) {
  return { quote: flag.matched_value, label: flagLabel(flag), kind: flagKind(flag) };
}

// Citation mode: hovering a highlight shows its reasons (the innermost mark: key words before sentences)
function setupTooltip() {
  const tip = makeEl("div", "gisun-tooltip");
  tip.hidden = true;
  document.body.appendChild(tip);

  document.addEventListener("mouseover", (e) => {
    const mark = e.target.closest?.("mark.gisun-flag, mark.gisun-claim");
    if (!mark || mark.closest("[data-gisun-mode]")?.dataset.gisunMode !== "citation") {
      tip.hidden = true;
      return;
    }
    const rect = mark.getBoundingClientRect();
    tip.textContent = mark.dataset.gisunClaim ? `${mark.dataset.gisunLabel} Click for details.` : mark.dataset.gisunLabel;
    tip.style.left = `${rect.left}px`;
    tip.style.top = `${rect.bottom + 6}px`;
    tip.hidden = false;
  });
  window.addEventListener("scroll", () => { tip.hidden = true; }, true);
}

// Blocking modal; if one is already open, new items are added to it instead of stacking modals
function showModal(items) {
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
  for (const item of items) {
    list.appendChild(makeEl("li", `gisun-${item.kind}`, `"${item.quote}": ${item.label}`));
  }
}

// Clicking an agent highlight opens a panel with that claim's full verdict (no new model call:
// the result is already here)
function setupClaimDetails() {
  document.addEventListener("click", (e) => {
    const mark = e.target.closest?.("mark[data-gisun-claim]");
    const container = mark?.closest("[data-gisun-mode]");
    const result = container && results.get(container);
    const claim = result?.claims.find((c) => String(c.claim_id) === mark.dataset.gisunClaim);
    if (claim) renderDeepResult(showDeepPanel(mark), claim, result);
  });
  // The panel is fixed to the viewport, so close it when the conversation scrolls under it
  window.addEventListener("scroll", (e) => {
    if (!e.target.closest?.(".gisun-deep")) document.querySelector(".gisun-deep")?.remove();
  }, true);
}

// Risk level, the problems found (with any source quotes), what was fine and what couldn't be checked
function renderDeepResult(panel, claim, result) {
  const footer = makeEl("p", "gisun-deep-meta", result.model && result.agent_share
    ? `Checked by ${result.model} (${result.mode} mode).`
    : `Checked by the rules only (${result.mode}).`);

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
    if (d.by === "rules" && result.agent_share) {
      item.appendChild(makeEl("div", "gisun-deep-meta", "Decided by the rules (the agent didn't finish)."));
    }
    list.appendChild(item);
  }

  const children = [makeEl("p", "gisun-deep-claim", claim.sentence), heading];
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
  panel.setAttribute("aria-label", "GiSuN claim details");
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
setupClaimDetails();
observe_dom_for_new_response();
selfTest();
