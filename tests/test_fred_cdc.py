"""The FRED and CDC fetchers, offline (tests/fake_stats.py answers the requests)."""
import json
import unittest
from unittest.mock import patch

from gisun import config
from gisun.tools import retrieval
from tests import fake_stats

US = {"kind": "us", "name": "United States", "code": "USA"}
NY = {"kind": "us_state", "name": "New York", "code": "36"}


def entry(eid):
    return next(e for e in retrieval.all_series() if e["id"] == eid)


class Fred(unittest.TestCase):
    def setUp(self):
        self.mock = fake_stats.install(self)

    def test_annual_average_and_month(self):
        self.assertEqual(retrieval._fred(entry("fred_fed_funds"), US, "2023")[0], [{"value": 5.02}])
        self.assertEqual(retrieval._fred(entry("fred_fed_funds"), US, "2023-07")[0], [{"value": 5.12}])

    def test_missing_value_is_no_figure(self):
        self.assertEqual(retrieval._fred(entry("fred_fed_funds"), US, "2030")[0], [])

    def test_key_is_sent_but_never_cached(self):
        retrieval._fred(entry("fred_fed_funds"), US, "2023")
        self.assertIn("api_key=test-key", self.mock.call_args[0][0])
        self.assertNotIn("test-key", json.dumps(retrieval._cache()))

    def test_no_key_is_an_error_not_a_guess(self):
        with patch.object(config, "FRED_KEY", ""):
            with self.assertRaises(LookupError):
                retrieval._fred(entry("fred_fed_funds"), US, "2023")


class Cdc(unittest.TestCase):
    def setUp(self):
        self.mock = fake_stats.install(self)

    def test_state_and_national_rows(self):
        e = entry("cdc_adult_obesity_brfss")
        self.assertEqual(retrieval._cdc(e, NY, "2022")[0], [{"value": 30.1}])
        self.assertEqual(retrieval._cdc(e, US, "2022")[0], [{"value": 33.6}])

    def test_through_the_lookup_with_our_place_names(self):
        allv = [{**e, "verified": True} for e in retrieval.all_series()]
        with patch.object(retrieval, "all_series", return_value=allv):
            found = retrieval.lookup_statistic("adult obesity rate", "New York", "2022")
        self.assertEqual([(r["source"], r["value_text"]) for r in found["records"]],
                         [("Centers for Disease Control and Prevention (data.cdc.gov)", "30.1 percent")])

    def test_no_row_is_no_figure(self):
        self.assertEqual(retrieval._cdc(entry("cdc_adult_obesity_brfss"), NY, "1990")[0], [])

    def test_filters_matching_two_values_are_refused(self):
        ohio = {"kind": "us_state", "name": "Ohio", "code": "39"}
        with self.assertRaises(LookupError):
            retrieval._cdc(entry("cdc_adult_obesity_brfss"), ohio, "2021")

    def test_token_goes_in_the_header_not_the_cache(self):
        retrieval._cdc(entry("cdc_adult_obesity_brfss"), NY, "2022")
        self.assertEqual(self.mock.call_args[0][2], {"X-App-Token": "test-token"})
        self.assertNotIn("test-token", json.dumps(retrieval._cache()))


class NewEntriesStayOff(unittest.TestCase):
    def test_unverified_entries_do_not_answer_claims(self):
        fake_stats.install(self)
        self.assertEqual(retrieval.lookup_statistic("federal funds rate", "United States", "2023")["records"], [])
        ids = {e["id"] for e in retrieval.matching_series("obesity rate")}
        self.assertNotIn("cdc_adult_obesity_brfss", ids)


if __name__ == "__main__":
    unittest.main()
