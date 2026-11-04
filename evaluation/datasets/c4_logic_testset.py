"""
C4 test set from LOGIC (Jin et al. 2022, "Logical Fallacy Detection", github causalNLP/logical-fallacy):
50 "faulty generalization" sentences labeled C4 met and 50 sentences from the other fallacy classes
labeled C4 not_met, sampled with a fixed seed. Our own C4 set has almost no positive examples
(4 met of 447 pairs in datasets/gold_answers.json).

The file is downloaded once (pinned to a commit and checked by SHA-256) into
datasets/external/logic/ (git-ignored). Only single sentences GiSuN turns into a claim are used
(a gold label matches one claim sentence), and a text that appears under more than one class is
left out. Writes datasets/gold_c4_logic.json in the gold format of datasets/gold_example.json.

    python -m evaluation.datasets.c4_logic_testset            # -> datasets/gold_c4_logic.json
    python -m evaluation.datasets.c4_logic_testset --seed 7 --n 50

Note: LOGIC's "faulty generalization" includes hasty inferences from one case ("It is warmer
this year in Las Vegas ...; therefore, global warming is rapidly accelerating"), not only the
unqualified universal claims C4 asks about, and some other-class sentences use absolute words
("Everyone is buying it"). Read the results with that in mind, or relabel a sample.
"""

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import urllib.request
from collections import Counter

sys.path.insert(0, os.getcwd())
from gisun.detectors.claims import _is_candidate
from gisun.preprocess import split_sentences

COMMIT = "bb5750cbcc8a28007796d811cb95dae8da859d4f"  # last commit touching data/edu_all.csv (2022-04-14)
URL = f"https://raw.githubusercontent.com/causalNLP/logical-fallacy/{COMMIT}/data/edu_all.csv"
SHA256 = "bc03ca335524518b8eda3c63b97f45d15af3096de10fe1a4c3a890aabd7556a0"
RAW = os.path.join("datasets", "external", "logic", "edu_all.csv")
OUT = os.path.join("datasets", "gold_c4_logic.json")
POSITIVE = "faulty generalization"
SKIP_CLASSES = {"miscellaneous"}  # 3 rows, no single fallacy
SEED, N = 2022, 50


def download(path: str = RAW, url: str = URL, sha256: str = SHA256) -> str:
    """Download the file unless it is already there; refuse it if the hash differs."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    with open(path, "rb") as f:
        got = hashlib.sha256(f.read()).hexdigest()
    if got != sha256:
        raise RuntimeError(f"{path}: SHA-256 {got} is not the pinned {sha256}; delete it and download again")
    return path


def clean(text: str) -> str:
    """One line, without the quotation marks many LOGIC items are wrapped in."""
    text = re.sub(r"\s+", " ", text or "").strip()
    return text.strip("\"'“” ").strip()


# Quiz debris in LOGIC, not example arguments: "..., or a group of people think, in order to ...",
# "... This logical fallacy is called...", "Which fallacy is this?"
QUIZ_TEXT = re.compile(r"\bfallac(?:y|ies)\b|\bis called\b|\b(?:example|answer) (?:of|is)\b", re.I)


def usable(text: str) -> bool:
    """A single sentence the pipeline turns into a claim (not a question, fragment or instruction),
    and an example argument rather than quiz text."""
    if not re.match(r"[A-Z0-9]", text) or text.endswith(("...", "\u2026")) or QUIZ_TEXT.search(text):
        return False
    sentences = split_sentences(text)
    return len(sentences) == 1 and sentences[0] == text and _is_candidate(text)


def load(path: str) -> dict[str, set[str]]:
    """{clean text: set of LOGIC labels} for the usable rows."""
    by_text: dict[str, set[str]] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            label, text = (row.get("updated_label") or "").strip(), clean(row.get("source_article"))
            if label and label not in SKIP_CLASSES and usable(text):
                by_text.setdefault(text, set()).add(label)
    return by_text


def build(by_text: dict[str, set[str]], n: int = N, seed: int = SEED) -> list[dict]:
    single = {t: next(iter(ls)) for t, ls in by_text.items() if len(ls) == 1}  # one class only
    pos = sorted(t for t, l in single.items() if l == POSITIVE)
    neg = sorted(t for t, l in single.items() if l != POSITIVE)
    if len(pos) < n or len(neg) < n:
        raise ValueError(f"only {len(pos)} positive / {len(neg)} negative usable sentences for n={n}")
    rng = random.Random(seed)
    items = []
    for name, texts, decision in (("fg", rng.sample(pos, n), "met"), ("other", rng.sample(neg, n), "not_met")):
        for i, text in enumerate(texts, 1):
            items.append({"id": f"logic-{name}-{i:03d}", "source": f"LOGIC (Jin et al. 2022), edu_all.csv @ {COMMIT[:7]}",
                          "logic_label": single[text], "question": "", "text": text,
                          "labels": {text: {"C4": decision}}})
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=N, help="sentences per side")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    by_text = load(download())
    items = build(by_text, a.n, a.seed)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1, ensure_ascii=False)
    print(json.dumps({"usable_sentences": len(by_text),
                      "in_more_than_one_class": sum(len(v) > 1 for v in by_text.values()),
                      "met": sum(i["labels"][i["text"]]["C4"] == "met" for i in items),
                      "not_met_classes": dict(Counter(i["logic_label"] for i in items if i["logic_label"] != POSITIVE))},
                     indent=1))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
