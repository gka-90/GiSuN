"""
detect_numeric_claims() -- scans AI response text and flags sentences
containing numbers, percentages, or years for fact-checking.

Matches the format used across all detection functions so the frontend
renderer can treat numeric flags and bias flags the same way:
{sentence, matched_value, start_index, end_index}
"""

import re

# Patterns from the Excel spec:
#   \d+(\.\d+)?%      -> percentages, e.g. 8.5%
#   \$\d+             -> dollar amounts, e.g. $8.5B (basic version, see notes below)
#   \b(19|20)\d{2}\b  -> years from 1900-2099
PATTERNS = {
    "percentage": re.compile(r"\d+(?:\.\d+)?%"),
    "dollar_amount": re.compile(r"\$\d+(?:,\d{3})*(?:\.\d+)?\s?(?:[BbMmKk](?:illion)?)?"),
    "year": re.compile(r"\b(?:19|20)\d{2}\b"),
}


def _find_sentence_span(text: str, match_start: int, match_end: int):
    """Given the text and a match's character range, return the full
    sentence that contains it (and that sentence's own start index in text).
    Splits on . ! ? followed by whitespace -- good enough for chatbot prose,
    not meant to handle abbreviations like 'Dr.' perfectly."""
    sentence_boundaries = [m.end() for m in re.finditer(r"[.!?]\s+", text)]
    sentence_start = 0
    for boundary in sentence_boundaries:
        if boundary > match_start:
            break
        sentence_start = boundary

    sentence_end = len(text)
    for boundary in sentence_boundaries:
        if boundary >= match_end:
            sentence_end = boundary
            break

    return text[sentence_start:sentence_end].strip(), sentence_start


def detect_numeric_claims(text: str) -> list[dict]:
    """
    Scan `text` for numeric/statistical claims (percentages, dollar
    amounts, years). Returns a list of flags in the shared format:

        {
            "sentence": the full sentence containing the match,
            "matched_value": the exact substring that was matched,
            "start_index": character offset of the match in `text`,
            "end_index": character offset where the match ends in `text`,
            "type": which pattern matched ("percentage" | "dollar_amount" | "year"),
        }
    """
    flags = []

    for claim_type, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            sentence, _ = _find_sentence_span(text, match.start(), match.end())
            flags.append({
                "sentence": sentence,
                "matched_value": match.group(),
                "start_index": match.start(),
                "end_index": match.end(),
                "type": claim_type,
            })

    # Sort by position so the frontend can process them in reading order
    flags.sort(key=lambda f: f["start_index"])
    return flags


def save_results_to_json(results, filename: str, output_dir: str = "output"):
    """
    Save detection results to a JSON file inside `output_dir`
    (created automatically if it doesn't exist yet).
    """
    import os
    import json

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(results)} flags to {filepath}")
    return filepath


if __name__ == "__main__":
    test_cases = {
        "basic": (
            "Unemployment reportedly hit 8.5% in 2020, according to several reports. "
            "The company raised $2.3M in its first funding round back in 1999. "
            "By 2024, the market had grown to over $1B in total value."
        ),
        "no_numbers": "Photosynthesis is the process by which plants make food.",
        "tricky_false_positives": "See page 2020 of the report for details. Version 8.5 was released recently.",
        "multiple_numbers_one_sentence": "Between 2019 and 2023, revenue grew from $10M to $50M, a 400% increase.",
        "number_at_edges": "2024 was a record year. Growth reached 12%.",
    }

    all_results = {}
    for label, text in test_cases.items():
        all_results[label] = {
            "input_text": text,
            "flags": detect_numeric_claims(text),
        }

    save_results_to_json(all_results, "numeric_claims_results.json")