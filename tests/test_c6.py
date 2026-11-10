"""
C6 (unsupported cause and effect): the labeling rules in docs/labeling_rules.md, with the
sentences GiSuN wrongly flagged on our labeled answers. Scripted fake model, no backend needed.
    python -m unittest tests.test_c6
"""

import json
import re
import unittest

from gisun import llm
from gisun.criteria import CRITERIA, c6_prefilter
from gisun.pipeline import run
from gisun.preprocess import preprocess
from gisun.tools.language import heading_or_fragment, reported_viewpoint
from tests import fake_stats

# Reported viewpoints (rule 3) and headings / fragments (rule 2): decided by the pre-filter
ATTRIBUTED = [
    "Some economists, like Larry Summers, argued this added too much demand to an economy that couldn't produce enough.",
    "Critics say it can cast doubt on the achievements of minority students who would have been admitted anyway.",
    "Critics argue that higher labor costs lead employers to hire fewer workers, cut hours, or automate.",
    "Opponents claimed that the new tax caused small businesses to close.",
    "Psychologist Jonathan Haidt, author of *The Anxious Generation* (2024), argues this timing points to social media as a major cause.",
    "- **Less reliance on public assistance:** Supporters argue that when wages are too low, taxpayers end up subsidizing employers.",
]
HEADINGS = [
    "Possible reasons for the 2020 increase",
    "**Possible reasons for the 2020 increase**",
    "**Why it changes each year**",
    "## Causes of the decline",
    "Why did prices rise so quickly after 2021?",
]
# Reach the agent: the guidance, not the pre-filter, decides these
HEDGED = [
    "- **Weight:** EVs are heavier, which can increase tire wear and particle pollution.",
    "- **Higher prices:** Businesses may pass costs on to consumers.",
    "Effectiveness also tends to be lower for H3N2 strains and in older adults.",
    "Diabetes is associated with an increased risk of hearing loss.",
]
COMMON = [
    "When housing prices fell, losses spread rapidly.",
    "EVs produce no exhaust while driving, which improves local air quality.",
]
CAUSAL = "Pilates and walking positively impact quality of life, depression and anxiety."
# Vague evidence is not a reported viewpoint: still a claim the agent must judge (gold_example ex3)
STUDIES = "Studies show that immigration caused most of that growth."


class C6Model:
    """Follows the C6 guidance it is shown: 'not_met' for hedged wording and common knowledge, 'met'
    otherwise. Records every C6 task, so a test can see what reached the agent and what it was told."""

    HEDGE = re.compile(r"\b(can|may|might|could|tends to|is associated with)\b")

    def __init__(self):
        self.c6_tasks = []

    def __call__(self, messages, tools):
        system, task = messages[0]["content"], messages[1]["content"]
        if "plan a critical-reading" in system:
            claims = json.loads(task.split("Claims:\n", 1)[1])
            return {"content": json.dumps({"tasks": [{"claim_id": c["claim_id"], "criterion": k, "reason": "fits"}
                                                     for c in claims for k in c["candidates"]]}), "tool_calls": []}
        if "review another agent" in system:
            return {"content": json.dumps({"verdict": "approve", "problems": []}), "tool_calls": []}
        crit = re.search(r"Criterion (C\d)", task).group(1)
        claim = re.search(r"Claim: (.*)", task).group(1)
        if crit == "C6":
            self.c6_tasks.append({"claim": claim, "task": task})
            common = any(c in claim for c in COMMON)
            decision = "not_met" if self.HEDGE.search(claim) or common else "met"
            why = "common knowledge" if common else "hedged wording" if decision == "not_met" else "a causal claim as fact"
        else:
            decision, why = "not_met", "nothing of this kind in the sentence"
        return {"content": "", "tool_calls": [{"name": "submit_decision", "arguments": {
            "decision": decision, "strength": "moderate", "reasoning": f"The sentence is {why} for this criterion.",
            "evidence": [{"quote": claim.split()[0], "source": "response"}]}}]}


