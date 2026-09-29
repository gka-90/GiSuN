// Flow: observe_dom_for_new_response() -> background.js (POST /verify)
//       -> render_highlights() -> handle_interaction_mode()

// Old ChatGPT layout used data-message-author-role; the 2026 layout (chatgpt.com/uc/...) uses data-message-role
const RESPONSE_SELECTOR = '[data-message-author-role="assistant"], [data-message-role="assistant"]';
const MARKDOWN_SELECTOR = ".markdown, [data-assistant-markdown]";
const STREAM_DONE_MS = 1500; // no changes for this long = response finished streaming
const BLOCK_TAGS = new Set([
  "P", "LI", "H1", "H2", "H3", "H4", "H5", "H6", "PRE", "BLOCKQUOTE", "TR", "TD", "TH", "DIV",
]);

let currentMode = "citation"; // "citation" | "in_your_face"
const pendingTimers = new Map();
const processedText = new WeakMap();

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

  const flags = await requestFlags(text);
  if (buildTextMap(container).text !== text) return;

  render_highlights(container, flags);
  handle_interaction_mode(currentMode, container, flags);
}

function requestFlags(text) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "verify", text }, (res) => {
      if (chrome.runtime.lastError) {
        console.warn("[GiSuN]", chrome.runtime.lastError.message);
        resolve([]);
      } else {
        resolve(res?.flags ?? []);
      }
    });
  });
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

function flagLabel(flag) {
  if (flag.type === "bias_framing") {
    return `Loaded phrasing (${(flag.category ?? "bias").replace(/_/g, " ")}): consider how else this could be framed.`;
  }
  return `Unverified ${flag.type.replace(/_/g, " ")}: check a source before relying on it.`;
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
    tip.textContent = mark.dataset.gisunLabel;
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

// Built with createElement/textContent instead of innerHTML: chatgpt.com blocks innerHTML
function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text) el.textContent = text;
  return el;
}

//begin

chrome.storage.sync.get({ mode: "citation" }, ({ mode }) => { currentMode = mode; });
chrome.storage.onChanged.addListener((changes) => {
  if (changes.mode) currentMode = changes.mode.newValue;
});

setupTooltip();
observe_dom_for_new_response();
