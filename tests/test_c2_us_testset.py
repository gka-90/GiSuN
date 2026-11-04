"""
evaluation/datasets/c2_us_testset.py: which C2 claims the series catalog can look up. Offline:
the APIs are answered by tests/fake_stats.py, and only the country list may be requested.
    python -m unittest tests.test_c2_us_testset
"""

import json
import os
import tempfile
import unittest

from evaluation.datasets.c2_us_testset import build, why_not
from tests import fake_stats


def item(i, text, label="met"):
    return {"id": f"t{i}", "question": "", "text": text, "labels": {text[:40]: {"C2": label}}}


CASES = {
    "The U.S. unemployment rate averaged 12% in 2020.": None,
    "California's unemployment rate was 16% in April 2020.": None,
    "Germany's unemployment rate was 9% in 2020.": "not_us",
    "Inflation in the United States is costing households an extra $175 a month in 2022.": "unit_mismatch",
    "Unemployment peaked at 14.8% in April 2020.": "place_or_period_not_stated",
    "The U.S. Medicare program wasted $50 billion in 2019.": "measure_not_in_catalog",
    "This video shows a crowd in Times Square in January 2021.": "no_checkable_number",
}


class C2UsTestset(unittest.TestCase):
    def setUp(self):
        self.requests = fake_stats.install(self)

    def test_reasons(self):
        for i, (text, reason) in enumerate(CASES.items()):
            with self.subTest(text=text):
                self.assertEqual(why_not(item(i, text))[0], reason)

    def test_kept_items_are_gold_format_with_the_lookup_fields(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "gold_public_x.json")
            items = [item(i, t) for i, t in enumerate(CASES)] + [{"id": "c3", "question": "", "text": "A disgraced man.",
                                                                  "labels": {"A disgraced man.": {"C3": "met"}}}]
            json.dump(items, open(src, "w"))
            kept, reasons, _ = build([src])
        self.assertEqual(sum(reasons.values()), len(CASES))  # the C3 row is not a C2 claim
        self.assertEqual([k["id"] for k in kept], ["t0", "t1"])
        self.assertEqual(kept[0]["c2_fields"]["series"], ["bls_unemployment_u3"])
        self.assertEqual(kept[0]["labels"], {"The U.S. unemployment rate averaged 12% ": {"C2": "met"}})
        for k in kept:
            self.assertIn(next(iter(k["labels"])).lower(), k["text"].lower())

    def test_no_statistics_api_is_called(self):
        for i, text in enumerate(CASES):
            why_not(item(i, text))
        urls = [c.args[0] for c in self.requests.call_args_list]
        self.assertTrue(all("api.worldbank.org/v2/country?" in u for u in urls), urls)


if __name__ == "__main__":
    unittest.main()
