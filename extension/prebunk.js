// Prebunking banner: when the user asks a question in a known category, warn them
// about that category's common pitfalls *before* they read the answer.
// Loaded after content.js, so RESPONSE_SELECTOR / PROMPT_INPUT_SELECTOR / makeEl are available.

const PREBUNK_WARNINGS = {
  Medicine: [
    "Chatbots can sound confident about doses, symptoms and diagnoses while being wrong. Confirm with a doctor or pharmacist.",
    "Watch for a single study (\"a study found...\") presented as settled fact.",
    "Health numbers often leave out who was studied, how many people, and compared to what.",
  ],
  History: [
    "Chatbots sometimes invent quotes, dates and sources that sound real. Check a primary or reputable source.",
    "The same event can be framed very differently (\"riot\" vs. \"uprising\"). Notice which word is used.",
    "Be wary of a single, simple cause for a complex event.",
  ],
  Politics: [
    "Loaded labels (\"radical\", \"regime\", \"freedom fighters\") signal a side. Look for neutral wording.",
    "Check that statistics come with a named source and date; political numbers are often cherry-picked.",
    "A balanced-sounding answer can still leave out major viewpoints.",
  ],
};

// TODO: use the model to classify the question instead of keyword matching
const PREBUNK_KEYWORDS = {
  Medicine: ["symptom", "symptoms", "drug", "drugs", "doctor", "medication", "medicine", "dose", "dosage",
    "diagnosis", "disease", "treatment", "side effect", "side effects", "vaccine", "vaccines",
    "prescription", "illness", "infection", "cancer", "pain"],
  History: ["history", "historical", "century", "ancient", "empire", "revolution", "dynasty", "civil war",
    "world war", "colonial", "medieval", "battle", "war"],
  Politics: ["election", "elections", "vote", "voting", "president", "congress", "senate", "democrat",
    "democrats", "republican", "republicans", "policy", "government", "political", "politics",
    "immigration", "abortion", "gun control", "campaign", "politician", "legislation"],
};

let pendingPrebunk = null; // { category, existing: Set of responses on the page at submit time }

// Category with the most keyword hits; null if none match
function pickPrebunkCategory(question) {
  const lowered = question.toLowerCase();
  let best = null;
  let bestHits = 0;
  for (const [category, keywords] of Object.entries(PREBUNK_KEYWORDS)) {
    const hits = keywords.filter((k) => new RegExp(`\\b${k}\\b`).test(lowered)).length;
    if (hits > bestHits) {
      best = category;
      bestHits = hits;
    }
  }
  return best;
}

function readPrompt() {
  const input = document.querySelector(PROMPT_INPUT_SELECTOR);
  if (!input) return "";
  return input.tagName === "TEXTAREA" ? input.value : input.innerText;
}

// Capture phase, so the prompt is read before ChatGPT clears the box
function onPromptSubmit() {
  const category = pickPrebunkCategory(readPrompt());
  if (!category) return;
  pendingPrebunk = { category, existing: new Set(document.querySelectorAll(RESPONSE_SELECTOR)) };
}

// The response doesn't exist yet at submit time; put the banner above the first new one
function insertPendingBanner() {
  if (!pendingPrebunk) return;
  const response = [...document.querySelectorAll(RESPONSE_SELECTOR)]
    .find((r) => !pendingPrebunk.existing.has(r));
  if (!response) return;
  const { category } = pendingPrebunk;
  pendingPrebunk = null;
  response.parentNode.insertBefore(makePrebunkBanner(category), response);
}

function makePrebunkBanner(category) {
  const banner = makeEl("div", "gisun-prebunk");
  banner.setAttribute("role", "note");
  const close = makeEl("button", "gisun-prebunk-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "Close");
  close.addEventListener("click", () => banner.remove());

  const list = makeEl("ul");
  for (const warning of PREBUNK_WARNINGS[category]) list.appendChild(makeEl("li", "", warning));
  banner.append(close, makeEl("strong", "", `Before you read: common pitfalls in ${category.toLowerCase()} answers`), list);
  return banner;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.target.closest?.(PROMPT_INPUT_SELECTOR)) onPromptSubmit();
}, true);
document.addEventListener("click", (e) => {
  if (e.target.closest?.(SEND_BUTTON_SELECTOR)) onPromptSubmit();
}, true);
new MutationObserver(insertPendingBanner).observe(document.body, { childList: true, subtree: true });
