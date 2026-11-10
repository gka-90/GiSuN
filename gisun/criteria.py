"""
Criterion registry

Each criterion asks one yes/no question about one claim. "met" always means
"the problem is present" (the reader should be skeptical), so scoring can
treat all criteria the same way.

    id, name, question  what is being decided
    guidance            instructions shown to the task agent
    phase               execution phase; criteria in one phase run in parallel
    depends_on          {criterion: [decisions]} -- only run if that criterion came out that way
    tools               tool names the task agent may use
    severity            how much a "met" decision counts in scoring (by strength)
    applies(claim)      deterministic pre-filter the plan agent starts from
    open                True = in model modes, also run on claims the detectors didn't
                        trigger for it (open problem #1: the agents can only catch what
                        the rules miss if they get to see those sentences); or a
                        function(claim) that says which extra claims it runs on
    prefilter(claim)    optional: a reason string when the sentence can be decided "not_met"
                        without a model (a heading, a reported viewpoint); the pipeline then
                        records "not_met" and never sends the claim to the task agent

The guidance follows docs/labeling_rules.md (same wording and examples), so the agents and
the human labelers apply the same rules.

A decision is always one of DECISIONS. The agents make every decision; the only code that decides
is the C6 prefilter (headings, reported viewpoints). If an agent fails the result is "undetermined".
"""

import re

from gisun.tools.language import heading_or_fragment, reported_viewpoint
from gisun.tools.numbers import compare_numbers, numbers_in, parse_value

DECISIONS = ("met", "not_met", "undetermined")
STRENGTHS = ("strong", "moderate", "supporting")
LOADED_CATS = {"loaded_political_terms", "emotionally_charged_terms",
               "loaded_framing_of_events", "loaded_identity_or_group_terms"}


def _decision(decision, strength, reasoning, evidence=None, **extra):
    """Build a decision dict."""
    return {"decision": decision, "strength": strength, "reasoning": reasoning,
            "evidence": evidence or [], **extra}


def _terms(claim, cats):
    return [b for b in claim["bias_terms"] if b["category"] in cats]


# docs/labeling_rules.md, "Rules for every criterion", for the criteria that judge wording (C3-C5)
SHARED_RULES = ("Rules for every criterion: judge only this criterion (a different problem is 'not_met' here); "
                "headings, questions and fragments are never 'met'; reported viewpoints ('Critics argue ...', "
                "'Supporters say ...', 'Opponents claimed ...') describe a debate and are not the answer's own "
                "claim unless the answer itself endorses it; common knowledge a typical college student would "
                "accept without a source counts as support; a source or an explanation in the two previous "
                "sentences covers this sentence. When in doubt, decide 'not_met'.")


# ---- C2: statistic_contradicted ----------------------------------------------------------

def c2_outcome(value: str, hedge: str, records: list[dict]) -> tuple[str, list[dict]]:
    """The C2 decision the official figures give, by compare_numbers' tolerance rules:
    all match -> not_met, none match -> met, sources disagree or nothing comparable -> undetermined."""
    cmps = [{"record_id": r["record_id"], **compare_numbers(value, r["value_text"], hedge)} for r in records]
    matches = {c["match"] for c in cmps if c.get("comparable")}
    if matches == {True}:
        return "not_met", cmps
    if matches == {False}:
        return "met", cmps
    return "undetermined", cmps


# find_attribution reads "After states like California ... banned" as a source "After" that "states";
# a capitalized preposition or conjunction is never a source name
NOT_A_SOURCE = re.compile(r"(?i)(?:after|before|when|while|if|since|because|as|in|on|at|by|for|from|during|with|"
                          r"without|although|though|once|until|unlike|like|but|and|so|yet)\b")


def c6_prefilter(claim) -> str | None:
    """Labeling rules 2 and 3: headings, questions and fragments, and viewpoints reported as someone
    else's ('Critics argue ...', 'X says ...'), are never an unsupported causal claim of the answer's own."""
    if why := heading_or_fragment(claim["sentence"]):
        return f"The sentence is {why}, not a claim (headings and fragments are never 'met')."
    if who := reported_viewpoint(claim["sentence"]):
        return f"The sentence reports a viewpoint ({who!r}), not the answer's own causal claim."
    src = claim["attribution"]["source_text"] or ""
    if claim["attribution"]["names_specific_source"] and not NOT_A_SOURCE.match(src):
        return f"The causal claim is attributed to a source ({src!r})."
    return None


