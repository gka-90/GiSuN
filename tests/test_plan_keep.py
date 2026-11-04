"""
Plan agent safety net (plan.must_keep): on public part 1 the 32B Plan agent dropped C5 for
"is believed" / "is regarded as" / "allegedly" ("does not credit unnamed authorities") and C1
because "the claim cites a specific source". C1 stays whenever there is a number, C5 whenever
there is an agentless attribution cue. Scripted fake model, no backend.
    python -m unittest tests.test_plan_keep
"""

import unittest

from gisun import llm
from gisun.pipeline import run
from gisun.tools.attribution import agentless_attribution
from gisun.tools.numbers import numbers_in
from tests import fake_stats
from tests.test_forced import DroppingPlan

AGENTLESS = [
    "It is believed that the sweat from Lord Shiva's body formed the Bhimarathi river.",
    "Shea Fahy is regarded as one of the heroes of the Cork senior football team.",
    "A statue of Saint Pio attracted attention in 2002 when it allegedly wept tears of blood.",
    "It has a yearly fete and is generally considered a safe place to live.",
    "He also reportedly abused and killed neighborhood pets.",
    "The family car can be seen as a symbol of decadence and excess.",
    "Studies show it lowers the risk of hospitalization and death.",
]
NO_CUE = ["By 1880 the area was producing a million bushels of barley a year.",
          "The album was produced by Ian Broudie of The Lightning Seeds."]
NUMBERS = {"Lead has a density of 11.34 g/cm3, which is greater than that of most common metals.": "11.34",
           "In one day matches, he took 11 wickets at 27.72.": "11",
           "High temperatures during July averaging 22 °C (72 °F) are typical.": "22"}
NOT_NUMBERS = ["On May 28 1974 the square was the location of a terrorist bombing.",
               "TRIAL REGISTRATION NUMBER: ISRCTN42072606.", "The 1961–62 season was his last."]


class Cues(unittest.TestCase):
    def test_agentless_cue(self):
        for s in AGENTLESS:
            with self.subTest(s=s):
                self.assertIsNotNone(agentless_attribution(s))
        for s in NO_CUE:
            with self.subTest(s=s):
                self.assertIsNone(agentless_attribution(s))

    def test_numbers_but_not_dates(self):
        for s, first in NUMBERS.items():
            with self.subTest(s=s):
                self.assertEqual(numbers_in(s)[0], first)
        for s in NOT_NUMBERS:
            with self.subTest(s=s):
                self.assertEqual(numbers_in(s), [])


class KeepRule(unittest.TestCase):
    def setUp(self):
        fake_stats.install(self)
        model = DroppingPlan()
        model.DROP = ("C1", "C5")
        llm.set_backend(model)

    def tearDown(self):
        llm.set_backend(None)

    def test_c5_is_kept_for_an_agentless_cue(self):
        r = run(" ".join(AGENTLESS + NO_CUE[1:]), mode="full")
        for c in r["claims"]:
            with self.subTest(s=c["sentence"]):
                self.assertEqual("C5" in c["criteria"], c["sentence"] in AGENTLESS)
        kept = [n for n in r["plan"]["notes"] if n.get("by") == "keep_rule" and n["criterion"] == "C5"]
        self.assertEqual(len(kept), len(AGENTLESS))
        self.assertFalse(any(n.get("by") == "agent" and n["criterion"] == "C5" and
                             r["claims"][n["claim_id"]]["sentence"] in AGENTLESS for n in r["plan"]["notes"]))

    def test_c1_is_kept_whenever_there_is_a_number(self):
        r = run(" ".join([*NUMBERS, NO_CUE[1]]), mode="full")
        for c in r["claims"]:
            with self.subTest(s=c["sentence"]):
                self.assertEqual("C1" in c["criteria"], c["sentence"] in NUMBERS)

    def test_rules_only_baseline_is_unchanged(self):
        llm.set_backend(None)
        r = run(" ".join(NUMBERS), mode="rules_only")
        self.assertFalse(any("C1" in c["criteria"] for c in r["claims"]))


if __name__ == "__main__":
    unittest.main()
