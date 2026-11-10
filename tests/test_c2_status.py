import unittest

from gisun.agents.check import c2_status


def lookup(**out):
    return [{"tool": "lookup_statistic", "output": out}]


class C2StatusTest(unittest.TestCase):
    def test_checked(self):
        self.assertEqual(c2_status({"decision": "not_met"}, []), "checked")
        self.assertEqual(c2_status({"decision": "met"}, []), "checked")

    def test_no_series(self):
        d = {"decision": "undetermined"}
        self.assertEqual(c2_status(d, lookup(records=[], note="no official series for 'x' in the catalog, so C2 can't be checked.")), "no_series")
        self.assertEqual(c2_status(d, lookup(records=[], note="no series for 'x' covers Ohio with annual figures.")), "no_series_for_place")
        self.assertEqual(c2_status(d, lookup(records=[], note="period 'soon' must be a year (2020) or a month (2020-04).")), "no_period")
        self.assertEqual(c2_status(d, lookup(records=[], note="no official figure for exactly this measure, place and period.")), "no_record")
        self.assertEqual(c2_status(d, lookup(records=[], skipped=[{"series": "a", "reason": "boom"}])), "lookup_error")

    def test_without_lookup(self):
        self.assertEqual(c2_status({"decision": "undetermined", "claim_fields": {"measure": "x", "place": "US", "period": ""}}, []), "no_period")
        self.assertEqual(c2_status({"decision": "undetermined", "claim_fields": {"measure": "x", "place": "US", "period": "2020"}}, []), "not_looked_up")

    def test_rule_status_is_mapped(self):
        self.assertEqual(c2_status({"decision": "undetermined", "status": "source_conflict"}, []), "source_conflict")


if __name__ == "__main__":
    unittest.main()
