"""
extract_claims() -- Tier 1 claim extraction (no LLM).

TODO: for now this only takes the outputs of detect_numeric_claims() and
detect_bias_framing() as input. I will add the raw file/page text as input
after figuring out how to decide on what is a claim.

Groups the Tier 1 flags by the sentence they came from, drops sentences
that aren't factual claims (questions, chatbot filler, advice), scores the
rest, and merges near-duplicate claims. The output is the list of claims
worth sending to Tier 2 (classify_claim_evidence).
"""

import re
from difflib import SequenceMatcher

MIN_WORDS = 5
SIMILARITY_THRESHOLD = 0.85

FILLER_OPENERS = (
    "sure", "certainly", "of course", "great question", "let me know",
    "i hope", "feel free", "happy to help", "i'm happy to", "good luck",
)
IMPERATIVE_OPENERS = (
    "try", "use", "make", "consider", "remember", "avoid", "check",
    "ensure", "click", "run", "note", "keep", "look", "start", "ask",
)

# Each cue that matches adds 1 to a sentence's score
CUES = {
    "attribution": re.compile(
        r"\b(according to|studies (show|suggest|found)|research (shows|suggests|found)|"
        r"scientists|experts|reported|survey|data (shows|suggests))\b", re.IGNORECASE),
    "superlative": re.compile(
        r"\b(largest|smallest|biggest|highest|lowest|most|least|first|only|best|worst|"
        r"more than|less than|fewer than)\b", re.IGNORECASE),
    # A quantitative claim with no number (statistic-formats reference, "Comparisons and claims
    # without explicit numbers"): records, trends and comparisons that still need a source (C1)
    "quantitative": re.compile(
        r"\b(?:(?:the\s)?(?:highest|lowest|largest|biggest|smallest|fastest|slowest|most|least|best|worst)"
        r"(?:\s\w+)?\s(?:ever|on record|since|in\s(?:a|the|over\s\w+)\s(?:decade|century|generation|history|years?))"
        r"|record[- ](?:highs?|lows?|levels?|breaking|numbers?)|all[- ]time\s(?:highs?|lows?)"
        r"|fastest[- ]growing|outpac\w+|outperform\w+|more than any other|less than any other"
        r"|skyrocket\w*|plummet\w*|surg(?:ed|ing|es)|soar(?:ed|ing|s)|slump(?:ed|ing|s)?|plung(?:ed|ing|es)"
        r"|a total of)\b", re.IGNORECASE),  # not "in all" / "combined": too common outside statistics
    "causal": re.compile(
        r"\b(causes?|caused|leads? to|led to|results? in|because|due to)\b", re.IGNORECASE),
    "named_entity": re.compile(r"(?<=\s)[A-Z][a-zA-Z]+"),
}
HEDGE = re.compile(
    r"\b(?:[Ii] think|[Ii] believe|[Ii]n my opinion|may|might|could|possibly|perhaps)\b")


def _is_candidate(sentence: str) -> bool:
    lowered = sentence.lower()
    if sentence.endswith(("?", ":")):
        return False
    if len(sentence.split()) < MIN_WORDS:
        return False
    if lowered.startswith(FILLER_OPENERS):
        return False
    if lowered.split()[0].strip(",") in IMPERATIVE_OPENERS:
        return False
    return True


def _normalize(sentence: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", sentence.lower())


def _merge_similar(claims: list[dict]) -> list[dict]:
    """Similarity pass: fold near-duplicate claims into the first occurrence
    so the same claim isn't sent to the LLM twice."""
    kept = []
    for claim in claims:
        match = next(
            (k for k in kept
             if SequenceMatcher(None, _normalize(k["sentence"]), _normalize(claim["sentence"])).ratio()
             >= SIMILARITY_THRESHOLD),
            None,
        )
        if match is None:
            kept.append(claim)
            continue
        match["flags"] += claim["flags"]
        match["detector_hit"] = match["detector_hit"] or claim["detector_hit"]  # flagged if either was
        match["signals"] = sorted(set(match["signals"]) | set(claim["signals"]))
        match["score"] = max(match["score"], claim["score"])
        match["duplicates"].append(claim["sentence"])
    return kept


def extract_claims(numeric_flags: list[dict], bias_flags: list[dict],
                   min_score: int = 1, sentences: list[str] | None = None) -> list[dict]:
    """
    Turn the flags from detect_numeric_claims() and detect_bias_framing()
    into a list of check-worthy claims, one per flagged sentence.

    If `sentences` (all sentences of the text, in reading order) is given,
    factual sentences with no flag become claims too, with "flags": [] and
    "detector_hit": False. That lets the agents look at wording the regexes
    and word list miss ("Every worker was affected"); rules still drop
    questions, filler and advice.

    Returns claims in reading order:
        {
            "claim_id": position in the returned list,
            "sentence": the claim text,
            "type": "claim",
            "score": how check-worthy it looks (higher = check first),
            "signals": which cues fired, e.g. ["numeric", "attribution"],
            "flags": the Tier 1 flags from this sentence (they keep their
                     own start_index/end_index for highlighting),
            "duplicates": near-duplicate sentences merged into this one,
        }
    """
    # Group flags by the sentence they came from, in reading order
    # Seed with every sentence (reading order) so unflagged ones can become claims too
    by_sentence = {s: [] for s in sentences or []}
    for flag in sorted(numeric_flags + bias_flags, key=lambda f: f["start_index"]):
        by_sentence.setdefault(flag["sentence"], []).append(flag)

    claims = []
    for sentence, flags in by_sentence.items():
        if not _is_candidate(sentence):
            continue

        signals, score = [], 0
        if any(f["type"] != "bias_framing" for f in flags):
            signals.append("numeric")
            score += 2
        if any(f["type"] == "bias_framing" for f in flags):
            signals.append("bias_framing")
            score += 2
        for name, pattern in CUES.items():
            if pattern.search(sentence):
                signals.append(name)
                score += 1
        if HEDGE.search(sentence):
            signals.append("hedged")
            score -= 1

        # Unflagged sentences are kept whatever their score: the agents decide about them
        if score >= min_score or (sentences is not None and not flags):
            claims.append({
                "sentence": sentence,
                "type": "claim",
                "score": score,
                "signals": signals,
                "flags": flags,
                "detector_hit": bool(flags),
                "duplicates": [],
            })

    claims = _merge_similar(claims)
    for i, claim in enumerate(claims):
        claim["claim_id"] = i
    return claims


if __name__ == "__main__":
    from detect_numeric_claims import detect_numeric_claims, save_results_to_json
    from detect_bias_framing import detect_bias_framing

    test_cases = {
        "chatbot_response": (
            "Great question! Unemployment reportedly hit 8.5% in 2020, according to several reports. "
            "Experts describe the housing market as a crisis. "
            "The Federal Reserve raised interest rates because inflation was high. "
            "Would you like to know what happened in 2021? "
            "Unemployment reportedly reached 8.5% in 2020, according to reports."
        ),
        "hedged_opinion": "I think this might possibly become a crisis for some people.",
        "no_flags": "Photosynthesis is the process by which plants convert sunlight into energy.",
    }

    all_results = {}
    for label, text in test_cases.items():
        numeric = detect_numeric_claims(text)
        bias = detect_bias_framing(text, wordlist_path="bias_wordlist.json")
        all_results[label] = {
            "input_text": text,
            "claims": extract_claims(numeric, bias),
        }

    save_results_to_json(all_results, "extracted_claims.json")
