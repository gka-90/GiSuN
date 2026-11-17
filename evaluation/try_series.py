"""
Fetch a catalog entry's test figure, verified or not, and say whether it is inside the entry's
plausible range. The last step before setting "verified": true on a new entry by hand.

    python -m evaluation.try_series fred_fed_funds cdc_adult_obesity_brfss
    python -m evaluation.try_series            # every entry that is still unverified
"""

import sys

from gisun.tools import retrieval


def try_entry(entry: dict) -> str:
    test = entry["test"]
    place, period = retrieval.resolve_place(test["place"]), retrieval.normalize_period(test["period"])
    try:
        found, _ = retrieval.FETCH[entry["provider"]](entry, place, period)
    except Exception as ex:  # a wrong ID, a missing key and a network error all end up here
        return f"ERROR  {type(ex).__name__}: {ex}"
    if not found:
        return "EMPTY  the request worked but returned no figure"
    low, high = test["range"]
    values = [f["value"] for f in found]
    ok = all(low <= v <= high for v in values)
    return f"{'OK   ' if ok else 'RANGE'}  {values} (expected {low} to {high}, {test['place']} {test['period']})"


if __name__ == "__main__":
    wanted = sys.argv[1:]
    entries = [e for e in retrieval.all_series()
               if (e["id"] in wanted if wanted else e.get("verified") is False)]
    for e in entries:
        print(f"{e['id']:28} {try_entry(e)}")
    if not entries:
        print("no such entry" if wanted else "nothing left to verify")
