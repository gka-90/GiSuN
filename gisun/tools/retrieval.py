"""
Official statistics for C2 (step 2 of the C2 instructions).

lookup_statistic(measure, place, period) picks the API that fits the claim, checks the
cache first, and returns only figures for exactly that measure, place and period:

    BLS          US jobs and inflation        GISUN_BLS_KEY optional (annual averages need it)
    Census       US population and income     GISUN_CENSUS_KEY required
    World Bank   country-level figures        no key
    Data Commons everything else              GISUN_DATACOMMONS_KEY required

Which series answers which measure is listed in data/stat_series.json. A measure with no
entry there gets no figure (C2 is then "undetermined"): we never compare against a
close-enough series.

Cache: every API response is saved in data/stat_cache.json with the date it was fetched
(the same figures come up again and again in our dataset, and BLS and Census allow ~500
queries a day). GISUN_STAT_OFFLINE=1 uses the cache only (e.g. on HPC nodes with no internet).
"""

import json
import os
import re
import threading
import urllib.parse
import urllib.request
from datetime import date
from functools import lru_cache

from gisun import config

PROVIDERS = {"static": "", "bls": "U.S. Bureau of Labor Statistics", "census": "U.S. Census Bureau",
             "worldbank": "World Bank (World Development Indicators)", "datacommons": "Data Commons"}
# static entries (a fixed legal value, no API) first, then BLS / Census for the US, World Bank, Data Commons
ORDER = list(PROVIDERS)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]

# ---- places -------------------------------------------------------------------------------

US_ALIASES = ["united states", "united states of america", "u.s.", "u.s.a.", "us", "usa", "america", "american",
              "americans"]
US_STATES = {
    "alabama": "01", "alaska": "02", "arizona": "04", "arkansas": "05", "california": "06", "colorado": "08",
    "connecticut": "09", "delaware": "10", "district of columbia": "11", "florida": "12", "georgia": "13",
    "hawaii": "15", "idaho": "16", "illinois": "17", "indiana": "18", "iowa": "19", "kansas": "20",
    "kentucky": "21", "louisiana": "22", "maine": "23", "maryland": "24", "massachusetts": "25", "michigan": "26",
    "minnesota": "27", "mississippi": "28", "missouri": "29", "montana": "30", "nebraska": "31", "nevada": "32",
    "new hampshire": "33", "new jersey": "34", "new mexico": "35", "new york state": "36", "north carolina": "37",
    "north dakota": "38", "ohio": "39", "oklahoma": "40", "oregon": "41", "pennsylvania": "42",
    "rhode island": "44", "south carolina": "45", "south dakota": "46", "tennessee": "47", "texas": "48",
    "utah": "49", "vermont": "50", "virginia": "51", "washington state": "53", "west virginia": "54",
    "wisconsin": "55", "wyoming": "56"}
# Everyday names the World Bank list spells differently ("Korea, Rep.", "Turkiye")
COUNTRY_ALIASES = {
    "uk": "GBR", "u.k.": "GBR", "britain": "GBR", "great britain": "GBR", "united kingdom": "GBR",
    "south korea": "KOR", "korea": "KOR", "north korea": "PRK", "russia": "RUS", "iran": "IRN", "egypt": "EGY",
    "turkey": "TUR", "vietnam": "VNM", "venezuela": "VEN", "syria": "SYR", "yemen": "YEM", "laos": "LAO",
    "czech republic": "CZE", "czechia": "CZE", "slovakia": "SVK", "kyrgyzstan": "KGZ", "hong kong": "HKG",
    "macau": "MAC", "gambia": "GMB", "the gambia": "GMB", "bahamas": "BHS", "the bahamas": "BHS",
    "ivory coast": "CIV", "cote d'ivoire": "CIV", "dr congo": "COD", "democratic republic of the congo": "COD",
    "republic of the congo": "COG", "micronesia": "FSM", "st. lucia": "LCA", "saint lucia": "LCA",
    "eu": "EUU", "european union": "EUU", "the world": "WLD", "world": "WLD", "globally": "WLD", "global": "WLD",
    "worldwide": "WLD"}


