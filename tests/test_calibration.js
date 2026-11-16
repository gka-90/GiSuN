// The C3/C4 quiz's mode choice (extension/calibration.js), run with:  node tests/test_calibration.js
const assert = require("node:assert");
const { decideC34Mode, CALIBRATION_SENTENCES } = require("../extension/calibration.js");

// 5 sentences, 3 we flag and 2 we don't (so answering "Yes" to everything doesn't look like agreement)
assert.strictEqual(CALIBRATION_SENTENCES.length, 5);
assert.strictEqual(CALIBRATION_SENTENCES.filter((s) => s.ours === "yes").length, 3);

const cases = [
  [["yes", "no", "yes", "no", "yes"], "strict"], // matches us on all 5
  [["yes", "yes", "yes", "no", "yes"], "strict"], // 4 of 5 is enough
  [["yes", "yes", "yes", "yes", "yes"], "general"], // 3 of 5: our rules don't fit this reader
  [["no", "no", "no", "no", "no"], "general"],
  [["unsure", "no", "yes", "no", "yes"], "strict"], // 4 matches and one "Not sure"
  [["unsure", "unsure", "yes", "no", "yes"], "general"], // "Not sure" is not a match
];
for (const [answers, expected] of cases) assert.strictEqual(decideC34Mode(answers), expected, answers.join(","));
console.log(`ok: ${cases.length} quiz cases`);
