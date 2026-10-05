"""
detect_numeric_claims() -- scans AI response text and flags sentences
containing numbers, percentages, or years for fact-checking.

Matches the format used across all detection functions so the frontend
renderer can treat numeric flags and bias flags the same way:
{sentence, matched_value, start_index, end_index}
"""

import re

from sentences import find_sentence_span

# A number: "40,000" / "1,200.5" (thousands separators) or "8.5" / "8,5" (European decimal).
# The thousands form is tried first, so "8,5" only matches as a decimal.
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?"
# Not glued to a preceding word/number, so "8,5%" isn't read as "5%"
START = r"(?<![\w.,])"
SIGN = r"[-+−]?"
RANGE_TAIL = rf"(?:\s?(?:-|–|—|to)\s?{SIGN}(?:{NUM}))?"  # "5-10%", "5 to 10 percent"
SCALE = r"(?:trillion|billion|million|thousand|tn|bn|mn|[tbmk])\b"
SCALE_WORD = r"(?:trillion|billion|million|thousand)"
SMALL = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
# Spelled-out numbers up to the hundreds: "forty-two", "seventeen", "two hundred and five"
_ONES = r"(?:one|two|three|four|five|six|seven|eight|nine)"
_TEENS = r"(?:ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"
_TENS = r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
_UNDER_100 = rf"(?:{_TENS}(?:[- ]{_ONES})?|{_TEENS}|{_ONES})"
SPELLED = rf"(?:{_UNDER_100}(?:\shundred(?:\s(?:and\s)?{_UNDER_100})?)?|a\shundred|a)"
# "most Americans": a quantity with no number, which still needs a source
GROUP = (r"(?:Americans|people|adults|voters|experts|scientists|economists|doctors|students|"
         r"workers|users|children|parents|women|men|countries|states|households|companies|businesses)")

# Ordered by type; when matches overlap, the longest one wins (see _drop_overlaps).
PATTERNS = {
    "percentage": [
        rf"{START}{SIGN}(?:{NUM}){RANGE_TAIL}\s?(?:%|percent\b|per cent\b)",
        rf"\b(?!a\s){SPELLED}\s(?:percent|per cent)\b",           # forty percent
    ],
    "percentage_points": [
        rf"{START}{SIGN}(?:{NUM}){RANGE_TAIL}\s?(?:percentage points?|basis points?|pp\b|bps\b)",
    ],
    "dollar_amount": [
        rf"(?:US)?\$\s?(?:{NUM})(?:\s?(?:-|–|to)\s?\$?(?:{NUM}))?(?:\s?{SCALE})?",
        rf"{START}(?:{NUM})(?:\s{SCALE_WORD})?\s(?:dollars|USD)\b",
        rf"\bUSD\s?(?:{NUM})(?:\s?{SCALE})?",
    ],
    "currency_amount": [
        rf"[€£¥]\s?(?:{NUM})(?:\s?{SCALE})?",
        # not plain "pounds": "5 pounds of flour" is a weight
        rf"{START}(?:{NUM})(?:\s{SCALE_WORD})?\s(?:euros?|pounds sterling|yen|EUR|GBP|JPY)\b",
        rf"\b(?:EUR|GBP|JPY)\s?(?:{NUM})",
    ],
    "count": [
        rf"(?<![\w.,$€£¥])(?:{NUM})\s{SCALE_WORD}\b",         # 3 million
        r"(?<![\w.,$€£¥])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d%])",  # 40,000
        rf"\b{SPELLED}\s{SCALE_WORD}\b",                        # forty-two thousand, a million
    ],
    "quantity": [
        r"\b(?:the|a)\s(?:(?:vast|large|slim|narrow|small|clear)\s)?(?:majority|minority)\sof\b",
        r"\b(?:nearly|almost|virtually|practically)\s(?:all|everyone|everybody|no one|none)\b",
        rf"\bmost\s(?:of\s(?:the\s)?)?{GROUP}\b",
    ],
    "ratio": [
        rf"\b{SMALL}\s(?:in|out of)\s{SMALL}\b",               # one in three, 9 out of 10
        r"\b(?:half|one[- ]third|a third|one[- ]quarter|a quarter|two[- ]thirds|three[- ]quarters)\sof\b",
        r"\b(?:doubled|tripled|quadrupled|halved)\b",
        r"(?<![\w.])\d+(?:\.\d+)?(?:x|×|-fold|\sfold)(?!\w)",  # 2x, 3-fold
    ],
    "year": [
        r"\b(?:19|20)\d{2}s?\b",                               # 2020, 2020s
        r"\bFY\s?(?:(?:19|20)\d{2}|\d{2})\b",                  # FY2023, FY23
    ],
}
PATTERNS = {t: [re.compile(p, re.IGNORECASE) for p in ps] for t, ps in PATTERNS.items()}

# A "year" right after these is a page / version / ID number, not a date
NOT_A_YEAR_BEFORE = re.compile(
    r"(?:page|pages|p\.|pp\.|version|v\.?|no\.|number|#|chapter|section|room|model|isbn|route|flight)\s*$",
    re.IGNORECASE)
# "100% sure", "110% effort": figures of speech, not statistics
IDIOM_AFTER = re.compile(
    r"^\s*(?:sure|certain|confident|positive|honest|correct|right|committed|effort|agree)\b", re.IGNORECASE)


def _keep(text: str, claim_type: str, match: re.Match) -> bool:
    if claim_type == "year" and NOT_A_YEAR_BEFORE.search(text[max(0, match.start() - 12):match.start()]):
        return False
    if claim_type == "percentage" and IDIOM_AFTER.match(text[match.end():]):
        return False
    return True


def _drop_overlaps(flags: list[dict]) -> list[dict]:
    """Patterns overlap ("1.2 billion" is a count, "1.2 billion dollars" a dollar
    amount). Walk in reading order and keep the longest match at each spot."""
    flags.sort(key=lambda f: (f["start_index"], -(f["end_index"] - f["start_index"])))
    kept, last_end = [], -1
    for flag in flags:
        if flag["start_index"] >= last_end:
            kept.append(flag)
            last_end = flag["end_index"]
    return kept


def _find_sentence_span(text: str, match_start: int, match_end: int):
    return find_sentence_span(text, match_start, match_end)


def detect_numeric_claims(text: str) -> list[dict]:
    """
    Scan `text` for numeric/statistical claims (percentages, dollar
    amounts, years). Returns a list of flags in the shared format:

        {
            "sentence": the full sentence containing the match,
            "matched_value": the exact substring that was matched,
            "start_index": character offset of the match in `text`,
            "end_index": character offset where the match ends in `text`,
            "type": which pattern matched: "percentage" | "percentage_points" |
                    "dollar_amount" | "currency_amount" | "count" | "ratio" |
                    "quantity" | "year",
        }
    """
    flags = []

    for claim_type, patterns in PATTERNS.items():
        for pattern in patterns:
            for match in pattern.finditer(text):
                if not _keep(text, claim_type, match):
                    continue
                sentence, _ = _find_sentence_span(text, match.start(), match.end())
                flags.append({
                    "sentence": sentence,
                    "matched_value": match.group(),
                    "start_index": match.start(),
                    "end_index": match.end(),
                    "type": claim_type,
                })

    # _drop_overlaps also leaves them in reading order for the frontend
    return _drop_overlaps(flags)


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