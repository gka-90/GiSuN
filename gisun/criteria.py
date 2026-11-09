"""
Criterion registry -- the GiSuN counterpart of the ACMG criteria table.

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
    rule(claim, ctx)    deterministic decision: used in rules_only mode and as the
                        fallback when the agent fails (like the variant pipeline's
                        error path, but with an answer instead of a gap)
    prefilter(claim)    optional: a reason string when the sentence can be decided "not_met"
                        without a model (a heading, a reported viewpoint); the pipeline then
                        uses the rule and never sends the claim to the task agent

The guidance follows docs/labeling_rules.md (same wording and examples), so the agents and
the human labelers apply the same rules.
"""

import re

from gisun.detectors.claims import CUES
from gisun.tools.language import context_cues, heading_or_fragment, reported_viewpoint
from gisun.tools.numbers import compare_numbers, hedge_of, numbers_in, parse_value
from gisun.tools.retrieval import (implied_period, implied_places, lookup_statistic, matching_series,
                                   periods_in, places_in)

DECISIONS = ("met", "not_met", "undetermined")
STRENGTHS = ("strong", "moderate", "supporting")
LOADED_CATS = {"loaded_political_terms", "emotionally_charged_terms",
               "loaded_framing_of_events", "loaded_identity_or_group_terms"}


def _decision(decision, strength, reasoning, evidence=None):
    return {"decision": decision, "strength": strength, "reasoning": reasoning, "evidence": evidence or []}


def _terms(claim, cats):
    return [b for b in claim["bias_terms"] if b["category"] in cats]


# docs/labeling_rules.md, "Rules for every criterion", for the criteria that judge wording (C3-C5)
SHARED_RULES = ("Rules for every criterion: judge only this criterion (a different problem is 'not_met' here); "
                "headings, questions and fragments are never 'met'; reported viewpoints ('Critics argue ...', "
                "'Supporters say ...', 'Opponents claimed ...') describe a debate and are not the answer's own "
                "claim unless the answer itself endorses it; common knowledge a typical college student would "
                "accept without a source counts as support; a source or an explanation in the two previous "
                "sentences covers this sentence. When in doubt, decide 'not_met'.")


def _not_own_claim(claim) -> str | None:
    """Rules 2 and 3 for the wording criteria: a heading or a reported viewpoint is never 'met'."""
    if why := heading_or_fragment(claim["sentence"]):
        return f"The sentence is {why}, not a claim."
    if who := reported_viewpoint(claim["sentence"]):
        return f"The sentence reports a viewpoint ({who!r}), not the answer's own claim."
    return None


def _used_terms(claim, cats):
    """Terms from these categories that are not negated / quoted / merely mentioned."""
    used = []
    for b in _terms(claim, cats):
        cues = context_cues(claim["sentence"], b["term"])
        if not (cues.get("negated") or cues.get("quoted") or cues.get("mentioned_not_used")):
            used.append(b["term"])
    return used


# ---- deterministic rules ---------------------------------------------------------------

def rule_c1(claim, ctx):
    src = claim["attribution"]["source_text"] or claim["attribution_nearby"]["source_text"]
    # The numbers, or for a claim with no number the record/trend/comparison words ("the highest ever")
    quoted = claim["stat_values"] or [m.group(0) for m in CUES["quantitative"].finditer(claim["sentence"])] \
        or numbers_in(claim["sentence"])
    values = ", ".join(quoted)
    if src:
        return _decision("not_met", "moderate", f"{values} is attributed to {src}.",
                         [{"quote": src, "source": "response"}])
    return _decision("met", "strong", f"{values} is given with no named source in this or the previous sentences.",
                     [{"quote": v, "source": "response"} for v in quoted])


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


def _measure_in(text: str) -> str | None:
    """The longest catalog alias named in the text."""
    return max((a for e in matching_series(text) for a in e["aliases"]
                if re.search(r"(?<![a-z])" + re.escape(a) + r"s?(?![a-z])", text.lower())), key=len, default=None)


def c2_fields_from_text(claim, question: str = "") -> dict | None:
    """The rules' version of step 1: measure, place, period and hedge. Each comes from the claim
    first, then the two sentences before it, then the user's question. None if any can't be pinned down."""
    texts = [claim["sentence"], " ".join(claim["context_before"]), question or ""]
    measure = next((m for t in texts if (m := _measure_in(t))), None)
    places = next((p for t in texts if (p := places_in(t))), []) or next(
        (p for t in texts if (p := implied_places(t))), [])
    periods = next((p for t in texts if (p := periods_in(t))), [])
    # "(2009): ... in October 2009" gives 2009 and 2009-10: the month is the same period, more precisely
    periods = [p for p in periods if not any(q != p and q.startswith(p + "-") for q in periods)]
    if not periods and (latest := implied_period(claim["sentence"])):
        periods = [latest]  # present tense, no time stated: the latest full year
    if not measure or len(places) != 1 or len(periods) != 1 or not claim["checkable_values"]:
        return None
    value = claim["checkable_values"][0]
    return {"value": value, "measure": measure, "place": places[0]["name"], "period": periods[0],
            "hedge": hedge_of(claim["sentence"], value)}


