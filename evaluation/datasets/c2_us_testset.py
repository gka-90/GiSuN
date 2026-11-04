"""
C2 test set: the QuanTemp claims (the C2 rows of datasets/gold_public_*.json) that our series
catalog (data/stat_series.json) can actually look up. On the full public set C2 made no flag on
67 QuanTemp claims, because almost none of them are about a measure the catalog has.

A claim is kept when the C2 rules' own step 1 (criteria.c2_fields_from_text) pins down a value,
a catalog measure, one place and one period from the text, the place is the United States or a
U.S. state, and some catalog series covers that place and frequency (retrieval.usable_series) in
the claim's unit (a percent for a rate, dollars for a wage: "$175 a month" is not a CPI rate).
Nothing is fetched: only the catalog is consulted (the place names come from the cache, and
the run is forced offline), so this needs no API key and makes no API call.

    python -m evaluation.datasets.c2_us_testset                # -> datasets/gold_c2_us.json
    python -m evaluation.datasets.c2_us_testset --show         # also print why each claim was dropped
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.getcwd())
from gisun import config
from gisun.criteria import _measure_in, c2_fields_from_text
from gisun.preprocess import match_claim, preprocess
from gisun.tools.numbers import parse_value
from gisun.tools.retrieval import resolve_place, usable_series

SOURCES = "datasets/gold_public_*.json"
OUT = "datasets/gold_c2_us.json"
US_KINDS = {"us", "us_state"}


def claim_unit(value: str) -> str | None:
    """The catalog unit a claimed value is in: percent, usd or number (None if it can't be read)."""
    parsed = parse_value(value)
    if parsed is None:
        return None
    return "percent" if parsed["unit"] == "percent" else "usd" if "$" in value else parsed["unit"]


def why_not(item: dict) -> tuple[str | None, dict]:
    """(None, info) if the item's C2 claim can be looked up, else (the first reason it can't, info)."""
    key = next(k for k, v in item["labels"].items() if "C2" in v)
    claim = match_claim(preprocess(item["text"], item.get("question", ""), all_sentences=True).claims, key)
    if claim is None:
        return "no_claim", {}
    if not claim["checkable_values"]:
        return "no_checkable_number", {}
    text = " ".join([claim["sentence"], *claim["context_before"], item.get("question", "")])
    if not _measure_in(text):
        return "measure_not_in_catalog", {}
    fields = c2_fields_from_text(claim, item.get("question", ""))
    if fields is None:
        return "place_or_period_not_stated", {"measure": _measure_in(text)}
    place = resolve_place(fields["place"])
    if not place or place["kind"] not in US_KINDS:
        return "not_us", fields
    series, _, _, note = usable_series(fields["measure"], fields["place"], fields["period"])
    if not series:
        return "no_series_for_place_or_frequency", {**fields, "note": note}
    series = [e for e in series if e["unit"] == claim_unit(fields["value"])]
    if not series:
        return "unit_mismatch", fields
    return None, {**fields, "series": [e["id"] for e in series]}


def build(paths: list[str]) -> tuple[list[dict], Counter, list[tuple[str, str, str]]]:
    kept, reasons, dropped = [], Counter(), []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for item in json.load(f):
                if not any("C2" in v for v in item["labels"].values()):
                    continue
                reason, info = why_not(item)
                reasons[reason or "kept"] += 1
                if reason:
                    dropped.append((item["id"], reason, item["text"][:100]))
                    continue
                labels = {k: {"C2": v["C2"]} for k, v in item["labels"].items() if "C2" in v}
                kept.append({"id": item["id"], "source": "QuanTemp (" + os.path.basename(path) + ")",
                             "question": item.get("question", ""), "text": item["text"], "labels": labels,
                             "c2_fields": info})
    return kept, reasons, dropped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", nargs="+", default=sorted(glob.glob(SOURCES)))
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--show", action="store_true", help="print each dropped claim and why")
    a = ap.parse_args()
    config.STAT_OFFLINE = True  # the catalog check needs no figures: never call an API from here
    kept, reasons, dropped = build(a.sources)
    if a.show:
        for row in dropped:
            print(" | ".join(row))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(kept, f, indent=1, ensure_ascii=False)
    labels = Counter(v["C2"] for it in kept for v in it["labels"].values())
    print(json.dumps({"c2_claims": sum(reasons.values()), "kept": len(kept), "labels": dict(labels),
                      "reasons": dict(reasons.most_common())}, indent=1))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
