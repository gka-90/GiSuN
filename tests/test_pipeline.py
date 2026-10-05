"""
Pipeline tests with a scripted fake model (no Ollama / HPC needed).
    python -m unittest tests.test_pipeline
"""

import json
import re
import unittest
from unittest.mock import patch

from gisun import config, llm
from gisun.agents.check import check_decision
from gisun.pipeline import run
from gisun.preprocess import preprocess
from gisun.scoring import score_claim
from gisun.tools.numbers import compare_numbers, parse_value

TEXT = ("The U.S. unemployment rate averaged 12% in 2020. "
        "Officials stressed that the situation was not a crisis. "
        "Experts say the recovery was a disaster for small businesses.")


class FakeModel:
    """Acts like a careful agent; on its first C2 submit it invents a quote, to exercise the checks."""

    def __init__(self, judge_verdict="approve"):
        self.judge_verdict, self.calls, self.c2_tries = judge_verdict, 0, 0

    def __call__(self, messages, tools):
        self.calls += 1
        system, task = messages[0]["content"], messages[1]["content"]
        if "plan a critical-reading" in system:
            claims = json.loads(task.split("Claims:\n", 1)[1])
            return {"content": json.dumps({"tasks": [{"claim_id": c["claim_id"], "criterion": k, "reason": "fits"}
                                                     for c in claims for k in c["candidates"]]}), "tool_calls": []}
        if "review another agent" in system:
            return {"content": json.dumps({"verdict": self.judge_verdict,
                                           "problems": ["strength too high"] if self.judge_verdict == "revise" else []}),
                    "tool_calls": []}
        crit = re.search(r"Criterion (C\d)", task).group(1)
        claim = re.search(r"Claim: (.*)", task).group(1)
        done = [m for m in messages if m["role"] == "tool"]
        submit = lambda **a: {"content": "", "tool_calls": [{"name": "submit_decision", "arguments": a}]}
        call = lambda n, **a: {"content": "", "tool_calls": [{"name": n, "arguments": a}]}

        if crit == "C2":
            if len(done) == 0:
                return call("search", query="unemployment rate 2020 annual average")
            if len(done) == 1:
                return call("read_source", source_id="bls-unemployment-2020")
            if len(done) == 2:
                return call("compare_numbers", claim_value="12%", source_value="8.1 percent")
            self.c2_tries += 1
            if self.c2_tries == 1:  # invented quote -> must be rejected
                return submit(decision="met", strength="strong", reasoning="The source gives a different annual average.",
                              evidence=[{"quote": "averaged 9 percent", "source": "bls-unemployment-2020"}])
            return submit(decision="met", strength="strong", reasoning="BLS reports an 8.1 percent annual average, not 12%.",
                          evidence=[{"quote": "averaged 8.1 percent in 2020", "source": "bls-unemployment-2020"}])
        if crit == "C3" and "not a crisis" in claim:
            if not done:
                return call("context_cues", term="crisis")
            return submit(decision="not_met", strength="moderate", reasoning="The word crisis is negated, so it is not loaded use.",
                          evidence=[{"quote": "not a crisis", "source": "response"}])
        if crit == "C1":
            return submit(decision="met", strength="strong", reasoning="The 12% figure has no named source anywhere nearby.",
                          evidence=[{"quote": "12%", "source": "response"}])
        word = {"C3": "disaster", "C5": "Experts say"}.get(crit, "")
        if not word or word not in claim:  # open criteria also run on sentences without that word
            word = claim.split()[0]
        return submit(decision="met", strength="moderate", reasoning=f"The wording {word} is used without a specific basis.",
                      evidence=[{"quote": word, "source": "response"}])


