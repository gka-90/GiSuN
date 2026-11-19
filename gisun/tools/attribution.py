"""Does a sentence (or the sentences right before it) name a specific source?
One definition shared by the preprocess step, the agents' tools and the rules
(it started in the removed agent/analyzer.py)."""

import re

SOURCE_NAME = r"(?P<name>(?i:the\s+)?(?:(?:19|20)\d{2}\s+)?[A-Z][\w&.'-]*(?:\s+(?:of\s+|for\s+|and\s+|&\s+)?[A-Z][\w&.'-]*)*)"
SOURCE_PATTERNS = [re.compile(p) for p in (
    r"\b(?i:according to|reported by|published (?:by|in)|data from|figures from|estimates from|"
    r"survey by|study by)\s+" + SOURCE_NAME,
    # "an assessment by the Mississippi Emergency Management Agency", "a 2021 analysis from Pew"
    r"\b(?i:assessments?|analys[ie]s|reports?|reviews?|estimates?|surveys?|stud(?:y|ies)|polls?|audits?|"
    r"evaluations?|investigations?|counts?|data|figures)\s+(?i:by|from)\s+" + SOURCE_NAME,
    SOURCE_NAME + r"\s+(?:reports?|reported|found|finds|estimates?|estimated|shows?|showed|says|said|"
    r"states?|stated|reveals?|revealed|announced|recorded|counted|concluded)\b",
    r"\(\s*" + SOURCE_NAME + r",?\s+(?:19|20)\d{2}\s*\)",
    r"(?i:sources?)\s*:\s*" + SOURCE_NAME,
    # "ranked the 11th greatest singer of all time by Rolling Stone", "detailed by geographer Roger Brunet"
    r"\b(?:ranked|rated|voted|named|listed|placed|classified|certified|detailed|compiled|documented)\b"
    r"[^.;]{0,80}?\bby\s+(?:[a-z]+\s+){0,2}" + SOURCE_NAME,
    # Wikipedia-style citation lines: "(Source: 1 2 Thornton)", "(Source: ↑ Hughes et al. 2003)"
    r"(?i:sources?)\s*:\s*(?:[\d\s↑^*]+)?" + SOURCE_NAME,
    r"(?P<ref>\[\d+\]|https?://\S+)",
)]
GENERIC_SOURCES = {
    "experts", "expert", "studies", "study", "research", "researchers", "scientists", "analysts",
    "reports", "report", "surveys", "survey", "data", "sources", "critics", "officials", "economists",
    "doctors", "many", "some", "most", "people", "it", "this", "that", "they", "he", "she", "we", "i",
    "the", "a", "an", "these", "those", "one", "another", "new", "several",
}


def find_attribution(sentence: str) -> dict:
    for pattern in SOURCE_PATTERNS:
        for match in pattern.finditer(sentence):
            name = match.groupdict().get("name")
            if name:
                words = re.sub(r"^the\s+", "", name, flags=re.IGNORECASE).split()
                # "New research shows" is vague, "the New York State Department of Labor" is not:
                # "new" only counts as vague when it stands alone
                proper_new = words[0].lower() == "new" and len(words) > 1 if words else False
                if not words or (words[0].lower() in GENERIC_SOURCES and not proper_new):
                    continue
            return {"names_specific_source": True, "source_text": match.group(0)}
    return {"names_specific_source": False, "source_text": None}


# Agentless attribution: a claim credited to nobody in particular ("is believed", "is regarded as",
# "allegedly"). On the gold sets it is in 106 of 119 C5 "met" rows and 1 of 110 "not_met" rows; the
# 32B Plan agent dropped C5 for it ("does not credit unnamed authorities"), so it always keeps C5.
AGENTLESS = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+(?:(?:widely|generally|often|commonly|largely|also|now|still|usually|"
    r"traditionally|sometimes|frequently|long)\s+)?(?:believed|considered|regarded|seen|thought|viewed|reported|"
    r"said|argued|claimed|alleged|rumou?red|deemed)\b"
    r"|\b(?:allegedly|reportedly|supposedly|purportedly|reputedly)\b"
    r"|\b(?:studies|research|evidence|data)\s+(?:shows?|suggests?|finds|found|has shown|have shown|indicates?)\b"
    r"|\bexperts\s+(?:say|agree|believe|warn)\b", re.IGNORECASE)


def agentless_attribution(sentence: str) -> str | None:
    """The words that credit an unnamed authority ('is believed', 'allegedly', 'studies show'), or None."""
    m = AGENTLESS.search(sentence)
    return m.group(0) if m else None
