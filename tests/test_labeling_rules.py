"""
The agents get the same rules as the labelers: every example sentence in docs/labeling_rules.md
for C3-C6 is in that criterion's guidance.
    python -m unittest tests.test_labeling_rules
"""

import unittest

from gisun.criteria import CRITERIA, SHARED_RULES
from gisun.preprocess import preprocess

EXAMPLES = {
    "C3": ["Mark Oaten is a disgraced Liberal Democrat politician", "Opponents argued that race-conscious admissions",
           "Concerns include cyberbullying, body image issues, sleep disruption", "devastated", "illegal alien"],
    "C4": ["Everyone concentrates better after a good breakfast", "Only a member of Congress can formally introduce a bill",
           "More time doesn't always mean better results", "Republicans have especially low trust", "all 12 patients"],
    "C5": ["Studies show it lowers the risk of hospitalization and death",
           "Critics argue these costs fall hardest on working-class people", "The CDC recommends an annual flu vaccine",
           # added Nov 10 with the new C5 rules (made-up sentences, not from the gold set)
           "The castle is said to be the oldest in Europe",
           "Most researchers agree that screen time slows toddlers' language development",
           "Some economists say a tax cut would raise growth",
           "Experts caution that the long-term effects are still unclear",
           "Experts recommend getting enough sleep"],
    "C6": ["Pilates and walking positively impact quality of life, depression and anxiety",
           "When housing prices fell, losses spread rapidly", "EVs produce no exhaust while driving",
           "Critics argue that higher labor costs lead employers to hire fewer workers",
           # added Nov 10 with the new C6 rules (made-up sentences, not from the gold set)
           "The drop in crime is largely explained by more police on the streets",
           "Because Python strings are immutable, changing one creates a new string",
           "The flood destroyed crops and displaced about 40,000 people"],
}


class GuidanceMirrorsTheLabelingRules(unittest.TestCase):
    def test_examples(self):
        with open("docs/labeling_rules.md", encoding="utf-8") as f:
            doc = f.read()
        for cid, examples in EXAMPLES.items():
            section = " ".join(doc.split(f"## {cid}:", 1)[1].split("\n## ", 1)[0].split())
            for e in examples:
                with self.subTest(cid=cid, example=e):
                    self.assertIn(e, section)
                    self.assertIn(e, CRITERIA[cid]["guidance"])

    def test_rules_for_every_criterion(self):
        for cid in ("C3", "C4", "C5"):
            self.assertIn(SHARED_RULES, CRITERIA[cid]["guidance"])
        for words in ("headings, questions and fragments", "reported viewpoints", "common knowledge",
                      "two previous sentences", "When in doubt, decide 'not_met'"):
            self.assertIn(words, SHARED_RULES)


if __name__ == "__main__":
    unittest.main()
