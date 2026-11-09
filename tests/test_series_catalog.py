"""New catalog entries stay off until verified, and education-specific claims don't fall back to
the overall unemployment rate. No network."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gisun.tools import retrieval  # noqa: E402


class TestCatalog(unittest.TestCase):
    def test_unverified_entries_are_off(self):
        off = [e["id"] for e in retrieval.all_series() if e.get("verified") is False]
        self.assertTrue(off)
        on = {e["id"] for e in retrieval.catalog()}
        self.assertFalse(on & set(off))

    def test_every_new_entry_has_a_test(self):
        for e in retrieval.all_series():
            if "verified" in e:
                self.assertIn("test", e, e["id"])
                self.assertEqual(len(e["test"]["range"]), 2, e["id"])

    def test_college_unemployment_never_matches_the_overall_rate(self):
        ids = {e["id"] for e in retrieval.matching_series("unemployment rate of college graduates")}
        self.assertFalse(ids & {"bls_unemployment_u3", "wb_unemployment", "dc_unemployment"})

    def test_overall_unemployment_still_matches(self):
        ids = {e["id"] for e in retrieval.matching_series("unemployment rate")}
        self.assertIn("bls_unemployment_u3", ids)


if __name__ == "__main__":
    unittest.main()
