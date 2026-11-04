"""
evaluation/datasets/c4_logic_testset.py on a small made-up CSV in LOGIC's format (no download).
    python -m unittest tests.test_c4_logic_testset
"""

import csv
import os
import tempfile
import unittest

from evaluation.datasets import c4_logic_testset as logic

ROWS = [("faulty generalization", f"All {w} people in this town are terrible drivers.") for w in
        ("tall", "short", "young", "old", "rich", "poor")] + \
       [("ad hominem", f"You can't trust {n} on taxes because he is a liar.") for n in ("Tom", "Bob", "Sam", "Al")] + \
       [("false dilemma", "Either you support the plan or you hate this country."),
        ("ad populum", "Either you support the plan or you hate this country."),   # two classes: left out
        ("faulty generalization", '"Everyone in my class failed, so the whole school is failing."'),
        ("ad populum", ", or a group of people think, in order to persuade one to think the same way."),
        ("circular reasoning", "We need new judges. This logical fallacy is called..."),
        ("ad hominem", "He is wrong. He also lies about everything else."),           # two sentences
        ("miscellaneous", "This sentence is in no single class at all."),
        ("false causality", "Why did the stock market fall right after the election?")]


class LogicTestset(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.csv = os.path.join(self.dir, "edu_all.csv")
        with open(self.csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, ["updated_label", "original_url", "old_label", "source_article", "explanations", "rationale"])
            w.writeheader()
            for label, text in ROWS:
                w.writerow({"updated_label": label, "source_article": text})

    def test_only_usable_single_class_sentences(self):
        by_text = logic.load(self.csv)
        self.assertIn("Everyone in my class failed, so the whole school is failing.", by_text)  # quotes stripped
        self.assertEqual(by_text["Either you support the plan or you hate this country."], {"false dilemma", "ad populum"})
        for gone in (", or a group", "This logical fallacy", "He is wrong.", "This sentence is in no", "Why did"):
            self.assertFalse(any(t.startswith(gone) or gone in t for t in by_text), gone)

    def test_build_is_balanced_seeded_and_in_gold_format(self):
        by_text = logic.load(self.csv)
        a, b = logic.build(by_text, n=4, seed=1), logic.build(by_text, n=4, seed=1)
        self.assertEqual(a, b)  # fixed seed
        self.assertEqual([i["labels"][i["text"]]["C4"] for i in a], ["met"] * 4 + ["not_met"] * 4)
        self.assertTrue(all(i["logic_label"] == "faulty generalization" for i in a[:4]))
        self.assertTrue(all(i["logic_label"] != "faulty generalization" for i in a[4:]))
        self.assertNotIn("Either you support the plan or you hate this country.", [i["text"] for i in a])
        self.assertEqual(set(a[0]), {"id", "source", "logic_label", "question", "text", "labels"})
        with self.assertRaises(ValueError):
            logic.build(by_text, n=50)

    def test_download_checks_the_hash(self):
        with self.assertRaises(RuntimeError):  # the file is already there, so nothing is fetched
            logic.download(self.csv, url="http://invalid.example/never-fetched", sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
