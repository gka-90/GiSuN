# Adding a C2 source

C2 compares a claim's number with an official figure. Which figures it can reach is decided by
`data/stat_series.json` (the catalog) and the fetchers in `gisun/tools/retrieval.py`. On the 50
Claude answers, about two thirds of numeric claims came out `no_series`: the catalog has no entry
for that measure. Two ways to widen it.

## Level 1: a new measure from a provider we already have (no code)

BLS, Census, World Bank and Data Commons are already wired up. Adding a measure is one JSON entry.

1. Find the series id on the provider's site (e.g. World Bank indicator `SL.UEM.TOTL.ZS`).
2. Add an entry to `data/stat_series.json`:

```json
{
  "id": "wb_labor_force",
  "measure": "labor force (total)",
  "provider": "worldbank",
  "series_id": "SL.TLF.TOTL.IN",
  "unit": "number",
  "scope": ["us", "country"],
  "frequency": ["annual"],
  "aliases": ["labor force", "labour force", "size of the labor force"],
  "excludes": ["participation", "rate"],
  "verified": false,
  "test": {"place": "united states", "period": "2022", "range": [160000000, 175000000]}
}
```

   - `aliases` are what the agent might call the measure; `matching_series` matches on them, so
     write the words a chatbot would use. `excludes` keeps a near neighbour out (the labor force
     is not the participation *rate*).
   - `unit` is `percent`, `usd` or `number`; it decides how the value is written and compared.
   - `scope`: `us`, `us_state`, `country`, `other`. `frequency`: `annual`, `monthly`.
3. Verify it by hand, then set `"verified": true`:

```bash
python -c "from gisun.tools.retrieval import lookup_statistic as l; print(l('labor force','United States','2022'))"
```

   Check the number against the provider's own page. C2 skips unverified entries, so this step is
   not optional.
4. `python -m pytest tests -q` (the catalog has schema tests), then commit.

## Level 2: a new provider (about 30 lines)

Worth it when a provider covers a whole area we are missing. Two candidates:

| Provider | Covers | Key |
|---|---|---|
| FRED (St. Louis Fed) | interest rates and most US economic series | free, instant |
| CDC (data.cdc.gov, Socrata) | vaccine effectiveness, obesity, overdose deaths | none for light use |

Steps, using FRED as the example:

1. Get a key at https://fredaccount.stlouisfed.org/apikeys and put it in `.env` as
   `GISUN_FRED_KEY=...` (`.env` is git-ignored; never commit a key).
2. `gisun/config.py`: `FRED_KEY = os.environ.get("GISUN_FRED_KEY", "")`, and add it to the
   docstring's list of environment variables.
3. `gisun/tools/retrieval.py`: add a fetcher next to `_worldbank`. It takes the catalog entry, the
   resolved place and the normalized period, and returns `(records, query_date)`, where each record
   is at least `{"value": float}`:

```python
def _fred(entry: dict, place: dict, period: str) -> tuple[list[dict], str]:
    if not config.FRED_KEY:
        raise LookupError("the FRED API needs GISUN_FRED_KEY (free)")
    start = period if len(period) > 4 else period + "-01-01"
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={entry['series_id']}"
           f"&file_type=json&observation_start={start}&observation_end={period[:4]}-12-31")
    data, qdate = _get("fred", url, secret={"api_key": config.FRED_KEY})
    vals = [float(o["value"]) for o in data["observations"] if o["value"] != "."]
    return ([{"value": sum(vals) / len(vals)}] if vals else []), qdate
```

   Always pass the key through `_get`'s `secret=`: `_get` caches by the request *without* the
   secret, so the key never reaches `data/stat_cache.json`.
4. Register it: add `"fred": _fred` to `FETCH`, `"fred"` to `ORDER` (the order sources are reported
   in) and to `PROVIDERS` (its display name, which becomes the `source` on each record).
5. Add catalog entries with `"provider": "fred"`, then verify each one as in level 1.
6. Add a case to `tests/fake_stats.py` so the C2 tests still run offline, and
   `python -m pytest tests -q`.

## Before adding anything, check these first

A claim can fail for reasons a new source will not fix. Run the report and read the `c2_status`
column: `python -m evaluation.c2_report`.

- `no_series` is the only code a new source helps with.
- `no_period`, `no_place`: the agent could not pin the claim down; that is a guidance problem.
- `not_comparable`: the measure was found but is the wrong kind (a multi-year change compared with
  one year's rate, a count compared with a percentage). A new source makes this worse, not better.

## The scalable alternative

The catalog is a hand-written list, so coverage grows one entry at a time while real chatbot answers
can be about anything. Data Commons has a `resolve` endpoint with `resolver=indicator` that finds a
variable from a plain-language description, which would replace the list with a search. It needs a
key and has not been tried here. Worth an experiment before adding a fourth or fifth hand-made
provider.
