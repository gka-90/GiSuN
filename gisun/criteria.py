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
    rule(claim, ctx)    deterministic decision: used in rules_only mode and as the
                        fallback when the agent fails (like the variant pipeline's
                        error path, but with an answer instead of a gap)
"""

from gisun.preprocess import STAT_TYPES
from gisun.tools.language import context_cues
from gisun.tools.numbers import compare_numbers, NUMBER
from gisun.tools.retrieval import read_source, search

DECISIONS = ("met", "not_met", "undetermined")
STRENGTHS = ("strong", "moderate", "supporting")
LOADED_CATS = {"loaded_political_terms", "emotionally_charged_terms",
               "loaded_framing_of_events", "loaded_identity_or_group_terms"}


def _decision(decision, strength, reasoning, evidence=None):
    return {"decision": decision, "strength": strength, "reasoning": reasoning, "evidence": evidence or []}


def _terms(claim, cats):
    return [b for b in claim["bias_terms"] if b["category"] in cats]


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
    values = ", ".join(claim["stat_values"])
    if src:
        return _decision("not_met", "moderate", f"{values} is attributed to {src}.",
                         [{"quote": src, "source": "response"}])
    return _decision("met", "strong", f"{values} is given with no named source in this or the previous sentences.",
                     [{"quote": v, "source": "response"} for v in claim["stat_values"]])


def rule_c2(claim, ctx):
    hits = search(claim["sentence"], k=3)
    for hit in hits:
        doc = read_source(hit["source_id"])
        ctx.record_read(hit["source_id"], doc["text"])
        for value in claim["stat_values"]:
            for m in NUMBER.finditer(doc["text"]):
                cmp = compare_numbers(value, m.group(0))
                if cmp.get("comparable") and cmp["match"]:
                    return _decision("not_met", "supporting", f"{value} matches {m.group(0)} in {hit['title']}.",
                                     [{"quote": m.group(0), "source": hit["source_id"]}])
    return _decision("undetermined", "supporting", "Rules could not match the number to a retrieved source.")


def rule_terms(cats, label):
    def rule(claim, ctx):
        terms = _terms(claim, cats)
        used = _used_terms(claim, cats)
        if used:
            return _decision("met", "moderate", f"{label}: {', '.join(used)}.",
                             [{"quote": t, "source": "response"} for t in used])
        return _decision("not_met", "supporting",
                         f"{', '.join(b['term'] for b in terms)} appears negated, quoted or only mentioned.")
    return rule


def rule_c5(claim, ctx):
    vague = [b["term"] for b in _terms(claim, {"vague_or_unsourced_attribution"})]
    if vague and not claim["attribution"]["names_specific_source"]:
        return _decision("met", "moderate", f"Credits unnamed sources: {', '.join(vague)}.",
                         [{"quote": t, "source": "response"} for t in vague])
    return _decision("not_met", "supporting", "A specific source is named.")


def rule_c6(claim, ctx):
    if claim["attribution"]["names_specific_source"] or claim["attribution_nearby"]["names_specific_source"]:
        return _decision("not_met", "supporting", "The causal claim is attributed to a source.")
    return _decision("met", "supporting", "States a cause-effect link without evidence or a source.")


# ---- registry ----------------------------------------------------------------------------

CRITERIA = {
    "C1": {
        "name": "unsourced_statistic",
        "question": "Does the claim give a statistic without naming a specific source (in this or the previous two sentences)?",
        "guidance": "A specific source is a named organisation, publication, dataset or link. 'Experts', 'studies' or "
                    "'reports' are NOT specific. Use find_attribution and context_window; a source in the previous "
                    "sentence counts if it clearly covers this number.",
        "phase": 1, "depends_on": {},
        "tools": ["find_attribution", "context_window"],
        "severity": {"strong": 2, "moderate": 2, "supporting": 1},
        "applies": lambda c: bool(c["stat_values"]),
        "rule": rule_c1,
    },
    "C3": {
        "name": "loaded_language",
        "question": "Does the claim use slanted or emotionally loaded wording where a neutral word would do?",
        "guidance": "Check each flagged term with context_cues. A term that is negated ('not a crisis'), quoted, or "
                    "only mentioned ('the term \"illegal alien\"') is NOT loaded use. You may also report loaded "
                    "wording the word list missed; quote it exactly.",
        "phase": 1, "depends_on": {},
        "tools": ["context_cues", "wordlist_lookup"],
        "severity": {"strong": 2, "moderate": 1, "supporting": 1},
        "applies": lambda c: bool(_terms(c, LOADED_CATS)),
        "rule": rule_terms(LOADED_CATS, "Loaded wording"),
    },
    "C4": {
        "name": "overgeneralization",
        "question": "Does the claim make an absolute or sweeping statement (always, never, everyone ...) that the evidence can't support?",
        "guidance": "Absolute words are fine when literally true ('water always boils at a lower temperature at "
                    "altitude' is a physical law). Flag them when they turn a tendency into a rule.",
        "phase": 1, "depends_on": {},
        "tools": ["context_cues"],
        "severity": {"strong": 2, "moderate": 1, "supporting": 1},
        "applies": lambda c: bool(_terms(c, {"absolutist_or_overgeneralizing_terms"})),
        "rule": rule_terms({"absolutist_or_overgeneralizing_terms"}, "Sweeping wording"),
    },
    "C5": {
        "name": "vague_attribution",
        "question": "Does the claim credit unnamed authorities (experts say, studies show) instead of a specific source?",
        "guidance": "Use find_attribution. If a specific source is also named, this is not vague attribution.",
        "phase": 1, "depends_on": {},
        "tools": ["find_attribution", "context_window"],
        "severity": {"strong": 2, "moderate": 1, "supporting": 1},
        "applies": lambda c: bool(_terms(c, {"vague_or_unsourced_attribution"})) or "attribution" in c["signals"],
        "rule": rule_c5,
    },
    "C6": {
        "name": "unsupported_causal_claim",
        "question": "Does the claim state that one thing causes another without evidence or a source?",
        "guidance": "Look for causal wording (causes, leads to, because, due to). Correlation presented as cause "
                    "is the main problem.",
        "phase": 1, "depends_on": {},
        "tools": ["find_attribution", "context_window"],
        "severity": {"strong": 1, "moderate": 1, "supporting": 0},
        "applies": lambda c: "causal" in c["signals"],
        "rule": rule_c6,
    },
    "C2": {
        "name": "statistic_contradicted",
        "question": "Does a reliable source contradict the number in the claim?",
        "guidance": "Search for the statistic, open the most reliable result (government statistics office, "
                    "peer-reviewed or primary source first), find the matching figure, and ALWAYS use "
                    "compare_numbers before deciding. 'met' = contradicted, 'not_met' = a reliable source "
                    "matches, 'undetermined' = no reliable figure found after reasonable searching. Watch for "
                    "different definitions (annual average vs monthly peak, percent vs percentage points).",
        "phase": 2, "depends_on": {"C1": ["met", "not_met", "undetermined"]},
        "tools": ["search", "read_source", "compare_numbers"],
        "severity": {"strong": 3, "moderate": 3, "supporting": 2},
        "applies": lambda c: bool(c["stat_values"]),
        "rule": rule_c2,
    },
}
PHASES = sorted({c["phase"] for c in CRITERIA.values()})


def applicable(claim: dict) -> list[str]:
    return [cid for cid, c in CRITERIA.items() if c["applies"](claim)]
