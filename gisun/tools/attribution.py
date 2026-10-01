"""Does a sentence (or the sentences right before it) name a specific source?
Moved from agent/analyzer.py so every agent and the rules share one definition."""

import re

SOURCE_NAME = r"(?P<name>(?i:the\s+)?(?:(?:19|20)\d{2}\s+)?[A-Z][\w&.'-]*(?:\s+(?:of\s+|for\s+|and\s+|&\s+)?[A-Z][\w&.'-]*)*)"
SOURCE_PATTERNS = [re.compile(p) for p in (
    r"\b(?i:according to|reported by|published (?:by|in)|data from|figures from|estimates from|"
    r"survey by|study by)\s+" + SOURCE_NAME,
    SOURCE_NAME + r"\s+(?:reports?|reported|found|finds|estimates?|estimated|shows?|showed|says|said|"
    r"states?|stated)\b",
    r"\(\s*" + SOURCE_NAME + r",?\s+(?:19|20)\d{2}\s*\)",
    r"(?i:sources?)\s*:\s*" + SOURCE_NAME,
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
                if not words or words[0].lower() in GENERIC_SOURCES:
                    continue
            return {"names_specific_source": True, "source_text": match.group(0)}
    return {"names_specific_source": False, "source_text": None}