# ---- registry ----------------------------------------------------------------------------

CRITERIA = {
    "C1": {
        "name": "unsourced_statistic",
        "question": "Does the claim give a statistic or other quantitative claim without naming a specific source "
                    "(in this or the previous two sentences)?",
        "guidance": "Quantitative claims include numbers, but also records, trends and comparisons with no number: "
                    "'the highest ever', 'a record low', 'skyrocketed', 'the fastest-growing', 'outpaced inflation'. "
                    "A specific source is a named organisation, publication, dataset or link. 'Experts', 'studies' or "
                    "'reports' are NOT specific. Use find_attribution and context_window; a source in the previous "
                    "sentence counts if it clearly covers this claim.",
        "phase": 1, "depends_on": {},
        "tools": ["find_attribution", "context_window"],
        "severity": {"strong": 2, "moderate": 2, "supporting": 1},
        "applies": lambda c: bool(c["stat_values"]),
        # In model modes also a claim with no flagged statistic but a record/trend/comparison cue, or any
        # number the detector doesn't flag ("a density of 11.34 g/cm3"); the rules-only baseline keeps the
        # narrower gate, so its numbers stay comparable with earlier runs
        "open": lambda c: "quantitative" in c["signals"] or bool(numbers_in(c["sentence"])),
    },
    "C3": {
        "name": "loaded_language",
        "question": "Does the claim use slanted or emotionally loaded wording where a neutral word would do?",
        "guidance": "'met' only if the answer itself uses a word that carries a judgment where a neutral word "
                    "would say the same thing ('Mark Oaten is a disgraced Liberal Democrat politician': "
                    "'disgraced' adds a judgment). 'not_met' for: quoted or reported wording ('Opponents argued "
                    "that race-conscious admissions disadvantaged Asian American applicants' is a reported view); "
                    "strong but accurate words for documented facts ('devastated' for the Dust Bowl); words that "
                    "are the topic being explained, or only mentioned ('the term \"illegal alien\" is "
                    "controversial'); negated terms ('not a crisis'); neutral lists ('Concerns include "
                    "cyberbullying, body image issues, sleep disruption'). Check each flagged term with "
                    "context_cues. You may also report loaded wording the word list missed; quote it exactly. If "
                    "nothing was flagged, judge the sentence's own wording: most sentences are neutral, so "
                    "'not_met' is the usual answer. " + SHARED_RULES,
        "phase": 1, "depends_on": {},
        "tools": ["context_cues", "wordlist_lookup"],
        "severity": {"strong": 2, "moderate": 1, "supporting": 1},
        "applies": lambda c: bool(_terms(c, LOADED_CATS)),
        "open": True,
    },
    "C4": {
        "name": "overgeneralization",
        "question": "Does the claim make an absolute or sweeping statement (always, never, everyone ...) that the evidence can't support?",
        "guidance": "'met' only if the sentence makes an unqualified universal claim about people, groups or "
                    "outcomes ('always', 'never', 'everyone', or a claim about a whole group) that has obvious "
                    "exceptions ('Everyone concentrates better after a good breakfast'): a tendency turned into "
                    "a rule. 'not_met' for: literally true absolutes ('water always boils at a lower temperature at "
                    "altitude' is a physical law); rules and laws ('Only a member of Congress can formally "
                    "introduce a bill'); definitions; closed groups ('all 12 patients'); hedged sentences ('More "
                    "time doesn't always mean better results' is a hedge, not a generalization; so are often, "
                    "usually, most, can, may, tends to); comparisons backed by the previous sentence ('Republicans "
                    "have especially low trust' right after a Gallup figure). Use context_cues on the absolute "
                    "word: a negated 'always' is a hedge. " + SHARED_RULES,
        "phase": 1, "depends_on": {},
        "tools": ["context_cues"],
        "severity": {"strong": 2, "moderate": 1, "supporting": 1},
        "applies": lambda c: bool(_terms(c, {"absolutist_or_overgeneralizing_terms"})),
        "open": True,
    },
    "C5": {
        "name": "vague_attribution",
        "question": "Does the claim credit unnamed authorities (experts say, studies show) instead of a specific source?",
        "guidance": "'met' only if a factual claim rests on an unnamed authority ('studies show', 'experts say', "
                    "'research suggests', 'it is believed', 'is widely considered') and no specific source is in "
                    "the sentence or the two before it ('Studies show it lowers the risk of hospitalization and "
                    "death' is a fact resting on 'studies'). "
                    # Nov 10 review: 98 of 100 public weasel-word sentences were missed because no group was named
                    "Vague wording counts even when no group is named: 'is believed', 'is considered', 'is "
                    "regarded as', 'allegedly', 'reportedly', 'it is thought', 'is said to' ('The castle is "
                    "said to be the oldest in Europe' is 'met'). "
                    # Nov 10 review: "Most experts agree ..." was read as a debate opinion
                    "Experts, scientists, economists, researchers, surveys or studies used as support for a "
                    "concrete claim or for the answer's own conclusion are 'met', whatever the verb (agree, "
                    "think, note, argue): 'Most researchers agree that screen time slows toddlers' language "
                    "development' is 'met'. "
                    "Test question: is the vague group used as evidence "
                    "for a fact, or does it only name who believes something? 'not_met' for: naming who holds an "
                    "opinion in a debate ('Critics argue these costs fall hardest on working-class people', "
                    # Nov 10 review: one side of a debate is 'not_met' even when that side is experts
                    "'supporters say'); in a debate or a list of arguments for and against, any group that "
                    "presents one side, experts and economists included ('Some economists say a tax cut would "
                    "raise growth', listed as one argument for); "
                    # Nov 10 review: "Experts emphasize that the causes are still debated" adds caution only
                    "a vague source used only to add caution or uncertainty ('Experts caution that the "
                    "long-term effects are still unclear'); "
                    # Nov 10 review: "Experts commonly recommend limiting use ..." is everyday advice
                    "widely accepted, low-stakes everyday advice ('Experts recommend getting enough sleep'), "
                    "while disputed or risky advice stays 'met'; "
                    "a sentence that credits no one at all (a missing source is C1's job); a "
                    "specific source named in the sentence, or in the two before it if it covers this claim ('The CDC recommends an annual "
                    "flu vaccine'). "
                    # Nov 10 review: "Surveys have found ..." was left undetermined over common knowledge
                    "Common knowledge does not excuse a vague source used as evidence for a fact most readers "
                    "could not check themselves. "
                    "Use find_attribution with where='sentence' and where='previous'. " + SHARED_RULES,
        "phase": 1, "depends_on": {},
        "tools": ["find_attribution", "context_window"],
        "severity": {"strong": 2, "moderate": 1, "supporting": 1},
        "applies": lambda c: bool(_terms(c, {"vague_or_unsourced_attribution"})) or "attribution" in c["signals"],
        "open": True,
    },
    "C6": {
        "name": "unsupported_causal_claim",
        "question": "Does the claim state that one thing causes another without evidence or a source?",
        "guidance": "'met' only if the answer states a specific cause -> effect as its own fact, and the link is "
                    "not common knowledge, not explained in the previous two sentences, not hedged, and not "
                    "attributed to someone. Correlation presented as cause is the main problem: 'Pilates and "
                    "walking positively impact quality of life, depression and anxiety' is 'met' (a specific "
                    "causal claim stated as fact). "
                    # Nov 10 review: the agent missed "The rise is largely explained by ..." as not causal
                    "An explanation of why something happened is a cause -> effect too: 'is (largely) "
                    "explained by', 'is due to', 'is driven by' ('The drop in crime is largely explained by "
                    "more police on the streets' is 'met' unless a rule below applies). Decide 'not_met' for: "
                    "(1) reported viewpoints attributed to someone ('Critics argue that higher labor costs lead "
                    "employers to hire fewer workers', 'Some economists argue ...', 'X says ...', 'Opponents "
                    "claimed ...'): they describe a debate, unless the answer itself endorses the claim; "
                    "(2) common-knowledge mechanisms a typical college student would accept without a source "
                    "('When housing prices fell, losses spread rapidly', 'EVs produce no exhaust while driving, "
                    "which improves local air quality', 'EVs are heavier, which can increase tire wear'); "
                    "(3) hedged wording: can, may, might, could, tends to, may contribute, and correlation stated "
                    "as correlation ('is associated with'); "
                    # Nov 10 review: a related named source two sentences back (the WHO) also covers the claim
                    "(4) a cause already explained, or backed by a related named source (an organisation, "
                    "study or dataset), in this sentence or the two previous sentences (use context_window); "
                    "(5) headings, questions and fragments ('Possible reasons for the 2020 increase', 'Why it "
                    # Nov 10 review: the agent called a full bullet-point sentence after a heading a fragment
                    "changes each year'). A full sentence in a bullet list is still a claim, even right after "
                    "a heading ('- Regular exercise lowers blood pressure.' is judged like any sentence); "
                    # Nov 10 review: "Because tuples are immutable ..." (how Python works) was flagged
                    "(6) how code, math or a technical system works by design ('Because Python strings are "
                    "immutable, changing one creates a new string'): this is common knowledge; "
                    # Nov 10 review: a sentence was flagged C6 because of its unsourced number
                    "(7) a number in the sentence is not a reason for 'met': judge only the cause -> effect "
                    "link ('The flood destroyed crops and displaced about 40,000 people': the number is C1's "
                    "job, the flood destroying crops is common knowledge). A sentence with no cause-effect "
                    "link at all is 'not_met' too. When in doubt, decide 'not_met'. "
                    # Nov 10 review: say so when common knowledge decided it, so a reader knows to look it up
                    "When common knowledge is your reason for 'not_met', start the reasoning with 'Common "
                    "knowledge:' and say what a quick search would confirm.",
        "phase": 1, "depends_on": {},
        "tools": ["find_attribution", "context_window"],
        "severity": {"strong": 1, "moderate": 1, "supporting": 0},
        "applies": lambda c: "causal" in c["signals"],
        "open": True,
        "prefilter": c6_prefilter,
    },
    "C2": {
        "name": "statistic_contradicted",
        "question": "Does a reliable source give a different figure?",
        "guidance": (
            "1. Pin the number down.\n"
            "   - Extract: value, measure, place, period, and hedge ('approx' for about/roughly/around/nearly, "
            "'at_least' for over/more than/at least, 'at_most' for under/less than/fewer than, else 'none').\n"
            "   - Context fallback: if place or period is missing from the sentence, use the two previous "
            "sentences and the user's question (if they say 'the US in 2020', inherit place='United States', "
            "period='2020'). 'Federal' means 'United States'. Present tense with no time stated means the latest "
            "full year.\n"
            "   - A plain 'unemployment rate' means U-3, not U-6.\n"
            "   - If measure, place or period still can't be determined, decide 'undetermined' and say "
            "'missing_context' in your reasoning.\n\n"
            "2. Call lookup_statistic(measure, place, period).\n"
            "   - If an annual figure is asked for and only monthly records exist, and all 12 months of that "
            "year are there, use their mean as the annual figure.\n"
            "   - If no matching record is found, decide 'undetermined' and say 'no_record' in your reasoning. "
            "Never compare with a different measure, place or period.\n\n"
            "3. Call compare_numbers(claim_value, official_value=value_text, hedge) for EVERY record.\n"
            "   - 'not_met': every official figure matches the claim within the hedge tolerance.\n"
            "   - 'met': official figures exist and ALL of them contradict the claim.\n"
            "   - 'undetermined': official figures disagree with each other ('source_conflict'; cite all) "
            "or none is comparable.\n\n"
            "4. Submit claim_fields and one evidence item per record (quote = value_text, source = record_id)."
        ),
        "phase": 2,
        "depends_on": {"C1": ["met", "not_met", "undetermined"]},
        "tools": ["lookup_statistic", "compare_numbers"],
        "severity": {"strong": 3, "moderate": 3, "supporting": 2},
        "applies": lambda c: any(parse_value(v) is not None for v in c["checkable_values"]),
        "open": False,
    },
}
PHASES = sorted({c["phase"] for c in CRITERIA.values()})


def applicable(claim: dict, open_criteria: bool = False) -> list[str]:
    """Criteria to run for a claim. open_criteria=True (model modes) adds the open criteria
    (C3-C6 always, C1 for numberless quantitative claims), so the agents also judge sentences
    the rules didn't trigger on."""
    def is_open(c):  # "open" is True/False, or a test for which claims it opens up to
        return c["open"](claim) if callable(c["open"]) else c["open"]
    return [cid for cid, c in CRITERIA.items() if c["applies"](claim) or (open_criteria and is_open(c))]