"""
detect_numeric_claims() -- scans AI response text and flags sentences
containing numbers, percentages, or years for fact-checking.

Matches the format used across all detection functions so the frontend
renderer can treat numeric flags and bias flags the same way:
{sentence, matched_value, start_index, end_index}
"""

import re

from sentences import find_sentence_span

# A number, longest grouping style first (formats from "Statistic Formats for Claim Detection"):
#   Indian "10,00,000" | US "40,000" / "1,200.5" | European "1.000.000,50" (2+ groups, so "1.000"
#   stays a decimal) | spaced "1 000 000" (not followed by more digits, so phone numbers don't
#   match) | plain "8.5" / "8,5" | a leading decimal ".5" (START keeps "8.5" from matching as ".5").
_SPACE = "[    ]"  # regular, non-breaking, narrow and thin spaces
INDIAN_NUM = r"\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?"
EUROPEAN_NUM = r"\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?"
SPACED_NUM = rf"\d{{1,3}}(?:{_SPACE}\d{{3}}){{2,}}(?!{_SPACE}?\d)"
NUM = (rf"{INDIAN_NUM}"
       r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
       rf"|{EUROPEAN_NUM}"
       rf"|{SPACED_NUM}"
       r"|\d+(?:[.,]\d+)?"
       r"|\.\d+")
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
FRACTION_WORD = r"(?:half|halves|thirds?|quarters?|fifths?|tenths?)"
UNICODE_FRACTION = "[½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]"
# A single-letter magnitude must be glued to the number and not start a name: "3.5M", "12k",
# but not "221B Baker Street" or "4K TV" (case-sensitive, unlike the rest of the patterns)
LETTER_MAGNITUDE = r"(?-i:(?:[MBK]|k)\b(?!\s[A-Z]))"

