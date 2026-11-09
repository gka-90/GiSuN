"""
Confirm new C2 catalog entries against the live APIs before C2 may use them.

An entry in data/stat_series.json with "verified": false is skipped by C2. This script fetches
its "test" place and period once, prints what came back, and with --write marks the entry
verified when the value is inside its "test" range (a wrong series ID or Data Commons variable
returns nothing or an implausible number and stays off). Needs the API keys in .env and network
access, so run it on a laptop, not on an HPC node:

    python -m evaluation.check_series            # check the unverified entries, change nothing
    python -m evaluation.check_series --write    # ... and mark the ones that pass as verified
    python -m evaluation.check_series --all      # re-check every entry that has a "test"
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from gisun import config
from gisun.tools import retrieval


def check(entry: dict) -> tuple[bool, str]:
    test = entry.get("test")
    if not test:
        return False, "no 'test' place and period"
    place = retrieval.resolve_place(test["place"])
    if not place:
        return False, f"can't resolve {test['place']!r}"
    try:
        found, _ = retrieval.FETCH[entry["provider"]](entry, place, test["period"])
    except Exception as ex:
        return False, f"{type(ex).__name__}: {ex}"
    if not found:
        return False, "no value returned (wrong series ID or variable, or no data for that year)"
    lo, hi = test["range"]
    vals = [f["value"] for f in found]
    ok = any(lo <= v <= hi for v in vals)
    return ok, f"{', '.join(retrieval.format_value(v, entry['unit']) for v in vals)} (expected {lo} to {hi})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="mark entries that pass as verified")
    ap.add_argument("--all", action="store_true", help="also re-check entries already verified")
    a = ap.parse_args()
    entries = [e for e in retrieval.all_series() if a.all and e.get("test") or e.get("verified") is False]
    passed = []
    for e in entries:
        ok, msg = check(e)
        print(f"{'PASS' if ok else 'FAIL'}  {e['id']:32} {msg}")
        if ok and e.get("verified") is False:
            passed.append(e["id"])
    if a.write and passed:
        path = config.STAT_SERIES_PATH
        text = open(path, encoding="utf-8").read()
        for sid in passed:
            start = text.index(f'"id": "{sid}"')
            pos = text.index('"verified": false', start)
            text = text[:pos] + '"verified": true' + text[pos + len('"verified": false'):]
        json.loads(text)
        open(path, "w", encoding="utf-8").write(text)
        print(f"marked verified: {', '.join(passed)}")
    elif passed:
        print("rerun with --write to turn these on")


if __name__ == "__main__":
    main()