def _norm(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").lower().strip().strip(",;:")).removeprefix("the ")
    return t if re.search(r"\.[a-z]\.$", t) else t.rstrip(".")  # keep the dot of "u.s." but not of "Germany."


def mentions(text: str, alias: str) -> bool:
    """Is the alias in the text as whole words? ('us' must not match 'business')."""
    if alias.lower() == "us":  # only "US", not the pronoun
        return re.search(r"(?<![A-Za-z])US(?![A-Za-z])", text or "") is not None
    return re.search(r"(?<![a-z])" + re.escape(alias.lower()) + r"(?![a-z])", (text or "").lower()) is not None


@lru_cache(maxsize=1)
def _wb_countries() -> dict:
    """World Bank economy name -> ISO3 code (cached like every other API call)."""
    data = _get("worldbank", "https://api.worldbank.org/v2/country?format=json&per_page=400",
                keep=lambda r: [r[0], [{"id": c["id"], "name": c["name"]} for c in r[1]]] if len(r) > 1 else r)[0]
    return {_norm(c["name"]): c["id"] for c in (data[1] if isinstance(data, list) and len(data) > 1 else [])}


def _country_names() -> dict:
    try:
        names = dict(_wb_countries())
    except Exception:  # offline and not cached: the aliases still work
        names = {}
    names.update(COUNTRY_ALIASES)
    return names


def resolve_place(place: str) -> dict | None:
    """'the U.S.' -> {kind: us, ...}; 'California' -> us_state; 'Germany' -> country;
    anything else -> other (Data Commons resolves it, if there is a key). None = can't tell."""
    p = _norm(place)
    if not p:
        return None
    if p in US_ALIASES or p + "." in US_ALIASES:
        return {"kind": "us", "name": "United States", "code": "USA", "dcid": "country/USA",
                "aliases": US_ALIASES}
    state = p.removesuffix(" state")
    for name, fips in US_STATES.items():
        if state == name.removesuffix(" state"):
            return {"kind": "us_state", "name": name.title(), "code": fips, "dcid": f"geoId/{fips}",
                    "aliases": sorted({name, name.removesuffix(" state")})}
    names = _country_names()
    if p in names:
        iso3 = names[p]
        return {"kind": "country", "name": place.strip().rstrip(".") if place.strip()[:1].isupper() else place.strip().rstrip(".").title(), "code": iso3, "dcid": f"country/{iso3}",
                "aliases": sorted({n for n, c in names.items() if c == iso3} | {p})}
    if config.DATACOMMONS_KEY:
        try:
            dcid = _dc_resolve(place)
        except Exception:
            dcid = None
        if dcid:
            return {"kind": "other", "name": place.strip(), "code": dcid, "dcid": dcid, "aliases": [p]}
    return None


def places_in(text: str) -> list[dict]:
    """Places named in a text, for the rules (longest name first: 'west virginia' before 'virginia')."""
    found, taken = [], []
    candidates = [(a, "us") for a in US_ALIASES if a != "us"] + \
                 [(n.removesuffix(" state"), "state") for n in US_STATES] + [(n, "country") for n in _country_names()]
    for alias, _ in sorted(candidates, key=lambda x: -len(x[0])):
        for m in re.finditer(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", (text or "").lower()):
            if any(a <= m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            if (r := resolve_place(alias)) and r["code"] not in {f["code"] for f in found}:
                found.append(r)
    if mentions(text, "us") and "USA" not in {f["code"] for f in found}:  # capital "US" only, not the pronoun
        found.append(resolve_place("united states"))
    return found


# ---- periods ------------------------------------------------------------------------------

def normalize_period(period: str) -> str | None:
    """'2020' -> '2020'; 'April 2020' / 'Apr. 2020' / '2020-04' -> '2020-04'; anything else -> None."""
    p = (period or "").strip().lower()
    if m := re.fullmatch(r"((?:19|20)\d{2})-(\d{1,2})", p):
        return f"{m.group(1)}-{int(m.group(2)):02d}" if 1 <= int(m.group(2)) <= 12 else None
    years = re.findall(r"\b(?:19|20)\d{2}\b", p)
    if len(years) != 1:
        return None
    month = next((i for i, name in enumerate(MONTHS, 1) if re.search(rf"\b{name[:3]}", p)), None)
    return f"{years[0]}-{month:02d}" if month else years[0]


def periods_in(text: str) -> list[str]:
    """Periods a text is about, for the rules: 'April 2020' -> 2020-04, a bare year -> 2020."""
    t, out = (text or "").lower(), []
    for m in re.finditer(r"\b(?:(" + "|".join(MONTHS) + r")\.?,?\s+(?:of\s+)?)?((?:19|20)\d{2})\b", t):
        out.append(f"{m.group(2)}-{MONTHS.index(m.group(1)) + 1:02d}" if m.group(1) else m.group(2))
    return sorted(set(out))


PRESENT_TENSE = re.compile(r"\b(is|are|stands at|remains|currently|now|today)\b", re.I)


def implied_period(sentence: str, today=None) -> str | None:
    """A present-tense claim with no stated time ('The federal minimum wage is $9.50') is about now:
    compare it with the latest full year. None if the sentence isn't in the present tense."""
    import datetime
    if periods_in(sentence) or not PRESENT_TENSE.search(sentence or ""):
        return None
    return str((today or datetime.date.today()).year - 1)


def implied_places(text: str) -> list[dict]:
    """'federal' (federal minimum wage, the federal poverty line) means the United States, when no
    other place is named."""
    if re.search(r"\bfederal\b", text or "", re.I):
        return [resolve_place("united states")]
    return []


def period_in_text(period: str, text: str) -> bool:
    """Is the period stated in the text (the year, and for a month the month name too)?"""
    year, t = period[:4], (text or "").lower()
    if not re.search(rf"\b{year}\b", t):
        return False
    return len(period) == 4 or re.search(rf"\b{MONTHS[int(period[5:]) - 1][:3]}", t) is not None


# ---- cache, quota and HTTP ----------------------------------------------------------------

_lock = threading.Lock()
_cache_data: dict | None = None
DAILY_LIMITS = {"bls": lambda: 500 if config.BLS_KEY else 25, "census": lambda: 500}


def _cache() -> dict:
    global _cache_data
    if _cache_data is None:
        try:
            with open(config.STAT_CACHE_PATH, encoding="utf-8") as f:
                _cache_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _cache_data = {}
        _cache_data.setdefault("responses", {})
        _cache_data.setdefault("usage", {})
    return _cache_data


def reset_cache():
    """Forget the in-memory cache (tests, or after changing GISUN_STAT_CACHE)."""
    global _cache_data
    with _lock:
        _cache_data = None
    _wb_countries.cache_clear()


def _save():
    path = config.STAT_CACHE_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(_cache_data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)


def _request(url: str, payload: dict | None = None, headers: dict | None = None):
    """One HTTP call (patched in the tests)."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    for attempt in (1, 2):  # the World Bank API times out now and then
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if "missing_key" in resp.geturl():
                    raise PermissionError("the API wants a key")
                return json.loads(resp.read())
        except TimeoutError:
            if attempt == 2:
                raise


def _get(provider: str, url: str, payload: dict | None = None, secret: dict | None = None,
         headers: dict | None = None, valid=lambda r: True, keep=lambda r: r) -> tuple:
    """(response, query_date). Cached by the request without its API key, so a key never
    lands in the cache file. secret = query or payload fields that carry the key. A response
    that fails `valid` is not cached (a refused or rate-limited request must be retried);
    `keep` trims what is saved."""
    key = provider + " " + url + (" " + json.dumps(payload, sort_keys=True) if payload else "")
    with _lock:
        hit = _cache()["responses"].get(key)
    if hit:
        return hit["response"], hit["query_date"]
    if config.STAT_OFFLINE:
        raise LookupError("not in the cache and GISUN_STAT_OFFLINE=1")
    today = date.today().isoformat()
    with _lock:
        used = _cache()["usage"].setdefault(provider, {})
        if provider in DAILY_LIMITS and used.get(today, 0) >= DAILY_LIMITS[provider]():
            raise LookupError(f"daily {provider} query limit reached; try again tomorrow")
        used[today] = used.get(today, 0) + 1
        for day in [d for d in used if d != today]:
            del used[day]
    full_url, full_payload = url, payload
    if secret and payload is not None:
        full_payload = {**payload, **secret}
    elif secret:
        full_url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(secret)
    response = _request(full_url, full_payload, headers)
    if not valid(response):
        raise LookupError(f"{provider} refused the request: {json.dumps(response)[:200]}")
    response = keep(response)
    with _lock:
        _cache()["responses"][key] = {"query_date": today, "response": response}
        _save()
    return response, today


# ---- providers: each returns a list of {value, note?} for one entry, place and period ------

def series_id_for(entry: dict, period: str) -> str | None:
    """BLS publishes annual averages only on the not seasonally adjusted series, so an entry
    whose monthly series is seasonally adjusted names that one as annual_series_id."""
    if len(period) == 4 and entry.get("annual_series_id"):
        return entry["annual_series_id"]
    return entry.get("series_id")


def _bls(entry: dict, place: dict, period: str) -> tuple[list[dict], str]:
    year, monthly = int(period[:4]), len(period) > 4
    if not monthly and not config.BLS_KEY:
        raise LookupError("BLS annual averages need GISUN_BLS_KEY (free registration)")
    pct = entry.get("calc") == "pct_change_12m"
    payload = {"seriesid": [series_id_for(entry, period)], "startyear": str(year - 1 if pct else year), "endyear": str(year)}
    if config.BLS_KEY:
        payload["annualaverage"] = True
    data, qdate = _get("bls", "https://api.bls.gov/publicAPI/v2/timeseries/data/", payload,
                       secret={"registrationkey": config.BLS_KEY} if config.BLS_KEY else None,
                       valid=lambda r: r.get("status") == "REQUEST_SUCCEEDED")
    obs = {(int(o["year"]), o["period"]): o["value"] for s in data["Results"]["series"] for o in s["data"]}
    code = f"M{period[5:]}" if monthly else "M13"

    def value(y):
        try:
            return float(obs[(y, code)])
        except (KeyError, ValueError):  # missing, or "-" for a month BLS skipped
            return None
    now = value(year)
    if now is None:
        return [], qdate
    if pct:
        before = value(year - 1)
        if not before:
            return [], qdate
        return [{"value": round((now / before - 1) * 100, 1),
                 "note": f"index {now} vs {before} a year earlier"}], qdate
    return [{"value": now}], qdate


def _census(entry: dict, place: dict, period: str) -> tuple[list[dict], str]:
    year = period[:4]
    if entry.get("years") and year not in entry["years"] or year in entry.get("skip_years", []):
        return [], ""
    if not config.CENSUS_KEY:
        raise LookupError("the Census API needs GISUN_CENSUS_KEY (free)")
    geo = "us:1" if place["kind"] == "us" else f"state:{place['code']}"
    url = f"https://api.census.gov/data/{year}/{entry['dataset']}?get=NAME,{entry['variable']}&for={geo}"
    rows, qdate = _get("census", url, secret={"key": config.CENSUS_KEY})
    header, *body = rows
    vals = [float(r[header.index(entry["variable"])]) for r in body if r[header.index(entry["variable"])] not in (None, "")]
    return [{"value": v} for v in vals[:1]], qdate


def _worldbank(entry: dict, place: dict, period: str) -> tuple[list[dict], str]:
    url = (f"https://api.worldbank.org/v2/country/{place['code']}/indicator/{entry['series_id']}"
           f"?format=json&date={period[:4]}")
    data, qdate = _get("worldbank", url)
    if not isinstance(data, list) or len(data) < 2 or not data[1]:
        msg = data[0].get("message") if isinstance(data, list) and data and isinstance(data[0], dict) else None
        if msg:
            raise LookupError(str(msg))
        return [], qdate
    return [{"value": float(r["value"])} for r in data[1] if r.get("value") is not None][:1], qdate


def _dc_resolve(place: str) -> str | None:
    url = "https://api.datacommons.org/v2/resolve?" + urllib.parse.urlencode(
        {"nodes": place, "property": "<-description->dcid"})
    data, _ = _get("datacommons", url, secret={"key": config.DATACOMMONS_KEY})
    for ent in data.get("entities", []):
        for cand in ent.get("candidates", []):
            return cand.get("dcid")
    return None


def _datacommons(entry: dict, place: dict, period: str) -> tuple[list[dict], str]:
    """Data Commons keeps several sources ("facets") per figure. Each one that has this exact
    date and observation period comes back, so two disagreeing sources are both seen."""
    if not config.DATACOMMONS_KEY:
        raise LookupError("Data Commons needs GISUN_DATACOMMONS_KEY (free)")
    url = "https://api.datacommons.org/v2/observation?" + urllib.parse.urlencode(
        [("date", period), ("variable.dcids", entry["variable"]), ("entity.dcids", place["dcid"]),
         ("select", "entity"), ("select", "variable"), ("select", "value"), ("select", "date")])
    data, qdate = _get("datacommons", url, secret={"key": config.DATACOMMONS_KEY})
    facets = data.get("facets", {})
    by_entity = data.get("byVariable", {}).get(entry["variable"], {}).get("byEntity", {}).get(place["dcid"], {})
    want = "P1M" if len(period) > 4 else "P1Y"
    out = []
    for f in by_entity.get("orderedFacets", []):
        info = facets.get(f.get("facetId"), {})
        # scalingFactor 100 on a percent figure means "already in percent" (CDC PLACES gives 29.7, not 0.297)
        ok_scale = (None, "1", 1) + (("100", 100) if entry.get("unit") == "percent" else ())
        if info.get("observationPeriod") not in (None, want) or info.get("scalingFactor") not in ok_scale:
            continue
        for o in f.get("observations", []):
            if o.get("date") == period and o.get("value") is not None:
                out.append({"value": float(o["value"]), "source": f"Data Commons: {info.get('importName', 'unknown')}",
                            "note": info.get("provenanceUrl", "")})
    return out[:3], qdate


def _static(entry: dict, place: dict, period: str) -> tuple[list[dict], str]:
    """A fixed value written into the catalog (e.g. a legal rate), valid from a date until changed.
    It only answers periods that start on or after that date; query_date = when it was last checked."""
    start = period + ("-01-01" if len(period) == 4 else "-01")
    return ([{"value": float(entry["value"])}] if start >= entry["valid_from"] else []), entry["checked"]


FETCH = {"static": _static, "bls": _bls, "census": _census, "worldbank": _worldbank, "datacommons": _datacommons}


# ---- catalog and lookup -------------------------------------------------------------------

@lru_cache(maxsize=1)
def all_series() -> list[dict]:
    """Every catalog entry, including new ones not yet confirmed."""
    with open(config.STAT_SERIES_PATH, encoding="utf-8") as f:
        return json.load(f)["series"]


def catalog() -> list[dict]:
    """The entries C2 may use: an entry marked "verified": false stays off until someone has
    fetched a plausible value for it and marked it verified, so a guessed series ID can never judge a claim."""
    return [e for e in all_series() if e.get("verified", True)]


def _says(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"s?(?![a-z0-9])", (text or "").lower()) is not None


def matching_series(measure: str) -> list[dict]:
    """Catalog entries for this measure: an alias is in it and no exclude is."""
    return [e for e in catalog()
            if any(_says(measure, a) for a in e["aliases"]) and not any(_says(measure, x) for x in e["excludes"])]


def _fits(entry: dict, place: dict) -> bool:
    return place["kind"] in entry["scope"] and place["code"] not in entry.get("exclude", [])


def format_value(value: float, unit: str) -> str:
    decimals = 0 if value == int(value) else len(repr(value).split(".")[1]) if "e" not in repr(value) else 2
    text = f"{value:,.{decimals}f}"
    return {"percent": f"{text} percent", "usd": f"${text}"}.get(unit, text)


def usable_series(measure: str, place: str, period: str) -> tuple[list[dict], dict | None, str | None, str]:
    """Which catalog entries could answer this measure, place and period, without fetching anything:
    (entries, resolved place, normalized period, note). entries is empty when nothing can (note says why)."""
    p, where = normalize_period(period), resolve_place(place)
    if not p:
        return [], where, p, f"period {period!r} must be a year (2020) or a month (2020-04)."
    if not where:
        return [], where, p, f"can't resolve the place {place!r}."
    entries = matching_series(measure)
    if not entries:
        known = sorted({a for e in catalog() for a in e["aliases"][:1]})
        return [], where, p, (f"no official series for {measure!r} in the catalog, so C2 can't be "
                              f"checked. Measures it knows: {', '.join(known)}.")
    freq = "monthly" if len(p) > 4 else "annual"
    usable = [e for e in entries if _fits(e, where) and freq in e["frequency"]]
    if not usable:
        return [], where, p, f"no series for {measure!r} covers {where['name']} with {freq} figures."
    return usable, where, p, ""


def lookup_statistic(measure: str, place: str, period: str) -> dict:
    """Official figures for exactly this measure, place and period (one per source)."""
    usable, where, p, note = usable_series(measure, place, period)
    if not usable:
        return {"records": [], "note": note}
    records, skipped = [], []
    for e in sorted(usable, key=lambda e: ORDER.index(e["provider"])):
        try:
            found, qdate = FETCH[e["provider"]](e, where, p)
        except Exception as ex:
            skipped.append({"series": e["id"], "reason": f"{type(ex).__name__}: {ex}"})
            continue
        for f in found:
            sid = series_id_for(e, p) or e.get("variable") or f"{e['dataset']}/{e['variable']}"
            if e["provider"] == "census":
                sid = f"{p[:4]}/{e['dataset']}/{e['variable']}"
            records.append({
                "record_id": f"{e['provider']}:{sid}:{where['code']}:{p}" + (f":{len(records)}" if e["provider"] == "datacommons" else ""),
                "source": f.get("source") or e.get("source") or PROVIDERS[e["provider"]], "series_id": sid, "measure": e["measure"],
                "place": where["name"], "place_code": where["code"], "period": p, "value": f["value"], "unit": e["unit"],
                "value_text": format_value(f["value"], e["unit"]), "query_date": qdate,
                **({"note": n} if (n := " ".join(x for x in (e.get("note"), f.get("note")) if x)) else {})})
    out = {"measure": measure, "place": where["name"], "period": p, "records": records}
    if skipped:
        out["skipped"] = skipped
    if not records:
        out["note"] = "no official figure for exactly this measure, place and period."
    return out
