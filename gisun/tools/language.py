"""Word-list lookup and context cues (negation / quotation / mention) for a flagged term."""

import json
import re
from functools import lru_cache

from gisun import config

NEGATORS = re.compile(r"\b(?:not|no|never|isn't|wasn't|aren't|weren't|denied|deny|without|nor)\b", re.I)
MENTION = re.compile(r"\b(?:called|termed|labeled|labelled|described (?:it |them |this )?as|the (?:term|word|phrase)|"
                     r"so-called|referred to as|dubbed)\b", re.I)


@lru_cache(maxsize=1)
def wordlist() -> dict[str, list[str]]:
    with open(config.WORDLIST_PATH, encoding="utf-8") as f:
        return json.load(f)


def wordlist_lookup(term: str) -> dict:
    t = term.lower().strip()
    cats = [c for c, phrases in wordlist().items() if t in (p.lower() for p in phrases)]
    return {"term": term, "in_wordlist": bool(cats), "categories": cats}


def context_cues(sentence: str, term: str) -> dict:
    """Deterministic hints a judge can check: is the term negated, quoted, or only mentioned?"""
    idx = sentence.lower().find(term.lower())
    if idx < 0:
        return {"error": f"{term!r} is not in the sentence"}
    before = sentence[:idx]
    window = " ".join(before.split()[-4:])
    quoted = before.count('"') % 2 == 1 or before.count("\u201c") > before.count("\u201d")
    return {"term": term,
            "negated": bool(NEGATORS.search(window)),
            "quoted": quoted,
            "mentioned_not_used": bool(MENTION.search(" ".join(before.split()[-6:]))),
            "words_before": window}
