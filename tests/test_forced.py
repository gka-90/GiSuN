"""
Forced criteria (GISUN_FORCE_CRITERIA=1): every criterion a gold label asks about runs, and the
evaluation reports routing misses apart from judgment misses. Scripted fake model, no backend.
    python -m unittest tests.test_forced
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from evaluation.evaluate import evaluate
from gisun import config, llm
from gisun.pipeline import run, run_dataset
from tests import fake_stats
from tests.test_pipeline import FakeModel

# No number and no agentless cue in the first sentence, so plan.must_keep() doesn't put C1/C5 back
TEXT = ("Shea Fahy was one of the heroes of the Cork football team. "
        "The new tax caused hundreds of small shops to close within a year.")
LABELS = {"Shea Fahy was one": {"C5": "met", "C1": "not_met"},
          "The new tax caused": {"C6": "met"}}


class DroppingPlan(FakeModel):
    """Like FakeModel, but its Plan agent drops some criteria everywhere (with a reason), as the 32B
    model did on the public set."""

    DROP = ("C5", "C6")

    def __call__(self, messages, tools):
        if "plan a critical-reading" in messages[0]["content"]:
            claims = json.loads(messages[1]["content"].split("Claims:\n", 1)[1])
            keep = [{"claim_id": c["claim_id"], "criterion": k, "reason": "fits"}
                    for c in claims for k in c["candidates"] if k not in self.DROP]
            drop = [{"claim_id": c["claim_id"], "criterion": k, "reason": "does not credit unnamed authorities"}
                    for c in claims for k in c["candidates"] if k in self.DROP]
            return {"content": json.dumps({"tasks": keep, "dropped": drop}), "tool_calls": []}
        return super().__call__(messages, tools)


class Forced(unittest.TestCase):
    def setUp(self):
        fake_stats.install(self)
        llm.set_backend(DroppingPlan())

    def tearDown(self):
        llm.set_backend(None)

    def claim(self, r, prefix):
        return next(c for c in r["claims"] if c["sentence"].startswith(prefix))

    def test_routing_alone_drops_the_labeled_criteria(self):
        r = run(TEXT, mode="full")
        self.assertNotIn("C5", self.claim(r, "Shea")["criteria"])
        self.assertNotIn("C6", self.claim(r, "The new tax")["criteria"])
        self.assertFalse(r["forced_criteria"])

    def test_forced_runs_every_labeled_criterion(self):
        r = run(TEXT, mode="full", force=LABELS)
        shea, tax = self.claim(r, "Shea"), self.claim(r, "The new tax")
        self.assertTrue(r["forced_criteria"])
        for claim, cid in ((shea, "C5"), (shea, "C1"), (tax, "C6")):
            with self.subTest(cid=cid):
                self.assertIn(claim["criteria"][cid]["by"], ("agent", "rules"))  # rules = the Check agent's fallback
                self.assertTrue(claim["criteria"][cid]["forced"])  # not chosen by the routing
                self.assertNotIn(cid, r["plan"]["routed"][str(claim["claim_id"])])
        self.assertFalse(shea["criteria"]["C3"]["forced"])  # routed as usual
        self.assertTrue(any(n.get("by") == "forced" and n["criterion"] == "C5" for n in r["plan"]["notes"]))

    def test_forced_c2_brings_its_dependency(self):
        r = run("Prices rose 9% in 2022 across the country.", mode="full",
                force={"Prices rose 9%": {"C2": "undetermined"}})
        crits = r["claims"][0]["criteria"]
        self.assertIn("C1", crits)
        self.assertIn("C2", crits)

    def test_the_extension_is_never_forced(self):
        with patch.object(config, "FORCE_CRITERIA", True):
            r = run(TEXT, mode="full")  # server.py / api.py: no gold labels
        self.assertFalse(r["forced_criteria"])
        self.assertNotIn("C5", self.claim(r, "Shea")["criteria"])

    def test_evaluation_reports_routed_and_forced(self):
        with tempfile.TemporaryDirectory() as d:
            gold = os.path.join(d, "gold.json")
            json.dump([{"id": "t1", "question": "", "text": TEXT, "labels": LABELS}], open(gold, "w"))
            run_dataset(gold, "full", os.path.join(d, "plain"), force=False)
            run_dataset(gold, "full", os.path.join(d, "forced"), force=True)
            plain, forced = evaluate(gold, os.path.join(d, "plain")), evaluate(gold, os.path.join(d, "forced"))
            with self.assertRaises(ValueError):  # don't mix forced and routed items in one folder
                run_dataset(gold, "full", os.path.join(d, "plain"), force=True)
        self.assertEqual(plain["decided_by"].get("not_run"), 3)          # C1 never offered, C5 and C6 dropped
        self.assertNotIn("not_run", forced["decided_by"])                 # every pair ran
        self.assertEqual(plain["rq1_overall"], plain["routing"]["rq1_overall"])
        self.assertEqual(forced["routing"]["rq1_overall"], plain["rq1_overall"])  # same routing, same decisions
        self.assertGreater(forced["rq1_overall"]["recall"], forced["routing"]["rq1_overall"]["recall"])
        for m in (plain, forced):
            self.assertEqual(m["routing"]["missed"], {"C1": {"not_candidate": 1}, "C5": {"plan_dropped": 1},
                                                      "C6": {"plan_dropped": 1}})


if __name__ == "__main__":
    unittest.main()