# Ordered by type; when matches overlap, the longest one wins (see _drop_overlaps).
# Deliberately NOT flagged (see the formats PDF's false positives, and alarm fatigue): a bare
# number with no unit ("about 500", "twenty-five", "fewer than 10"), measurements and times.
PATTERNS = {
    "percentage": [
        rf"{START}{SIGN}(?:{NUM}){RANGE_TAIL}\s?(?:%|‰|‱|٪|percent\b|per cent\b)",  # also per mille, Arabic %
        rf"\b(?!a\s){SPELLED}\s(?:percent|per cent)\b",           # forty percent
    ],
    "percentage_points": [
        rf"{START}{SIGN}(?:{NUM}){RANGE_TAIL}\s?(?:percentage points?|basis points?|pp\b|bps\b)",
    ],
    "dollar_amount": [
        rf"(?:US|CAD|AUD)?\$\s?(?:{NUM})(?:\s?(?:-|–|to)\s?\$?(?:{NUM}))?(?:\s?{SCALE})?",
        rf"{START}(?:{NUM})(?:\s{SCALE_WORD})?\s(?:dollars|bucks|USD)\b",       # 20 dollars, 5 bucks
        rf"\b{_UNDER_100}\s(?:dollars|bucks)\b",                               # ten dollars
        rf"\bUSD\s?(?:{NUM})(?:\s?{SCALE})?",
    ],
    "currency_amount": [
        rf"[€£¥₹]\s?(?:{NUM})(?:\s?(?:{SCALE}|lakh\b|crore\b))?",               # also ₹2 lakh / ₹5 crore
        rf"{START}(?:{NUM})\s?[€£¥₹]",                                          # 500€ (symbol after)
        # not plain "pounds": "5 pounds of flour" is a weight
        rf"{START}(?:{NUM})(?:\s{SCALE_WORD})?\s(?:euros?|pounds sterling|yen|rupees|EUR|GBP|JPY|INR)\b",
        rf"\b{_UNDER_100}\s(?:euros?|yen|rupees)\b",                           # ten euros
        rf"\b(?:EUR|GBP|JPY|INR)\s?(?:{NUM})",
    ],
    "count": [
        rf"(?<![\w.,$€£¥])(?:{NUM})\s(?:{SCALE_WORD}|dozen)\b",                 # 3 million, 1.5 dozen
        r"(?<![\w.,$€£¥])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d%])",  # 40,000
        # the other grouping styles, standalone: 10,00,000 / 1.000.000,50 / 1 000 000
        rf"(?<![\w.,$€£¥])(?:{INDIAN_NUM}|{EUROPEAN_NUM}|{SPACED_NUM})(?![\d%])",
        rf"(?<![\w.,$€£¥])(?:{NUM})(?:\s?(?:bn|mn|tn)\b|{LETTER_MAGNITUDE})",   # 3.5M, 12k, 1.2bn
        rf"\b{SPELLED}\s(?:{SCALE_WORD}|dozen)\b",              # forty-two thousand, a million, a dozen
        rf"(?<![\w.])(?:{NUM})\s?[×x]\s?10(?:\^-?\d+|[⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+)",          # 3.2 × 10^6
        r"(?<![\w.])\d+(?:\.\d+)?[eE][-+]?\d+\b",                              # 1e9, 4.5E-3
        rf"(?<![\w.])\d+{UNICODE_FRACTION}",                                    # 2½
        rf"\b(?:rose|fell|grew|increased|decreased|dropped|jumped|climbed|declined|went)\sfrom\s"
        rf"(?:{NUM})\sto\s(?:{NUM})\b",                                         # rose from 200 to 350
    ],
    "quantity": [
        r"\b(?:the|a)\s(?:(?:vast|large|slim|narrow|small|clear)\s)?(?:majority|minority)"
        r"(?:\sof\b|(?!\s(?:leader|party|owner|stake|group|shareholder)))",  # a majority of / a minority
        r"\b(?:nearly|almost|virtually|practically)\s(?:all|everyone|everybody|no one|none)\b",
        rf"\bmost\s(?:of\s(?:the\s)?)?{GROUP}\b",
        # nearly half, roughly a third, over two-thirds
        r"\b(?:nearly|almost|roughly|about|around|over|more than|less than|under|just under|just over)\s"
        r"(?:half|a\s(?:third|quarter|fifth|tenth)|two[- ]thirds|three[- ]quarters)\b",
        # vague magnitudes: tens of thousands, hundreds of, dozens of, millions of
        r"\b(?:tens|hundreds|dozens|scores)\sof\s(?:thousands|millions|billions)\b",
        r"\b(?:hundreds|thousands|millions|billions|dozens)\sof\b",
        r"\b(?:single|double|triple|five|six|seven)[- ](?:digits?|figures?)\b",  # six-figure, double-digit
    ],
    "ratio": [
        rf"\b{SMALL}\s(?:in|out of)\s(?:{SMALL}|{NUM})\b",     # one in three, 9 out of 10, 1 in 10,000
        rf"\b(?:half|(?:a|one|two|three|four|nine)[- ]{FRACTION_WORD})\sof\b",  # two-thirds of, a tenth of
        r"\b(?:doubled|tripled|quadrupled|halved)\b",
        r"(?<![\w.])\d+(?:\.\d+)?(?:x|×|-fold|\sfold)(?!\w)",  # 2x, 3-fold
        r"(?<!\w)×\s?\d+(?:\.\d+)?\b",                         # ×3
        r"\b(?:two|three|four|five|six|seven|eight|nine|ten|twenty|a\shundred|hundred|a\sthousand)[- ]?fold\b",
        # multipliers: twice as likely, three times more, 2.5 times higher, thrice, half as many
        r"\b(?:twice|(?:two|three|four|five|ten|\d+(?:\.\d+)?)\stimes)\s(?:as\s\w+|more|less|fewer|higher|lower|"
        r"larger|smaller|greater|faster|slower|bigger)\b",
        r"\bthrice\b",
        r"\bhalf\sas\s(?:many|much|likely|large|big)\b",
        # fractions in digits (3/4, 1/3 of adults): see _keep for 24/7, 20/20 vision, 120/80
        r"(?<![\w/.])\d{1,3}/\d{1,3}(?![\w/])",
        rf"(?<![\w]){UNICODE_FRACTION}",                       # ½, ¾
        # ratios and odds: 3-to-1, 3:1 odds, a 2:1 margin ("14:00" and "John 3:16" need the word)
        r"\b\d+-to-\d+\b",
        r"\b\d+:\d+(?=\s(?:odds|ratio|margin|majority|split|lead))",
        r"\b(?:odds|ratio)\sof\s\d+:\d+",
        rf"{START}(?:{NUM})\sper\s(?:{NUM}|one\s\w+|a\s(?:thousand|million|hundred))\b",  # 5 per 1,000
        rf"\bevery\s(?:{NUM})\s(?:seconds|minutes|hours|days|weeks)\b",                    # every 36 seconds
    ],
    # Polls, ratings and sports results
    "score": [
        rf"{START}{SIGN}(?:{NUM})\s?(?:pts?\b|points?\b)",             # 3 pts, up 120 points, 35 points
        rf"{START}(?:{NUM})\s(?:stars?)\b",                            # rated 4.7 stars
        r"\bscored\s\d+(?:\.\d+)?/\d+\b",                             # scored 98/100
        r"\b\d{1,3}[–-]\d{1,3}\s(?:record|win|loss|victory|defeat|vote|lead|margin|split)\b",  # a 10-2 record
        r"\b(?:won|lost|beat|defeated|leads?|led|trails?|trailed)\s(?:\w+\s)?\d{1,3}[–-]\d{1,3}\b",  # won 3-1
        r"(?<![\w.])\.\d{3}\s(?:batting\s)?average\b",               # a .300 batting average
    ],
    # Research statistics
    "statistic": [
        r"\bp\s?[<=>≤≥]\s?0?\.\d+",                                    # p < 0.05, p = .003
        rf"\b(?:odds ratio|relative risk|risk ratio|hazard ratio)\s(?:of\s)?(?:{NUM})",
        r"\b(?:r|R²|R\^2)\s?=\s?-?0?\.\d+",                           # r = 0.65, R² = 0.4
        rf"\b[nN]\s?=\s?(?:{NUM})",                                    # n = 1,200
        rf"\b(?:an?\s)?(?:average|mean|median)\s(?:\w+\s){{0,2}}of\s(?:{NUM})",  # an average of 3.2
        r"\b\d{2}%\s(?:CI|confidence interval)\b",                    # 95% CI
    ],
    # Rankings: top 10, ranked 3rd, the second-largest
    "ranking": [
        # "top 10" / "the top 5%", but not a list intro like "the top 5 tips"
        r"\btop\s\d+(?:%|\b(?!\s(?:tips|ways|reasons|things|ideas|strategies|steps|examples|options|picks|"
        r"books|movies|songs|places|questions|mistakes|tools)\b))",
        r"\b(?:ranked|ranks|ranking)\s#?\d+(?:st|nd|rd|th)?\b",
        r"\b(?:\d+(?:st|nd|rd|th)|second|third|fourth|fifth)[- ](?:largest|biggest|highest|lowest|most|best|"
        r"worst|smallest|richest|poorest)\b",
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


# "a million thanks", "a thousand times": idioms, not counts
IDIOM_COUNT_AFTER = re.compile(r"^\s*(?:thanks|times|apologies|kisses|questions|reasons|ways)\b", re.IGNORECASE)
# "20/20 vision" and blood pressure "120/80" are readings, not fractions
NOT_A_FRACTION_NEAR = re.compile(r"blood pressure|\bbp\b", re.IGNORECASE)
# "1/2 cup", "a quarter of an hour": a measurement (a recipe, a duration), not a statistic
MEASURE_AFTER = re.compile(
    r"^\s(?:of\s)?(?:an?\s)?(?:cups?|teaspoons?|tablespoons?|tsp|tbsp|inch(?:es)?|miles?|hours?|minutes?|"
    r"pounds?|lbs?|ounces?|oz|lit(?:er|re)s?|kg|kilos?|grams?|met(?:er|re)s?|feet|foot|mile|gallons?)\b",
    re.IGNORECASE)


def _keep(text: str, claim_type: str, match: re.Match) -> bool:
    if claim_type == "year" and NOT_A_YEAR_BEFORE.search(text[max(0, match.start() - 12):match.start()]):
        return False
    if claim_type == "percentage" and IDIOM_AFTER.match(text[match.end():]):
        return False
    value = match.group()
    if claim_type in ("ratio", "quantity") and MEASURE_AFTER.match(text[match.end():]):
        return False
    if claim_type == "count" and value.lower().startswith("a ") and IDIOM_COUNT_AFTER.match(text[match.end():]):
        return False
    if claim_type == "ratio" and re.fullmatch(r"\d+/\d+", value):
        top, bottom = (int(x) for x in value.split("/"))
        # a fraction is at most 1 (this drops 24/7 and 120/80); 20/20 is only kept away from "vision"
        if top > bottom or bottom == 0 or re.match(r"\s*vision\b", text[match.end():], re.IGNORECASE):
            return False
        if NOT_A_FRACTION_NEAR.search(text[max(0, match.start() - 20):match.start()]):
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
                    "quantity" | "score" | "statistic" | "ranking" | "year",
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