def rule_c2(claim, ctx):
    """The C2 steps without a model: pin the claim down, look up the official figure, compare."""
    fields = c2_fields_from_text(claim, ctx.question)
    if not fields:
        return _decision("undetermined", "supporting",
                         "The rules can't tell the measure, place and time of this number from the text.")
    try:
        found = lookup_statistic(fields["measure"], fields["place"], fields["period"])
    except Exception as e:
        return {**_decision("undetermined", "supporting", f"The statistics lookup failed ({e})."), "claim_fields": fields}
    records = found["records"]
    ctx.record_official(records)
    outcome, cmps = c2_outcome(fields["value"], fields["hedge"], records)
    if not records:
        why = found.get("note") or "No official figure was found."
    elif outcome == "undetermined" and len({c.get("match") for c in cmps if c.get("comparable")}) > 1:
        why = "Official sources disagree: " + "; ".join(f"{r['source']} {r['value_text']}" for r in records) + "."
    else:
        r = records[0]
        why = (f"{fields['value']} ({fields['hedge']}) vs {r['source']} {r['series_id']}: {r['value_text']} for "
               f"{r['period']}; {cmps[0].get('rule', cmps[0].get('reason'))}.")
    return {**_decision(outcome, "supporting", why, [{"quote": r["value_text"], "source": r["record_id"]}
                                                     for r in records]), "claim_fields": fields}


def rule_terms(cats, label):
    def rule(claim, ctx):
        terms = _terms(claim, cats)
        if terms and (why := _not_own_claim(claim)):
            return _decision("not_met", "supporting", why)
        used = _used_terms(claim, cats)
        if used:
            return _decision("met", "moderate", f"Uses {', '.join(repr(t) for t in used)} ({label.lower()}), "
                                                f"not negated, quoted or only mentioned.",
                             [{"quote": t, "source": "response"} for t in used])
        if not terms:  # an open-criteria sentence with no word-list hit
            return _decision("not_met", "supporting", "No word-list term for this check appears in the sentence.")
        return _decision("not_met", "supporting",
                         f"{', '.join(b['term'] for b in terms)} appears negated, quoted or only mentioned.")
    return rule


def rule_c5(claim, ctx):
    vague = [b["term"] for b in _terms(claim, {"vague_or_unsourced_attribution"})]
    # "critics argue", "some people say": naming who holds an opinion, not evidence for a fact
    opinion = [t for t in vague if reported_viewpoint(t)]
    if vague and (why := heading_or_fragment(claim["sentence"])):
        return _decision("not_met", "supporting", f"The sentence is {why}, not a claim.")
    if vague and len(opinion) == len(vague):
        return _decision("not_met", "supporting", f"{', '.join(opinion)} names who holds an opinion in a debate; "
                                                  "it is not used as evidence for a fact.")
    if vague and not claim["attribution"]["names_specific_source"]:
        return _decision("met", "moderate", f"Credits unnamed sources: {', '.join(vague)}.",
                         [{"quote": t, "source": "response"} for t in vague])
    if vague:
        return _decision("not_met", "supporting", f"{', '.join(vague)} appears, but a specific source is also named.")
    return _decision("not_met", "supporting", "No vague attribution ('experts say', 'studies show') in the sentence.")


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


