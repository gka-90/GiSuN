"""Sources named as "an assessment by X" or "X revealed" (C1 false positives on gold_public_1)."""
import unittest

from gisun.tools.attribution import find_attribution


class TestNamedSources(unittest.TestCase):
    def test_named(self):
        for s in (
            "A post-storm assessment by the Mississippi Emergency Management Agency revealed over 900 "
            "businesses in Jackson County sustained damage.",
            "A 2021 analysis from Pew found that 40% agree.",
            "Billboard revealed that ABC had proposed an investment of $6.25 million.",
            "Lead has a density of 11.34 g/cm3 (Source: 1 2 Thornton).",
            "In 1929-30 he scored 50 points (Source: ↑ Hughes et al. 2003).",
            "The storm damaged 101,241 homes (Source: Hurricane Andrew).",
            "McCartney was ranked the 11th greatest singer of all time by Rolling Stone.",
            "According to the New York State Department of Labor, the rate was 4.3%.",
            "The New York Times reported that 40% of renters moved.",
            "Large chains detailed by geographer Roger Brunet: BUT (240 staff), Carrefour (150 staff).",
            "Michigan is classified as one of 115 Doctoral Universities by the Carnegie Classification.",
        ):
            with self.subTest(s=s):
                self.assertTrue(find_attribution(s)["names_specific_source"])

    def test_not_named(self):
        for s in (
            "A study by researchers found 40% improvement.",
            "An assessment by experts showed 12% growth.",
            "Data from several sources suggests 30% of users quit.",
            "Unemployment averaged 12% over the decade.",
            "The club was then docked 30 points for financial irregularities.",
            "He was ranked first in the league for most of the season.",
            "New research shows 40% of students use AI.",
        ):
            with self.subTest(s=s):
                self.assertFalse(find_attribution(s)["names_specific_source"])


if __name__ == "__main__":
    unittest.main()


class TestCheckC1(unittest.TestCase):
    def test_met_must_deal_with_found_source(self):
        from gisun.agents.check import _check_c1
        claim = {"sentence": "A post-storm assessment by the Mississippi Emergency Management Agency revealed over "
                             "900 businesses sustained damage.", "context_before": []}
        self.assertTrue(_check_c1("met", "No specific source is named for the 900 figure.", claim))
        self.assertFalse(_check_c1("met", "The Mississippi agency is named, but it only covers the 900 figure, "
                                          "not the state total.", claim))
        self.assertFalse(_check_c1("not_met", "The Mississippi Emergency Management Agency is named.", claim))
        self.assertFalse(_check_c1("met", "No source given.", {"sentence": "Unemployment averaged 12%.",
                                                               "context_before": []}))
