"""
Nov 20: short full sentences (3-4 words) become claims checked for C3/C4 only.
    python -m unittest tests.test_short_claims
"""

import unittest

from gisun.agents.plan import plan
from gisun.preprocess import preprocess

TEXT = ("Tourists follow maps. Locals know shortcuts. Tip. What changed? Subscribe. "
        "About 40% of visitors return within a year, according to the city tourism office.")


class ShortClaims(unittest.TestCase):
    def setUp(self):
        self.ctx = preprocess(TEXT, all_sentences=True)
        self.by_sentence = {c["sentence"]: c for c in self.ctx.claims}

    def test_short_sentences_become_claims(self):
        # 3-word sentences are claims and marked short
        for s in ("Tourists follow maps.", "Locals know shortcuts."):
            self.assertIn(s, self.by_sentence)
            self.assertTrue(self.by_sentence[s]["short"])

    def test_tiny_lines_and_questions_are_still_skipped(self):
        for s in ("Tip.", "What changed?", "Subscribe."):
            self.assertNotIn(s, self.by_sentence)

    def test_bullets_are_not_words(self):
        # Nov 23 fix: "- People adapt." is 2 words, not 3, so it is skipped; a bulleted 3-word line is still checked
        ctx = preprocess("- People adapt.\n- Tourists follow maps.\n", all_sentences=True)
        sentences = [c["sentence"] for c in ctx.claims]
        self.assertFalse(any("People adapt" in s for s in sentences))
        self.assertTrue(any("Tourists follow maps" in s for s in sentences))

    def test_long_sentences_are_not_short(self):
        long = next(c for c in self.ctx.claims if "40%" in c["sentence"])
        self.assertFalse(long["short"])

    def test_short_claims_get_only_c3_c4(self):
        tasks = plan(self.ctx, use_model=False, open_criteria=True)["tasks"]
        for s in ("Tourists follow maps.", "Locals know shortcuts."):
            self.assertTrue(set(tasks[self.by_sentence[s]["claim_id"]]) <= {"C3", "C4"})
        long = next(c for c in self.ctx.claims if "40%" in c["sentence"])
        self.assertIn("C1", tasks[long["claim_id"]])  # long claims keep their usual checks

    def test_off_without_all_sentences(self):
        # the rules-only mode (no all_sentences) is unchanged: short sentences are not claims
        ctx = preprocess(TEXT)
        self.assertFalse(any(c["sentence"] == "Tourists follow maps." for c in ctx.claims))


if __name__ == "__main__":
    unittest.main()
