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
        ):
            with self.subTest(s=s):
                self.assertTrue(find_attribution(s)["names_specific_source"])

    def test_not_named(self):
        for s in (
            "A study by researchers found 40% improvement.",
            "An assessment by experts showed 12% growth.",
            "Data from several sources suggests 30% of users quit.",
            "Unemployment averaged 12% over the decade.",
        ):
            with self.subTest(s=s):
                self.assertFalse(find_attribution(s)["names_specific_source"])


if __name__ == "__main__":
    unittest.main()
