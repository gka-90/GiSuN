"""Every criterion says why it came out undetermined, not only C2."""
import unittest

from gisun.agents.check import decision_status


def call(tool):
    return [{"tool": tool, "output": {}}]


class DecisionStatus(unittest.TestCase):
    def test_a_real_decision_is_decided(self):
        for d in ("met", "not_met"):
            self.assertEqual(decision_status("C5", {"decision": d}, []), "decided")

    def test_undetermined_without_a_tool_call(self):
        self.assertEqual(decision_status("C5", {"decision": "undetermined"}, []), "no_tool_call")
        self.assertEqual(decision_status("C5", {"decision": "undetermined"}, call("wordlist_lookup")),
                         "no_tool_call")  # not one of C5's own tools

    def test_undetermined_after_looking(self):
        d = {"decision": "undetermined", "evidence": []}
        self.assertEqual(decision_status("C5", d, call("find_attribution")), "no_evidence")
        d = {"decision": "undetermined", "evidence": [{"quote": "studies show"}]}
        self.assertEqual(decision_status("C5", d, call("find_attribution")), "weighed")

    def test_c2_keeps_its_own_codes(self):
        self.assertEqual(decision_status("C2", {"decision": "not_met"}, []), "checked")
        self.assertEqual(decision_status(
            "C2", {"decision": "undetermined", "claim_fields": {"measure": "x", "place": "US", "period": ""}}, []),
            "no_period")


if __name__ == "__main__":
    unittest.main()
