"""A claim number the agent gives without its percent sign still compares with a percent figure."""
import unittest

from gisun.criteria import c2_outcome
from gisun.tools.numbers import compare_numbers, with_unit


class UnitHint(unittest.TestCase):
    def test_sentence_percent_is_added(self):
        s = "Inflation hit 9.1% year-over-year in June 2022."
        self.assertEqual(with_unit("9.1", "", s), "9.1%")

    def test_unit_field_percent_is_added(self):
        self.assertEqual(with_unit("10.0", "%", ""), "10.0%")

    def test_count_stays_a_number(self):
        self.assertEqual(with_unit("23", "states", "23 states had adult obesity rates of 35% or higher"), "23")

    def test_already_has_sign_or_words(self):
        for v in ("85-90%", "2.5% to 3%", "$5 million"):
            self.assertEqual(with_unit(v, "%", ""), v)

    def test_bare_number_was_incomparable_before(self):
        self.assertFalse(compare_numbers("9.1", "9.1 percent")["comparable"])
        self.assertTrue(compare_numbers(with_unit("9.1", "%"), "9.1 percent")["comparable"])

    def test_outcome_uses_the_unit(self):
        rec = [{"record_id": "r1", "value_text": "10.0 percent"}]
        self.assertEqual(c2_outcome("10.0", "none", rec, "%")[0], "not_met")
        self.assertEqual(c2_outcome("10.0", "none", rec)[0], "undetermined")


if __name__ == "__main__":
    unittest.main()
