"""
Sentence splitting shared by detect_numeric_claims() and detect_bias_framing().

A sentence ends at . ! ? followed by whitespace, except after:
- titles that are always followed by a name or number (Dr. Smith, No. 5, vs. ...)
- dotted acronyms (U.S., U.K., e.g., i.e., a.m.)
Treating "U.S." as a sentence end cut "U.S. unemployment hit 8.5%" down to
"unemployment hit 8.5%". The cost of never splitting after an acronym is that
"...in the U.S. Prices rose." stays one sentence -- merging two sentences is
less harmful than cutting the subject off a claim.

A line break also ends a sentence: content.js puts one between block elements
(list items, table cells, headings), which usually have no final period.
Without it, "- Unemployment: 14.8%" and "- Source: BLS" merged into one
sentence, so one item's source counted for its neighbour.
"""

import re

TITLES = {"dr", "mr", "mrs", "ms", "prof", "st", "no", "vs", "approx", "fig", "jr", "sr", "gov", "sen", "rep"}
ACRONYM = re.compile(r"(?:\b[A-Za-z]\.){2,}$")  # U.S.  e.g.  a.m.
BOUNDARY = re.compile(r"[.!?]\s+|[ \t]*\n\s*")


def _boundaries(text: str) -> list[int]:
    ends = []
    for m in BOUNDARY.finditer(text):
        before = text[:m.start() + 1]
        if m.end() == len(text):
            continue  # trailing whitespace, not a sentence boundary
        if text[m.start()] == ".":
            word = re.search(r"(\w+)\.$", before)
            if word and word.group(1).lower() in TITLES:
                continue
            if ACRONYM.search(before):
                continue
        ends.append(m.end())
    return ends


def find_sentence_span(text: str, match_start: int, match_end: int) -> tuple[str, int]:
    """Return the sentence containing text[match_start:match_end] and the
    sentence's start offset in `text`."""
    boundaries = _boundaries(text)
    sentence_start = 0
    for boundary in boundaries:
        if boundary > match_start:
            break
        sentence_start = boundary

    sentence_end = len(text)
    for boundary in boundaries:
        if boundary >= match_end:
            sentence_end = boundary
            break

    return text[sentence_start:sentence_end].strip(), sentence_start
