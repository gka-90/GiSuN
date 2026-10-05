"""
Edge cases for numeric detection, sentence splitting, and source detection.
No model needed. Run from the project root:

    python -m unittest discover tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detect_numeric_claims import detect_numeric_claims  # noqa: E402
from gisun.tools.attribution import find_attribution  # noqa: E402


def found(text: str) -> list[tuple[str, str]]:
    return [(f["matched_value"], f["type"]) for f in detect_numeric_claims(text)]


class TestNumericDetection(unittest.TestCase):
    # (text, expected (matched_value, type) pairs in reading order)
    CASES = {
        # previously missed
        "percent spelled out": ("Unemployment rose to 8.5 percent last year.", [("8.5 percent", "percentage")]),
        "per cent": ("It fell 3 per cent.", [("3 per cent", "percentage")]),
        "percentage points": ("Rates rose 2 percentage points.", [("2 percentage points", "percentage_points")]),
        "basis points": ("The Fed cut by 25 basis points.", [("25 basis points", "percentage_points")]),
        "thousands separator": ("The war killed 40,000 people.", [("40,000", "count")]),
        "scale word": ("It displaced 3 million people.", [("3 million", "count")]),
        "dollars as word": ("Revenue was 1.2 billion dollars.", [("1.2 billion dollars", "dollar_amount")]),
        "euro / pound signs": ("It cost €500 or £20.", [("€500", "currency_amount"), ("£20", "currency_amount")]),
        "euros as word": ("The fine was 50 million euros.", [("50 million euros", "currency_amount")]),
        "one in three": ("One in three adults is obese.", [("One in three", "ratio")]),
        "out of": ("9 out of 10 dentists agree.", [("9 out of 10", "ratio")]),
        "fraction": ("Two-thirds of voters agreed.", [("Two-thirds of", "ratio")]),
        "doubled / 2x": ("Prices doubled, a 2x increase.", [("doubled", "ratio"), ("2x", "ratio")]),
        "fold": ("Cases rose 3-fold.", [("3-fold", "ratio")]),
        "decade": ("In the 2020s, things changed.", [("2020s", "year")]),
        "fiscal year": ("Spending peaked in FY2023.", [("FY2023", "year")]),
        # previously wrong
        "range": ("Growth was 5-10% annually.", [("5-10%", "percentage")]),
        "range with to": ("Growth was 5 to 10 percent.", [("5 to 10 percent", "percentage")]),
        "negative / plus": ("GDP fell -3% then rose +2.1%.", [("-3%", "percentage"), ("+2.1%", "percentage")]),
        "euro decimal": ("Inflation was 8,5% in Germany.", [("8,5%", "percentage")]),
        "thousands percent": ("Shares rose 1,000% in a year.", [("1,000%", "percentage")]),
        "page number": ("See page 2020 of the report.", []),
        "version number": ("Upgrade to version 2024 now.", []),
        "idiom 100% sure": ("I'm 100% sure you'll love it.", []),
        "idiom 110% effort": ("Give it 110% effort.", []),
        # overlaps: the longest match wins, no double flags
        "dollar with scale": ("Revenue was $1.2 billion.", [("$1.2 billion", "dollar_amount")]),
        "dollar short scale": ("They raised $2.3M.", [("$2.3M", "dollar_amount")]),
        "US$": ("It cost US$500.", [("US$500", "dollar_amount")]),
        "dollar range": ("Tickets cost $20-$40.", [("$20-$40", "dollar_amount")]),
        # still not flagged on purpose
        "plain small number": ("I have 3 cats.", []),
        "time": ("The meeting is at 20:15.", []),
        "temperature": ("Water boils at 100°C.", []),
        "pounds as weight": ("Add 5 pounds of flour.", []),
        "covid-19": ("COVID-19 spread fast.", []),
        # original cases from detect_numeric_claims.py
        "basic": ("Unemployment reportedly hit 8.5% in 2020, according to several reports.",
                  [("8.5%", "percentage"), ("2020", "year")]),
        "between years": ("Between 2019 and 2023, revenue grew from $10M to $50M, a 400% increase.",
                          [("2019", "year"), ("2023", "year"), ("$10M", "dollar_amount"),
                           ("$50M", "dollar_amount"), ("400%", "percentage")]),
        "year range": ("From 1990-2000 crime fell.", [("1990", "year"), ("2000", "year")]),
        # spelled-out numbers and quantity words (open problem #2)
        "spelled count": ("Forty-two thousand jobs were lost.", [("Forty-two thousand", "count")]),
        "spelled hundreds": ("Two hundred and five thousand people.", [("Two hundred and five thousand", "count")]),
        "a million": ("A million people came.", [("A million", "count")]),
        "spelled percent": ("About forty percent agreed.", [("forty percent", "percentage")]),
        "most + group": ("Most Americans agree.", [("Most Americans", "quantity")]),
        "majority of": ("The vast majority of voters said no.", [("The vast majority of", "quantity")]),
        "almost all": ("Almost all experts agree.", [("Almost all", "quantity")]),
        "a lot is not a number": ("It was a lot of work.", []),
        "most + adjective": ("The most important thing.", []),
        "one of": ("One of the best.", []),
    }

    def test_cases(self):
        for name, (text, expected) in self.CASES.items():
            with self.subTest(name):
                self.assertEqual(found(text), expected)

    def test_offsets_match_value(self):
        text = "Between 2019 and 2023, revenue grew from $10M to $50M, a 400% increase. 9 out of 10 agree."
        for f in detect_numeric_claims(text):
            self.assertEqual(text[f["start_index"]:f["end_index"]], f["matched_value"])


class TestSentenceSplitting(unittest.TestCase):
    def sentence_of(self, text: str) -> str:
        return detect_numeric_claims(text)[0]["sentence"]

    def test_acronym_does_not_end_sentence(self):
        self.assertEqual(self.sentence_of("U.S. unemployment hit 8.5% in 2020. Prices rose."),
                         "U.S. unemployment hit 8.5% in 2020.")

    def test_title_does_not_end_sentence(self):
        self.assertEqual(self.sentence_of("Hi. Dr. Smith says 40% of patients improved. Bye."),
                         "Dr. Smith says 40% of patients improved.")

    def test_decimal_does_not_end_sentence(self):
        self.assertEqual(self.sentence_of("Rates hit 8.5% today. Next."), "Rates hit 8.5% today.")

    def test_line_break_ends_sentence(self):
        # list items have no final period; they must not merge (open problem #16)
        flags = detect_numeric_claims("- Unemployment: 14.8%\n- Inflation: 3%")
        self.assertEqual([f["sentence"] for f in flags], ["- Unemployment: 14.8%", "- Inflation: 3%"])

    def test_normal_split(self):
        self.assertEqual(self.sentence_of("Prices rose. Rent hit $2,000 in 2023! Wow."),
                         "Rent hit $2,000 in 2023!")


class TestSourceDetection(unittest.TestCase):
    NAMED = [
        "Unemployment hit 8.5%, according to the BLS.",
        "According to Wikipedia, 40% of teens vape.",
        "According to the 2020 Census, 40% rent.",
        "Unemployment hit 8.5% (BLS, 2023).",
        "Unemployment hit 8.5% [1].",
        "The BLS reports that unemployment hit 8.5%.",
        "Pew Research found that 40% agree.",
        "Source: Pew Research, 40% of adults agree.",
        "Unemployment hit 8.5% (https://www.bls.gov).",
    ]
    NOT_NAMED = [
        "According to a 2021 study, 40% of teens vape.",
        "According to experts, 40% agree.",
        "Experts found that 40% agree.",
        "Research shows 40% agree.",
        "The report says 40% agree.",
        "The study found 40% agree.",
        "Home prices rose 40% between 2019 and 2023.",
        "In 2020 unemployment hit 8.5%.",
    ]

    def test_named(self):
        for text in self.NAMED:
            with self.subTest(text):
                self.assertTrue(find_attribution(text)["names_specific_source"])

    def test_not_named(self):
        for text in self.NOT_NAMED:
            with self.subTest(text):
                self.assertFalse(find_attribution(text)["names_specific_source"])


if __name__ == "__main__":
    unittest.main()
