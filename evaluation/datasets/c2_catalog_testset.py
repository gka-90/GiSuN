"""
C2 test set built from the catalog's own measures (QuanTemp has no claim the catalog can check).

For each (measure, place, period) below the official figure is fetched once with lookup_statistic,
and sentences are written around it whose C2 label is known by construction:

    exact         the official figure, rounded as a chatbot would write it        -> not_met
    wrong         20% off, no hedge                                               -> met
    approx_true   "about" a number 4% off (inside the 10% tolerance)              -> not_met
    approx_wrong  "about" a number 30% off                                        -> met
    floor_true    "more than" a number 10% below the official figure              -> not_met
    floor_wrong   "more than" a number 15% above the official figure              -> met

Every measure gets exact + wrong; the approx and floor pairs alternate. A case is dropped when the
sources disagree, the figure is too small to alter cleanly, or the tolerance rules (c2_outcome) don't
give the intended label. Needs the API keys (or a warm cache):

    python -m evaluation.datasets.c2_catalog_testset           # -> datasets/gold_c2_catalog.json
"""

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.getcwd())

from gisun.criteria import c2_outcome
from gisun.tools.numbers import hedge_of
from gisun.tools.retrieval import lookup_statistic

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
US = "the United States"
# (measure as the sentence says it, place, period, text after the number)
SPECS = [
    ("unemployment rate", US, "2019", ""), ("unemployment rate", US, "2020", ""),
    ("unemployment rate", US, "2022", ""), ("unemployment rate", US, "2020-04", ""),
    ("unemployment rate", US, "2009-10", ""), ("unemployment rate", US, "2023-01", ""),
    ("U-6 unemployment rate", US, "2019", ""), ("U-6 unemployment rate", US, "2020-04", ""),
    ("labor force participation rate", US, "2019", ""), ("labor force participation rate", US, "2020-04", ""),
    ("inflation rate", US, "2021", ""), ("inflation rate", US, "2022", ""), ("inflation rate", US, "2022-06", ""),
    ("core inflation rate", US, "2022", ""),
    ("average hourly earnings", US, "2023-01", ""), ("federal minimum wage", US, "2015", " an hour"),
    ("unemployment rate for college graduates", US, "2022", ""),
    ("foreign-born population", US, "2022", ""),
    ("health spending per capita", US, "2021", ""),
    ("teen birth rate", US, "2021", " births per 1,000 women aged 15 to 19"),
    ("road traffic death rate", US, "2019", " deaths per 100,000 people"),
    ("life expectancy", US, "2019", " years"), ("GDP per capita", US, "2019", ""),
    ("population", "California", "2020", ""), ("population", "Texas", "2020", ""),
    ("population", "Germany", "2020", ""), ("population", "Japan", "2019", ""),
    ("unemployment rate", "California", "2020", ""), ("obesity rate", "New York", "2021", ""),
    ("GDP per capita", "Germany", "2020", ""), ("GDP per capita", "Japan", "2019", ""),
    ("GDP growth", "India", "2021", ""), ("GDP growth", "Germany", "2021", ""),
    ("inflation rate", "Germany", "2022", ""), ("inflation rate", "Brazil", "2021", ""),
    ("unemployment rate", "Germany", "2019", ""), ("unemployment rate", "Spain", "2019", ""),
    ("life expectancy", "Japan", "2019", " years"), ("life expectancy", "Brazil", "2019", " years"),
    ("fertility rate", "France", "2019", " births per woman"), ("fertility rate", "India", "2019", " births per woman"),
    ("infant mortality rate", "India", "2019", " deaths per 1,000 live births"),
    ("access to electricity", "Nigeria", "2019", " of the population"),
    ("access to electricity", "India", "2015", " of the population"),
    ("renewable energy share", "Brazil", "2019", ""), ("renewable energy share", "Germany", "2019", ""),
    ("literacy rate", "India", "2018", ""),
]
VARIANTS = {"exact": (1.0, "", "not_met"), "wrong": (1.2, "", "met"),
            "approx_true": (1.04, "about ", "not_met"), "approx_wrong": (1.3, "about ", "met"),
            "floor_true": (0.9, "more than ", "not_met"), "floor_wrong": (1.15, "more than ", "met")}
HEDGE = {"": "none", "about ": "approx", "more than ": "at_least"}


def sig(v: float, n: int = 3) -> float:
    return float(f"{v:.{n}g}")


def fmt(v: float, unit: str, exact: bool) -> str:
    """The number as a chatbot would write it."""
    if unit == "percent":
        return f"{v:.1f}%"
    if unit == "usd" and v < 100:
        return f"${v:,.2f}"
    if v >= 1000:
        text = f"{round(v if exact else sig(v)):,}"
        return "$" + text if unit == "usd" else text
    return ("$" if unit == "usd" else "") + f"{v:.1f}"


def when(period: str) -> str:
    return f"{MONTHS[int(period[5:]) - 1]} {period[:4]}" if "-" in period else period


def build() -> tuple[list[dict], Counter]:
    items, why = [], Counter()
    for n, (measure, place, period, tail) in enumerate(SPECS):
        found = lookup_statistic(measure, place.removeprefix("the "), period)
        records = found.get("records") or []
        if not records:
            why[f"no record: {measure} / {place} / {period} ({found.get('skipped') or found.get('note')})"] += 1
            continue
        values, unit = [r["value"] for r in records], records[0]["unit"]
        v = values[0]
        if max(values) - min(values) > 0.005 * abs(v) or v < (1.0 if unit == "percent" else 0.5):
            why[f"sources disagree or figure too small: {measure} / {place} / {period} {values}"] += 1
            continue
        for name in ["exact", "wrong"] + (["approx_true", "approx_wrong"] if n % 2 == 0 else ["floor_true", "floor_wrong"]):
            factor, hedge, label = VARIANTS[name]
            value = fmt(v * factor, unit, name == "exact")
            sentence = f"In {when(period)}, the {measure} in {place} was {hedge}{value}{tail}."
            if hedge_of(sentence, value) != HEDGE[hedge] or c2_outcome(value, HEDGE[hedge], records)[0] != label:
                why[f"rules don't give the intended label ({name})"] += 1
                continue
            slug = f"{measure}-{place.removeprefix('the ')}-{period}".lower().replace(" ", "_")
            items.append({"id": f"c2cat-{slug}-{name}", "source": "catalog (built)", "question": "",
                          "text": sentence, "labels": {sentence: {"C2": label}}})
    return items, why


if __name__ == "__main__":
    items, why = build()
    with open("datasets/gold_c2_catalog.json", "w") as f:
        json.dump(items, f, indent=1, ensure_ascii=False)
    print(len(items), "items", dict(Counter(next(iter(i["labels"].values()))["C2"] for i in items)))
    print(dict(Counter(i["id"].rsplit("-", 1)[1] for i in items)))
    for k, n in why.items():
        print("dropped:", n, k)