class PreFilter(unittest.TestCase):
    def test_reported_viewpoints(self):
        for s in ATTRIBUTED:
            with self.subTest(s=s):
                self.assertIsNotNone(reported_viewpoint(s))

    def test_headings_questions_and_fragments(self):
        for s in HEADINGS:
            with self.subTest(s=s):
                self.assertIsNotNone(heading_or_fragment(s))

    def test_claims_pass_through(self):
        for s in HEDGED + COMMON + [CAUSAL, STUDIES]:
            with self.subTest(s=s):
                self.assertIsNone(heading_or_fragment(s))
                self.assertIsNone(reported_viewpoint(s))

    def test_prefilter_fires_for_attributed_claims(self):
        for s in ATTRIBUTED:
            ctx = preprocess(s, all_sentences=True)
            with self.subTest(s=s):
                self.assertIsNotNone(c6_prefilter(ctx.claims[0]))
        self.assertIsNone(c6_prefilter(preprocess(STUDIES).claims[0]))

    def test_a_capitalized_preposition_is_not_a_source(self):
        s = ("- **Evidence from bans:** After states like California (in 1996) and Michigan (in 2006) banned "
             "affirmative action, enrollment of Black and Hispanic students dropped at their most selective universities.")
        self.assertIsNone(c6_prefilter(preprocess(s, all_sentences=True).claims[0]))
        named = preprocess("According to the Federal Reserve, low rates caused the housing boom.", all_sentences=True).claims[0]
        self.assertIn("attributed to a source", c6_prefilter(named))


class AgentSide(unittest.TestCase):
    def setUp(self):
        fake_stats.install(self)
        self.model = C6Model()
        llm.set_backend(self.model)

    def tearDown(self):
        llm.set_backend(None)

    def c6(self, text):
        r = run(text, mode="full")
        return {c["sentence"]: c["criteria"].get("C6") for c in r["claims"]}

    def test_attributed_and_headings_never_reach_the_agent(self):
        text = "\n".join(["**Possible reasons for the 2020 increase**", "**Why it changes each year**", *ATTRIBUTED])
        got = self.c6(text)
        self.assertEqual(len(got), 2 + len(ATTRIBUTED))
        for sentence, d in got.items():
            with self.subTest(s=sentence):
                self.assertEqual(d["decision"], "not_met")
                self.assertEqual(d["by"], "prefilter")
                self.assertIn("pre-filter", d["note"])
        self.assertEqual(self.model.c6_tasks, [], "no C6 task for a heading or a reported viewpoint")

    def test_hedged_and_common_knowledge_are_judged_by_the_agent(self):
        got = self.c6("\n".join(HEDGED + COMMON + [CAUSAL]))
        self.assertEqual(len(self.model.c6_tasks), len(HEDGED + COMMON) + 1)
        for sentence, d in got.items():
            with self.subTest(s=sentence):
                self.assertEqual(d["by"], "agent")
                self.assertEqual(d["decision"], "met" if sentence == CAUSAL else "not_met")

    def test_agent_sees_the_labeling_rules(self):
        self.c6(CAUSAL)
        task = self.model.c6_tasks[0]["task"]
        for rule in ("reported viewpoints", "common-knowledge", "can, may, might, could, tends to",
                     "is associated with", "two previous sentences", "headings, questions and fragments",
                     "Critics argue that higher labor costs", "EVs are heavier", "Possible reasons for the 2020"):
            self.assertIn(rule, task)

    def test_guidance_mirrors_the_labeling_rules(self):
        with open("docs/labeling_rules.md", encoding="utf-8") as f:
            doc = f.read()
        c6_doc = doc.split("## C6", 1)[1].split("\n## ", 1)[0]
        for example in ("Pilates and walking positively impact", "When housing prices fell, losses spread rapidly",
                        "EVs produce no exhaust while driving", "Critics argue that higher labor costs"):
            self.assertIn(example, c6_doc)
            self.assertIn(example, CRITERIA["C6"]["guidance"])


if __name__ == "__main__":
    unittest.main()