class PipelineTest(unittest.TestCase):
    def tearDown(self):
        llm.set_backend(None)

    def test_full_mode_agent_decisions(self):
        fake = FakeModel()
        llm.set_backend(fake)
        r = run(TEXT, mode="full")
        find = lambda pre: next(x for x in r["claims"] if x["sentence"].startswith(pre))
        stat = find("The U.S. unemployment")
        self.assertEqual(stat["criteria"]["C2"]["decision"], "met")
        self.assertEqual(stat["criteria"]["C2"]["by"], "agent")
        self.assertEqual(fake.c2_tries, 2, "the invented quote must be rejected once")
        self.assertEqual(stat["score"]["risk"], "high")
        self.assertEqual(find("Officials")["criteria"]["C3"]["decision"], "not_met")
        self.assertEqual(r["plan"]["by"], "agent")
        self.assertEqual(r["agent_share"], 1.0)

    def test_judge_revision_is_recorded(self):
        llm.set_backend(FakeModel(judge_verdict="revise"))
        r = run(TEXT, mode="full")
        d = r["claims"][0]["criteria"]["C1"]
        self.assertEqual(len(d["judge"]), 2)
        self.assertTrue(d.get("judge_disputed"))

    def test_backend_failure_falls_back_to_rules(self):
        def broken(messages, tools):
            raise llm.LLMError("connection refused")
        llm.set_backend(broken)
        r = run(TEXT, mode="full")
        self.assertTrue(all(d["by"] == "rules" for c in r["claims"] for d in c["criteria"].values()))
        self.assertEqual(r["plan"]["by"], "rules")

    def test_rules_only_needs_no_model(self):
        r = run(TEXT, mode="rules_only")
        self.assertEqual(r["claims"][0]["criteria"]["C1"]["decision"], "met")

    def test_check_rejects_c2_without_comparison(self):
        ctx = preprocess(TEXT)
        problems = check_decision("C2", {"decision": "met", "strength": "strong",
                                         "reasoning": "It is wrong according to the data.",
                                         "evidence": [{"quote": "12%", "source": "response"}]}, ctx.claims[0], ctx, [])
        self.assertTrue(any("compare_numbers" in p for p in problems))

    def test_compare_numbers_units(self):
        self.assertTrue(compare_numbers("331 million", "331,449,281")["match"])
        self.assertFalse(compare_numbers("12%", "8.1 percent")["match"])
        self.assertFalse(compare_numbers("3%", "3 percentage points")["comparable"])
        self.assertTrue(compare_numbers("forty-two thousand", "42,000")["match"])
        self.assertAlmostEqual(parse_value("one in three")["value"], 1 / 3)
        self.assertIsNone(parse_value("most Americans"))

    # open problem #1: sentences no rule flagged
    def test_open_criteria_reach_unflagged_sentences(self):
        text = "Every worker was affected by the policy. Unemployment hit 12% in 2020."
        llm.set_backend(FakeModel())
        full = run(text, mode="full")
        unflagged = next(c for c in full["claims"] if c["sentence"].startswith("Every worker"))
        self.assertFalse(unflagged["detector_hit"])
        self.assertTrue({"C3", "C4", "C5", "C6"} <= set(unflagged["criteria"]))
        self.assertFalse(any(c["sentence"].startswith("Every worker") for c in run(text, mode="rules_only")["claims"]))

    def test_open_criteria_can_be_turned_off(self):
        llm.set_backend(FakeModel())
        with patch.object(config, "OPEN_CRITERIA", False):
            r = run("Every worker was affected by the policy.", mode="full")
        self.assertEqual(r["claims"], [])

    # open problem #7: same measure, same year
    def test_c2_rule_needs_the_same_year(self):
        # the BLS sample gives 3.7 percent for 2019: that must not confirm an undated claim
        r = run("According to the Bureau of Labor Statistics, the unemployment rate is 3.7 percent.", mode="rules_only")
        self.assertEqual(r["claims"][0]["criteria"]["C2"]["decision"], "undetermined")
        r = run("Unemployment peaked at 14.8% in April 2020.", mode="rules_only")
        self.assertEqual(r["claims"][0]["criteria"]["C2"]["decision"], "not_met")

    def test_check_rejects_contradiction_without_year(self):
        ctx = preprocess("The unemployment rate is 12%.")
        ctx.record_read("bls-unemployment-2020", "The U.S. unemployment rate averaged 8.1 percent in 2020.")
        log = [{"tool": "compare_numbers", "args": {}, "output": compare_numbers("12%", "8.1 percent")}]
        problems = check_decision("C2", {"decision": "met", "strength": "strong",
                                         "reasoning": "BLS reports a different unemployment rate.",
                                         "evidence": [{"quote": "8.1 percent", "source": "bls-unemployment-2020"}]},
                                  ctx.claims[0], ctx, log)
        self.assertTrue(any("no year" in p for p in problems))

    # open problem #5: C1 + C5 are one attribution problem
    def test_attribution_cap(self):
        score = score_claim({"C1": {"decision": "met", "strength": "strong"},
                             "C5": {"decision": "met", "strength": "moderate"}})
        self.assertEqual(score["points"], 2)
        self.assertEqual(score["risk"], "medium")

    # open problem #3: only the most check-worthy claims get C2
    def test_c2_funnel_logs_dropped_claims(self):
        text = "Sales rose 5% in 2020. Costs rose 7% in 2021. Prices rose 9% in 2022."
        with patch.object(config, "C2_MAX_CLAIMS", 1):
            r = run(text, mode="rules_only")
        self.assertEqual(sum("C2" in c["criteria"] for c in r["claims"]), 1)
        self.assertEqual(sum(n.get("by") == "funnel" for n in r["plan"]["notes"]), 2)


if __name__ == "__main__":
    unittest.main()
