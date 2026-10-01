"""
Pipeline tests with a scripted fake model (no Ollama / HPC needed).
    python -m unittest tests.test_pipeline
"""

import json
import re
import unittest

from gisun import llm
from gisun.agents.check import check_decision
from gisun.pipeline import run
from gisun.preprocess import preprocess
from gisun.tools.numbers import compare_numbers

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
        word = {"C3": "disaster", "C5": "Experts say"}.get(crit, claim.split()[0])
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


if __name__ == "__main__":
    unittest.main()
