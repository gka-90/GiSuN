"""
detect_bias_framing() -- flags loaded phrases, controversial terms, or
contested framing in AI response text using a curated word list.

Matches the same shared flag format as detect_numeric_claims() so both
feed the same frontend renderer:
{sentence, matched_value, start_index, end_index, type}

Word list lives in bias_wordlist.json, organized into categories
(political framing, emotionally charged language, event framing,
absolutist claims, identity/group terms) so it's easy to review, edit,
and extend without touching this code.
"""

import json
import re
import os
from functools import lru_cache

from sentences import find_sentence_span


def _load_wordlist(path: str = "bias_wordlist.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=8)
def _compiled_wordlist(path: str, mtime: float) -> list[tuple[str, re.Pattern]]:
    """Read and compile the word list once; `mtime` is part of the cache key so
    editing bias_wordlist.json takes effect without restarting the server."""
    return [(category, re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE))
            for category, phrases in _load_wordlist(path).items() for phrase in phrases]


def _find_sentence_span(text: str, match_start: int, match_end: int):
    return find_sentence_span(text, match_start, match_end)[0]


def detect_bias_framing(text: str, wordlist_path: str = "bias_wordlist.json") -> list[dict]:
    """
    Scan `text` for loaded phrases / contested framing from the curated
    word list. Case-insensitive, whole-phrase matching (so "crisis" won't
    match inside "crisiscenter", but will match "Crisis" or "CRISIS").

    Returns a list of flags in the shared format:
        {
            "sentence": full sentence containing the match,
            "matched_value": the exact phrase as it appears in `text`,
            "start_index": character offset in `text`,
            "end_index": character offset where the match ends,
            "type": "bias_framing",
            "category": which word-list category it came from,
        }
    """
    flags = []

    # \b word boundaries so "crisis" doesn't match inside a longer word
    for category, pattern in _compiled_wordlist(wordlist_path, os.path.getmtime(wordlist_path)):
        for match in pattern.finditer(text):
            sentence = _find_sentence_span(text, match.start(), match.end())
            flags.append({
                "sentence": sentence,
                "matched_value": match.group(),
                "start_index": match.start(),
                "end_index": match.end(),
                "type": "bias_framing",
                "category": category,
            })

    flags.sort(key=lambda f: f["start_index"])
    return flags


def save_results_to_json(results, filename: str, output_dir: str = "output"):
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Saved results to {filepath}")
    return filepath


if __name__ == "__main__":
    test_cases = {
        "political_framing": (
            "The rise in homegrown terrorism has become a major concern. "
            "Critics say this is part of a radical left agenda."
        ),
        "emotionally_charged": (
            "Analysts describe this as a crisis requiring urgent action. "
            "The report calls the situation unprecedented and alarming."
        ),
        "event_framing": (
            "Police described the gathering as a riot, while organizers called "
            "the same people freedom fighters resisting an unjust system."
        ),
        "absolutist_claims": (
            "Everyone knows that this policy always fails. "
            "It is a fact that no one disputes this conclusion."
        ),
        "no_bias": (
            "Photosynthesis is the process by which plants convert sunlight into energy."
        ),
        "case_insensitivity_check": (
            "This was described as a CRISIS, and some called it a Riot."
        ),
    }

    all_results = {}
    for label, text in test_cases.items():
        all_results[label] = {
            "input_text": text,
            "flags": detect_bias_framing(text, wordlist_path="bias_wordlist.json"),
        }

    save_results_to_json(all_results, "bias_framing_results.json")
