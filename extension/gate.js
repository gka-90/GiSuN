// Gated access check: ChatGPT's input stays disabled until the user answers this
// question correctly once. Passing is remembered in chrome.storage.local (isPassed).
// Loaded after content.js, so PROMPT_INPUT_SELECTOR / SEND_BUTTON_SELECTOR / makeEl are available.
//
// To see it again: in the extension's service worker console (link on the extension card)
// run  chrome.storage.local.remove("isPassed")  and refresh the ChatGPT tab.

// Placeholder question -- replace with the one you want users to answer
const GATE_QUESTION = "An AI chatbot tells you \"62% of doctors recommend this supplement\" but names no source. What should you do?";
const GATE_OPTIONS = [
  "Trust it: chatbots are trained on a lot of data.",
  "Find the original source before relying on the number.",
  "Ask the chatbot again; if it repeats the number, it's correct.",
];
const GATE_CORRECT_INDEX = 1;
const GATE_WRONG_MESSAGE = "Incorrect response. Please try again.";

let gateActive = false;
let gateObserver = null;

// contenteditable divs ignore `disabled`, so those get contenteditable="false" instead.
// Re-checks already-gated inputs too: React may flip contenteditable back on the same element.
// Only writes when something changed, so the attribute observer below doesn't loop.
function disableInputs() {
  document.querySelectorAll(`${PROMPT_INPUT_SELECTOR}, [data-gisun-gated]`).forEach((input) => {
    input.dataset.gisunGated = "true";
    if (input.tagName === "TEXTAREA") {
      if (input.disabled) return;
      input.disabled = true;
    } else {
      if (input.getAttribute("contenteditable") === "false") return;
      input.setAttribute("contenteditable", "false");
    }
    input.blur();
  });
}

function enableInputs() {
  document.querySelectorAll("[data-gisun-gated]").forEach((input) => {
    delete input.dataset.gisunGated;
    if (input.tagName === "TEXTAREA") input.disabled = false;
    else input.setAttribute("contenteditable", "true");
  });
}

// Belt and braces: block Enter / the send button even if an input slipped through
function blockSend(e) {
  if (!gateActive) return;
  const enter = e.type === "keydown" && e.key === "Enter" && e.target.closest?.(PROMPT_INPUT_SELECTOR);
  const send = e.type === "click" && e.target.closest?.(SEND_BUTTON_SELECTOR);
  if (enter || send) {
    e.preventDefault();
    e.stopPropagation();
  }
}

function showGate() {
  gateActive = true;
  disableInputs();
  // ChatGPT re-renders its input box (new element, or contenteditable reset on the same
  // one); disable it again each time until the user passes
  gateObserver = new MutationObserver(disableInputs);
  gateObserver.observe(document.body, {
    childList: true, subtree: true, attributes: true, attributeFilter: ["contenteditable", "disabled"],
  });
  document.addEventListener("keydown", blockSend, true);
  document.addEventListener("click", blockSend, true);

  const overlay = makeEl("div", "gisun-gate-overlay");
  const modal = makeEl("form", "gisun-modal gisun-gate");
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-labelledby", "gisun-gate-title");

  const title = makeEl("h2", "", "Before you start");
  title.id = "gisun-gate-title";
  const options = makeEl("fieldset", "gisun-gate-options");
  options.appendChild(makeEl("legend", "", GATE_QUESTION));
  GATE_OPTIONS.forEach((text, i) => {
    const label = makeEl("label");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "gisun-gate";
    radio.value = String(i);
    label.append(radio, makeEl("span", "", text));
    options.appendChild(label);
  });
  const error = makeEl("p", "gisun-gate-error");
  error.setAttribute("role", "alert");
  error.hidden = true;
  const submit = makeEl("button", "gisun-modal-ok", "Submit");
  submit.type = "submit";

  modal.addEventListener("submit", (e) => {
    e.preventDefault();
    const picked = modal.querySelector('input[name="gisun-gate"]:checked');
    if (!picked || Number(picked.value) !== GATE_CORRECT_INDEX) {
      error.textContent = GATE_WRONG_MESSAGE;
      error.hidden = false;
      return; // input stays disabled
    }
    chrome.storage.local.set({ isPassed: true }, () => passGate(overlay));
  });

  modal.append(title, options, error, submit);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  modal.querySelector("input")?.focus();
}

function passGate(overlay) {
  gateActive = false;
  gateObserver?.disconnect();
  document.removeEventListener("keydown", blockSend, true);
  document.removeEventListener("click", blockSend, true);
  overlay.remove();
  enableInputs();
}

chrome.storage.local.get({ isPassed: false }, ({ isPassed }) => {
  if (!isPassed) showGate();
});
