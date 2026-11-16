"""
The user's C3/C4 mode from the extension quiz (docs/C3_C4_USER_CALIBRATION.md):
strict = our rules; general (quiz skipped or answered differently) = looser C3/C4 rules, and C3 and
C4 count as one problem in the score.
    python -m unittest tests.test_c34_mode
"""

import unittest

from fastapi.testclient import TestClient

from gisun.criteria import CRITERIA, GENERAL_GUIDANCE, SHARED_RULES, guidance
from gisun.scoring import score_claim


class Guidance(unittest.TestCase):
    def test_strict_uses_our_rules(self):
        for cid in CRITERIA:
            self.assertEqual(guidance(cid, "strict"), CRITERIA[cid]["guidance"])

    def test_general_changes_only_c3_and_c4(self):
        for cid in CRITERIA:
            if cid in ("C3", "C4"):
                self.assertEqual(guidance(cid, "general"), GENERAL_GUIDANCE[cid])
                self.assertNotIn("When in doubt, decide 'not_met'", guidance(cid, "general"))
                self.assertNotIn(SHARED_RULES, guidance(cid, "general"))
            else:
                self.assertEqual(guidance(cid, "general"), CRITERIA[cid]["guidance"])


def _d(decision, strength):
    return {"decision": decision, "strength": strength, "reasoning": "r", "evidence": []}


class Scoring(unittest.TestCase):
    def test_general_counts_c3_and_c4_once(self):
        both = {"C3": _d("met", "strong"), "C4": _d("met", "moderate")}  # 2 + 1 points
        self.assertEqual(score_claim(both)["points"], 3)  # strict: two problems
        self.assertEqual(score_claim(both, "general")["points"], 2)  # general: one, the larger score

    def test_general_leaves_other_criteria_alone(self):
        decisions = {"C1": _d("met", "strong"), "C3": _d("met", "moderate")}
        self.assertEqual(score_claim(decisions, "general")["points"], score_claim(decisions)["points"])


class Api(unittest.TestCase):
    def test_rejects_unknown_mode(self):
        from server import app
        for mode in ("broad", "light"):  # earlier draft modes, no longer used
            res = TestClient(app).post("/pipeline", json={"text": "x", "c34_mode": mode})
            self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
