"""
Step 0 (deterministic, like VEP annotation in the variant pipeline):
run the Tier 1 detectors, group flags into claims, and attach the context
every agent needs (neighbouring sentences, attribution, flag details).
"""

import threading
from dataclasses import dataclass, field

from detect_bias_framing import detect_bias_framing
from detect_numeric_claims import detect_numeric_claims
from extract_claims import extract_claims
from sentences import _boundaries
from gisun import config
from gisun.tools.attribution import find_attribution

# Every numeric flag that needs a source (C1). "quantity" ("most Americans") has no number but still
# needs one; scores, research statistics and rankings come from the statistic-formats reference.
STAT_TYPES = {"percentage", "percentage_points", "dollar_amount", "currency_amount", "count", "ratio",
              "quantity", "score", "statistic", "ranking"}
# The ones C2 can look up and compare in a reference source (not "top 10" or "p < 0.05")
CHECKABLE_TYPES = {"percentage", "percentage_points", "dollar_amount", "currency_amount", "count", "ratio"}


def split_sentences(text: str) -> list[str]:
    cuts = [0] + _boundaries(text) + [len(text)]
    return [text[a:b].strip() for a, b in zip(cuts, cuts[1:]) if text[a:b].strip()]


def _drop_nested(flags):
    return [f for f in flags if not any(
        o is not f and o["start_index"] <= f["start_index"] and f["end_index"] <= o["end_index"]
        and o["end_index"] - o["start_index"] > f["end_index"] - f["start_index"] for o in flags)]


@dataclass
class RunContext:
    """Shared state for one run. Agents record what they read so judges can check grounding."""
    text: str
    question: str
    sentences: list[str]
    claims: list[dict]
    numeric_flags: list[dict]
    bias_flags: list[dict]
    read_sources: dict = field(default_factory=dict)  # source_id -> text the agent actually saw
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_read(self, source_id: str, text: str):
        with self._lock:
            self.read_sources[source_id] = text

    def claim(self, claim_id) -> dict:
        for c in self.claims:
            if c["claim_id"] == int(claim_id):
                return c
        raise ValueError(f"no claim {claim_id!r}")


def _context_before(sentences: list[str], sentence: str, n: int = 2) -> list[str]:
    for i, s in enumerate(sentences):
        if s == sentence or sentence in s:
            return sentences[max(0, i - n):i]
    return []


def preprocess(text: str, question: str = "", all_sentences: bool = False) -> RunContext:
    """all_sentences=True also turns factual sentences with no detector flag into
    claims (open problem #1), so the agents can judge wording the rules miss.
    rules_only keeps it off: the rules have nothing to say about those sentences."""
    numeric = detect_numeric_claims(text)
    bias = _drop_nested(detect_bias_framing(text, wordlist_path=config.WORDLIST_PATH))
    sentences = split_sentences(text)
    claims = extract_claims(numeric, bias, sentences=sentences if all_sentences else None)
    for c in claims:
        before = _context_before(sentences, c["sentence"])
        c["context_before"] = before
        c["attribution"] = find_attribution(c["sentence"])
        c["attribution_nearby"] = next((find_attribution(s) for s in reversed(before)
                                        if find_attribution(s)["names_specific_source"]),
                                       {"names_specific_source": False, "source_text": None})
        c["stat_values"] = [f["matched_value"] for f in c["flags"] if f["type"] in STAT_TYPES]
        c["checkable_values"] = [f["matched_value"] for f in c["flags"] if f["type"] in CHECKABLE_TYPES]  # for C2
        c["bias_terms"] = [{"term": f["matched_value"], "category": f["category"]}
                           for f in c["flags"] if f["type"] == "bias_framing"]
    return RunContext(text=text, question=question, sentences=sentences, claims=claims,
                      numeric_flags=numeric, bias_flags=bias)