def rule_c6(claim, ctx):
    if why := c6_prefilter(claim):
        return _decision("not_met", "moderate", why)
    # Open criteria send every sentence here; without cause-effect wording there is nothing to check
    if "causal" not in claim["signals"]:
        return _decision("not_met", "supporting", "The sentence has no cause-effect wording.")
    if claim["attribution"]["names_specific_source"] or claim["attribution_nearby"]["names_specific_source"]:
        return _decision("not_met", "supporting", "The causal claim is attributed to a source.")
    return _decision("met", "supporting", "States a cause-effect link without evidence or a source.")


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
        "rule": rule_c1,
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
        "rule": rule_terms(LOADED_CATS, "Loaded wording"),
    },
    "C4": {
        "name": "overgeneralization",
        "question": "Does the claim make an absolute or sweeping statement (always, never, everyone ...) that the evidence can't support?",
        "guidance": "'met' only if the sentence makes an unqualified universal claim about people, groups or "
                    "outcomes ('always', 'never', 'everyone', or a claim about a whole group) that has obvious "
                    "exceptions ('Everyone concentrates better after a good breakfast'): a tendency turned into a "
                    "rule. 'not_met' for: literally true absolutes ('water always boils at a lower temperature at "
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
        "rule": rule_terms({"absolutist_or_overgeneralizing_terms"}, "Sweeping wording"),
    },
    "C5": {
        "name": "vague_attribution",
        "question": "Does the claim credit unnamed authorities (experts say, studies show) instead of a specific source?",
        "guidance": "'met' only if a factual claim rests on an unnamed authority ('studies show', 'experts say', "
                    "'research suggests', 'it is believed', 'is widely considered') and no specific source is in "
                    "the sentence or the two before it ('Studies show it lowers the risk of hospitalization and "
                    "death' is a fact resting on 'studies'). Test question: is the vague group used as evidence "
                    "for a fact, or does it only name who believes something? 'not_met' for: naming who holds an "
                    "opinion in a debate ('Critics argue these costs fall hardest on working-class people', "
                    "'supporters say'); a sentence that credits no one at all (a missing source is C1's job); a "
                    "specific source named in the sentence, or in the two before it if it covers this claim ('The CDC recommends an annual "
                    "flu vaccine'). Use find_attribution with where='sentence' and where='previous'. " + SHARED_RULES,
        "phase": 1, "depends_on": {},
        "tools": ["find_attribution", "context_window"],
        "severity": {"strong": 2, "moderate": 1, "supporting": 1},
        "applies": lambda c: bool(_terms(c, {"vague_or_unsourced_attribution"})) or "attribution" in c["signals"],
        "open": True,
        "rule": rule_c5,
    },
    "C6": {
        "name": "unsupported_causal_claim",
        "question": "Does the claim state that one thing causes another without evidence or a source?",
        "guidance": "'met' only if the answer states a specific cause -> effect as its own fact, and the link is "
                    "not common knowledge, not explained in the previous two sentences, not hedged, and not "
                    "attributed to someone. Correlation presented as cause is the main problem: 'Pilates and "
                    "walking positively impact quality of life, depression and anxiety' is 'met' (a specific "
                    "causal claim stated as fact). Decide 'not_met' for: "
                    "(1) reported viewpoints attributed to someone ('Critics argue that higher labor costs lead "
                    "employers to hire fewer workers', 'Some economists argue ...', 'X says ...', 'Opponents "
                    "claimed ...'): they describe a debate, unless the answer itself endorses the claim; "
                    "(2) common-knowledge mechanisms a typical college student would accept without a source "
                    "('When housing prices fell, losses spread rapidly', 'EVs produce no exhaust while driving, "
                    "which improves local air quality', 'EVs are heavier, which can increase tire wear'); "
                    "(3) hedged wording: can, may, might, could, tends to, may contribute, and correlation stated "
                    "as correlation ('is associated with'); "
                    "(4) a cause already explained in the two previous sentences (use context_window); "
                    "(5) headings, questions and fragments ('Possible reasons for the 2020 increase', 'Why it "
                    "changes each year'). A sentence with no cause-effect link at all is 'not_met' too. When in "
                    "doubt, decide 'not_met'.",
        "phase": 1, "depends_on": {},
        "tools": ["find_attribution", "context_window"],
        "severity": {"strong": 1, "moderate": 1, "supporting": 0},
        "applies": lambda c: "causal" in c["signals"],
        "open": True,
        "rule": rule_c6,
        "prefilter": c6_prefilter,
    },
    "C2": {
        "name": "statistic_contradicted",
        "question": "Does a reliable source give a different figure?",
        "guidance": "1. Pin the number down. From the claim (or the two sentences before it, or the user's "
                    "question) take: value (the "
                    "number as written, e.g. '14.7%'), measure (e.g. 'unemployment rate'), place (e.g. 'United "
                    "States'), period (a year '2020' or a month '2020-04') and hedge: 'approx' for about / "
                    "roughly / around / nearly, 'at_least' for over / more than / at least, 'at_most' for under / "
                    "less than / fewer than, else 'none'. If the measure, place or time is not stated in any of these, stop "
                    "and decide 'undetermined'. Plain 'unemployment rate' means U-3, not U-6. 'Federal' (e.g. federal minimum wage) means the United States. A present-tense claim with no time ('the minimum wage is $9.50') is about now: use the latest full year as the period. "
                    "2. Call lookup_statistic(measure, place, period); it picks the official API and only returns "
                    "figures for exactly that measure, place, period and unit. A monthly figure does not answer an "
                    "annual claim, and an annual average does not answer a monthly one. If it returns no record, "
                    "decide 'undetermined': never compare with a close-enough figure. "
                    "3. Call compare_numbers(claim_value, official_value=value_text, hedge) for EVERY record. "
                    "'not_met' = every official figure matches, 'met' = none does, 'undetermined' = official "
                    "sources disagree with each other (cite all of them) or nothing comparable was found. "
                    "4. Submit claim_fields, and one evidence item per record: quote = its value_text, source = "
                    "its record_id.",
        "phase": 2, "depends_on": {"C1": ["met", "not_met", "undetermined"]},
        "tools": ["lookup_statistic", "compare_numbers"],
        "severity": {"strong": 3, "moderate": 3, "supporting": 2},
        # only values compare_numbers can read ("most Americans" needs a source, but can't be checked)
        "applies": lambda c: any(parse_value(v) is not None for v in c["checkable_values"]),
        "open": False,
        "rule": rule_c2,
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
