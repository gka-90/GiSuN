"""Word-list lookup and context cues (negation / quotation / mention) for a flagged term."""

import json
import re
from functools import lru_cache

from gisun import config

NEGATORS = re.compile(r"\b(?:not|no|never|isn't|wasn't|aren't|weren't|denied|deny|without|nor)\b", re.I)
MENTION = re.compile(r"\b(?:called|termed|labeled|labelled|described (?:it |them |this )?as|the (?:term|word|phrase)|"
                     r"so-called|referred to as|dubbed)\b", re.I)


# ---- cheap sentence-shape checks (labeling rules 2 and 3, docs/labeling_rules.md) ----------
LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
BOLD_LABEL = re.compile(r"^\*\*[^*]{1,80}?\*\*:?\s+(?=\S)")      # "**Weight:** EVs are heavier ..."
END_PUNCT = re.compile(r"[.!;)\"'”’]$")
FRAGMENT_MAX_WORDS = 8  # an unpunctuated line this short is a heading or a list fragment, not a claim


def heading_or_fragment(sentence: str) -> str | None:
    """Why the sentence is a heading, question or fragment (rule 2: never 'met'), or None.
    '**Why it changes each year**', 'Possible reasons for the 2020 increase', '## Causes', 'Why?'"""
    s = LIST_MARKER.sub("", sentence.strip())
    if s.startswith("#"):
        return "a markdown heading"
    whole_bold = bool(re.fullmatch(r"(\*\*|__)[^*_]+\1:?|\*[^*]+\*:?", s)) or (s.endswith("**") and s.count("**") == 1)
    core = re.sub(r"[*_`]", "", BOLD_LABEL.sub("", s)).strip()
    if core.endswith("?"):
        return "a question"
    if core.endswith(":"):
        return "a lead-in line ending in a colon"
    if not END_PUNCT.search(core):
        if whole_bold:
            return "a bold heading"
        if len(core.split()) < FRAGMENT_MAX_WORDS:
            return "a fragment with no sentence ending"
    return None


# Who holds a view in a debate (rule 3), and the verbs that report it. Not "studies" / "research" /
# "experts": "studies show X causes Y" rests a fact on an unnamed authority, which is still a claim.
VIEW_HOLDERS = (r"critics|opponents|supporters|proponents|advocates|defenders|detractors|skeptics|sceptics|"
                r"some|others|many people|commentators|observers|activists|lawmakers|politicians|he|she")
VIEW_VERBS = (r"argue[sd]?|say|says|said|claim(?:s|ed)?|contend(?:s|ed)?|believe[sd]?|maintain(?:s|ed)?|"
              r"insist(?:s|ed)?|warn(?:s|ed)?|assert(?:s|ed)?|counter(?:s|ed)?|worry|worries|worried|"
              r"fear(?:s|ed)?|point(?:s|ed)? out|wr(?:ote|ites)")
REPORTED = re.compile(rf"\b(?:{VIEW_HOLDERS})\b[^.;:]{{0,60}}?\b(?:{VIEW_VERBS})\b", re.I)
EVIDENCE_WORDS = re.compile(r"\b(?:stud(?:y|ies)|research|data|evidence|surveys?|reports?|analys[ie]s|trials?)\b", re.I)
# A named person or body ("Psychologist Jonathan Haidt, author of ..., argues"); only verbs of arguing
NAMED_VIEW = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][\w.'-]*)+\b[^.;]{0,80}?\b(?:argue[sd]?|says|said|claim(?:s|ed)|"
                        r"contend(?:s|ed)|maintain(?:s|ed)|insist(?:s|ed)|assert(?:s|ed)|warn(?:s|ed)|wr(?:ote|ites))\b")


def reported_viewpoint(sentence: str) -> str | None:
    """The words that make the sentence a reported viewpoint ('Critics argue ...', 'Some economists,
    like Larry Summers, argued ...', 'Jonathan Haidt argues ...'), or None (rule 3)."""
    text = re.sub(r"[*_`]", "", BOLD_LABEL.sub("", LIST_MARKER.sub("", sentence.strip())))
    for m in (*REPORTED.finditer(text), *NAMED_VIEW.finditer(text)):
        if not EVIDENCE_WORDS.search(m.group(0)):  # "some studies say" is evidence, not a viewpoint
            return m.group(0)
    return None


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
