// C3/C4 calibration quiz (docs/C3_C4_USER_CALIBRATION.md).
// Loaded after gate.js. Shown once, right after the access question is passed: the user answers
// 5 sample sentences, and their answers pick one mode for both C3 (loaded wording) and C4
// (sweeping generalization):
//   strict   matches our labels on 4 or 5 of the 5: our rules, C3 and C4 shown separately
//   general  skipped, or matched 3 or fewer: our rules don't fit how this user reads, so C3 and C4
//            are judged with looser rules and shown as one "worth checking" flag
// The answers and the mode stay in this browser (chrome.storage.local); only the mode is sent to
// the backend with each check (content.js -> background.js -> POST /pipeline "c34_mode").
//
// To take the quiz again: in the extension's service worker console run
//   chrome.storage.local.remove("c34QuizDone")   and refresh the ChatGPT tab.

// New sentences, not from our test sets (datasets/gold_*.json), so those tests stay fair.
// 3 we label "met" and 2 "not_met", so answering "Yes" to everything doesn't look like agreement.
const CALIBRATION_SENTENCES = [
  { text: "The senator's reckless plan would gut funding for public schools.",
    criterion: "C3", ours: "yes", why: "\"reckless\" and \"gut\" add a judgment where neutral words would do." },
  { text: "The 2010 earthquake devastated Port-au-Prince, killing more than 200,000 people.",
    criterion: "C3", ours: "no", why: "\"devastated\" is strong, but accurate for what happened." },
  { text: "Teenagers today can't focus on anything for more than a few minutes.",
    criterion: "C4", ours: "yes", why: "It treats every teenager the same; there are obvious exceptions." },
  { text: "Exercise usually improves sleep, though not for everyone.",
    criterion: "C4", ours: "no", why: "\"usually\" and \"not for everyone\" make it a hedged claim, not a sweeping one." },
  { text: "People from big cities are rude to strangers.",
    criterion: "C4", ours: "yes", why: "A stereotype about a whole group of people." },
];
const CALIBRATION_QUESTION = "Does this sentence use unfair, loaded wording or make a sweeping generalization?";
const CALIBRATION_CHOICES = [["yes", "Yes"], ["no", "No"], ["unsure", "Not sure"]];
const MODE_MESSAGES = {
  strict: "You see these sentences the way GiSuN does. GiSuN will flag loaded wording and sweeping generalizations separately, using its normal rules.",
  general: "You read these sentences differently from GiSuN, so GiSuN won't apply its own rules here. It will mark sentences that may be slanted or too sweeping as \"worth checking\", and you decide.",
};

// answers: one of "yes" | "no" | "unsure" per sentence, in CALIBRATION_SENTENCES order.
// Pure function (no DOM), so it can be tested on its own.
// "Not sure" is not a match: only a user who clearly reads like us gets our rules.
function decideC34Mode(answers, sentences = CALIBRATION_SENTENCES) {
  const matches = answers.filter((a, i) => a === sentences[i].ours).length;
  return matches >= 4 ? "strict" : "general";
}

function showCalibration() {
  const overlay = makeEl("div", "gisun-gate-overlay");
  const modal = makeEl("form", "gisun-modal gisun-gate gisun-calibration");
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-labelledby", "gisun-cal-title");

  const title = makeEl("h2", "", "How strict should GiSuN be?");
  title.id = "gisun-cal-title";
  const intro = makeEl("p", "", `${CALIBRATION_QUESTION} Answer 5 quick examples so GiSuN can match how you read.`);
  modal.append(title, intro);

  CALIBRATION_SENTENCES.forEach((s, i) => {
    const group = makeEl("fieldset", "gisun-gate-options gisun-cal-item");
    group.appendChild(makeEl("legend", "", `${i + 1}. "${s.text}"`));
    const row = makeEl("div", "gisun-cal-choices");
    CALIBRATION_CHOICES.forEach(([value, text]) => {
      const label = makeEl("label");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = `gisun-cal-${i}`;
      radio.value = value;
      label.append(radio, makeEl("span", "", text));
      row.appendChild(label);
    });
    group.appendChild(row);
    modal.appendChild(group);
  });

  const error = makeEl("p", "gisun-gate-error", "Please answer all 5, or skip.");
  error.setAttribute("role", "alert");
  error.hidden = true;
  const buttons = makeEl("div", "gisun-cal-buttons");
  const submit = makeEl("button", "gisun-modal-ok", "Submit");
  submit.type = "submit";
  const skip = makeEl("button", "gisun-cal-skip", "Skip");
  skip.type = "button";
  buttons.append(submit, skip);
  modal.append(error, buttons);

  skip.addEventListener("click", () => {
    // skipping tells us nothing about how the user reads, so our rules aren't applied (general mode)
    chrome.storage.local.set({ c34QuizDone: true, c34Mode: "general", c34Answers: null }, () => overlay.remove());
  });
  modal.addEventListener("submit", (e) => {
    e.preventDefault();
    const answers = CALIBRATION_SENTENCES.map((_, i) => modal.querySelector(`input[name="gisun-cal-${i}"]:checked`)?.value);
    if (answers.some((a) => !a)) {
      error.hidden = false;
      return;
    }
    const mode = decideC34Mode(answers);
    chrome.storage.local.set({ c34QuizDone: true, c34Mode: mode, c34Answers: answers }, () => {
      showCalibrationResult(modal, answers, mode, () => overlay.remove());
    });
  });

  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  modal.querySelector("input")?.focus();
}

// After the quiz: the chosen mode, and GiSuN's view of each sentence the user answered differently
function showCalibrationResult(modal, answers, mode, close) {
  modal.replaceChildren();
  const title = makeEl("h2", "", "Thanks!");
  title.id = "gisun-cal-title";
  modal.append(title, makeEl("p", "", MODE_MESSAGES[mode]));

  const different = CALIBRATION_SENTENCES
    .map((s, i) => ({ ...s, answer: answers[i] }))
    .filter((s) => s.answer !== "unsure" && s.answer !== s.ours);
  if (different.length) {
    modal.appendChild(makeEl("p", "", "Where GiSuN sees it differently:"));
    const list = makeEl("ul", "gisun-modal-list");
    different.forEach((s) => {
      const verdict = s.ours === "yes" ? "GiSuN would flag this" : "GiSuN would not flag this";
      list.appendChild(makeEl("li", "", `"${s.text}" ${verdict}: ${s.why}`));
    });
    modal.appendChild(list);
  }
  const done = makeEl("button", "gisun-modal-ok", "Done");
  done.type = "button";
  done.addEventListener("click", close);
  modal.appendChild(done);
  done.focus();
}

// Called by gate.js right after the access question is passed, and on every page load
function maybeShowCalibration() {
  chrome.storage.local.get({ isPassed: false, c34QuizDone: false }, ({ isPassed, c34QuizDone }) => {
    if (isPassed && !c34QuizDone && !document.querySelector(".gisun-calibration")) showCalibration();
  });
}

if (typeof module !== "undefined") {
  module.exports = { decideC34Mode, CALIBRATION_SENTENCES }; // for tests/test_calibration.js (Node)
} else {
  maybeShowCalibration();
}
