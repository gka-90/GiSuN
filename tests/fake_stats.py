"""
A stand-in for the statistics APIs, so the C2 tests run offline and give the same answer
every time. install(test) points the cache at a temp file and answers requests from FIGURES.
"""

import os
import tempfile
from unittest.mock import patch

from gisun import config
from gisun.tools import retrieval

COUNTRIES = [{"id": "USA", "name": "United States"}, {"id": "DEU", "name": "Germany"},
             {"id": "KOR", "name": "Korea, Rep."}]
# BLS series -> {(year, period): value}; M13 = annual average (only sent with a key). As in the real
# API, the seasonally adjusted LNS14000000 has no M13: annual averages are on LNU04000000.
BLS = {"LNS14000000": {(2020, "M04"): "14.8", (2020, "M01"): "3.5"},
       "LNU04000000": {(2020, "M04"): "14.4", (2020, "M13"): "8.1", (2019, "M13"): "3.7"},
       "CUUR0000SA0": {(2022, "M06"): "296.311", (2021, "M06"): "271.696",
                       (2022, "M13"): "292.655", (2021, "M13"): "270.970"}}
# World Bank (indicator, ISO3, year) -> value
WB = {("FP.CPI.TOTL.ZG", "USA", "2022"): 8.00279982052121, ("SP.POP.TOTL", "DEU", "2020"): 83160871,
      ("NY.GDP.PCAP.CD", "DEU", "2020"): 46772.8253}
CENSUS = {("2020", "dec/pl", "P1_001N", "us:1"): "331449281"}


def fake_request(url, payload=None, headers=None):
    if "api.bls.gov" in url:
        series = []
        for sid in payload["seriesid"]:
            years = range(int(payload["startyear"]), int(payload["endyear"]) + 1)
            data = [{"year": str(y), "period": p, "value": v} for (y, p), v in BLS.get(sid, {}).items()
                    if y in years and (p != "M13" or payload.get("annualaverage"))]
            series.append({"seriesID": sid, "data": data})
        return {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": series}}
    if "api.worldbank.org/v2/country?" in url:
        return [{"page": 1}, COUNTRIES]
    if "api.worldbank.org" in url:
        parts = url.split("/")
        iso3, ind, year = parts[5], parts[7].split("?")[0], url.split("date=")[1][:4]
        v = WB.get((ind, iso3, year))
        return [{"page": 1}, [{"value": v}] if v is not None else None]
    if "api.census.gov" in url:
        _, rest = url.split("/data/", 1)
        year, rest = rest.split("/", 1)
        dataset, query = rest.split("?", 1)
        var = query.split("get=NAME,")[1].split("&")[0]
        geo = query.split("for=")[1].split("&")[0]
        v = CENSUS.get((year, dataset, var, geo))
        return [["NAME", var, "us"]] + ([["United States", v, "1"]] if v else [])
    raise AssertionError(f"unexpected request {url}")


def install(test, bls_key="test-key", census_key="test-key"):
    """Patch the APIs for one test (undone automatically). Returns the request mock."""
    tmp = tempfile.mkdtemp()
    mock = patch.object(retrieval, "_request", side_effect=fake_request).start()
    for p in [patch.object(config, "STAT_CACHE_PATH", os.path.join(tmp, "cache.json")),
              patch.object(config, "STAT_OFFLINE", False), patch.object(config, "BLS_KEY", bls_key),
              patch.object(config, "CENSUS_KEY", census_key), patch.object(config, "DATACOMMONS_KEY", "")]:
        p.start()
    retrieval.reset_cache()
    test.addCleanup(patch.stopall)
    test.addCleanup(retrieval.reset_cache)
    return mock
