"""
C2 (does a reliable source give a different figure?): tolerances, API routing, cache, and
the Check agent's rules. Offline: the APIs are answered by tests/fake_stats.py.
    python -m unittest tests.test_c2
"""

import json
import unittest
from unittest.mock import patch

from gisun import config
from gisun.agents.check import check_decision, normalize
from gisun.criteria import c2_fields_from_text, c2_outcome
from gisun.preprocess import preprocess
from gisun.tools import retrieval
from gisun.tools.numbers import compare_numbers, hedge_of
from gisun.tools.retrieval import lookup_statistic, normalize_period, resolve_place
from tests import fake_stats


class Tolerances(unittest.TestCase):
    def match(self, claim, official, hedge="none"):
        return compare_numbers(claim, official, hedge)["match"]

    def test_no_hedge_rounds_and_allows_one_unit_in_the_last_digit(self):
        self.assertTrue(self.match("14.7%", "14.7 percent"))
        self.assertTrue(self.match("14.7%", "14.8 percent"))  # BLS first said 14.7, then revised to 14.8
        self.assertTrue(self.match("14.7%", "14.84 percent"))  # rounds to 14.8: one unit off
        self.assertFalse(self.match("14.7%", "14.85 percent"))  # rounds to 14.9: two units off
        self.assertTrue(self.match("331 million", "331,449,281"))
        self.assertTrue(self.match("330 million", "331,449,281"))
        self.assertFalse(self.match("329 million", "331,449,281"))
        self.assertFalse(self.match("12%", "8.1 percent"))
        self.assertFalse(self.match("$9.50", "$7.25"))

    def test_about_is_within_ten_percent(self):
        self.assertTrue(self.match("15%", "14 percent", "approx"))
        self.assertFalse(self.match("15%", "13 percent", "approx"))
        self.assertTrue(self.match("about 15%", "14 percent"))  # the hedge can come with the value

    def test_over_and_under(self):
        self.assertTrue(self.match("300 million", "331,449,281", "at_least"))
        self.assertFalse(self.match("350 million", "331,449,281", "at_least"))
        self.assertTrue(self.match("5%", "4.2 percent", "at_most"))
        self.assertFalse(self.match("4%", "4.2 percent", "at_most"))

    def test_range(self):
        self.assertTrue(self.match("15-25%", "18.2 percent"))
        self.assertFalse(self.match("15-25%", "14.8 percent"))
        self.assertTrue(self.match("2 to 3 million", "2,500,000"))

    def test_units_must_agree(self):
        self.assertFalse(compare_numbers("3%", "3 percentage points")["comparable"])
        self.assertFalse(compare_numbers("3%", "3")["comparable"])

    def test_hedge_words(self):
        s = "About 14.7% were out of work, over 300 million live there, under 5% voted, no more than 3 million came."
        self.assertEqual([hedge_of(s, v) for v in ["14.7%", "300 million", "5%", "3 million"]],
                         ["approx", "at_least", "at_most", "at_most"])
        self.assertEqual(hedge_of("It hit 14.7% in April.", "14.7%"), "none")
        self.assertEqual(hedge_of("It hit 5% or more.", "5%"), "at_least")


class Lookup(unittest.TestCase):
    def setUp(self):
        self.requests = fake_stats.install(self)

    def test_routes_us_unemployment_to_bls(self):
        r = lookup_statistic("unemployment rate", "U.S.", "April 2020")
        self.assertEqual([(x["source"], x["series_id"], x["value"], x["period"]) for x in r["records"]],
                         [("U.S. Bureau of Labor Statistics", "LNS14000000", 14.8, "2020-04")])
        self.assertTrue(r["records"][0]["query_date"])

    def test_annual_bls_needs_a_key(self):
        with patch.object(config, "BLS_KEY", ""):
            r = lookup_statistic("unemployment rate", "United States", "2020")
        self.assertEqual(r["records"], [])
        self.assertIn("GISUN_BLS_KEY", r["skipped"][0]["reason"])

    def test_country_figures_come_from_the_world_bank(self):
        r = lookup_statistic("population", "Germany", "2020")
        self.assertEqual(r["records"][0]["series_id"], "SP.POP.TOTL")
        self.assertEqual(r["records"][0]["value_text"], "83,160,871")

    def test_us_population_comes_from_the_census(self):
        r = lookup_statistic("population", "United States", "2020")
        self.assertEqual([x["series_id"] for x in r["records"]], ["2020/dec/pl/P1_001N"])

    def test_cpi_inflation_is_the_12_month_change(self):
        r = lookup_statistic("inflation", "US", "2022-06")
        self.assertEqual(r["records"][0]["value"], 9.1)

    def test_two_sources_for_the_same_figure(self):
        r = lookup_statistic("inflation", "United States", "2022")  # BLS annual average + World Bank
        self.assertEqual([x["series_id"] for x in r["records"]], ["CUUR0000SA0", "FP.CPI.TOTL.ZG"])

    def test_federal_minimum_wage_is_a_static_entry(self):
        r = lookup_statistic("federal minimum wage", "United States", "2020")["records"][0]
        self.assertEqual((r["source"], r["value_text"], r["unit"]), ("U.S. Department of Labor", "$7.25", "usd"))
        self.assertEqual(self.requests.call_count, 0, "a static entry needs no API call")
        self.assertEqual(lookup_statistic("federal minimum wage", "US", "2009-07")["records"], [])  # $6.55 until 07-24
        self.assertEqual(len(lookup_statistic("federal minimum wage", "US", "2009-08")["records"]), 1)
        self.assertEqual(lookup_statistic("federal minimum wage", "California", "2020")["records"], [])

    def test_never_close_enough(self):
        self.assertIn("no official series", lookup_statistic("crime rate", "US", "2020")["note"])
        self.assertEqual(lookup_statistic("women's unemployment rate", "US", "2020-04")["records"], [])
        self.assertEqual(lookup_statistic("U-6 underemployment", "US", "2020-04")["records"], [])  # not U-3
        self.assertIn("monthly", lookup_statistic("population", "Germany", "2020-04")["note"])

    def test_cache_first(self):
        lookup_statistic("unemployment rate", "U.S.", "2020-04")
        n = self.requests.call_count
        lookup_statistic("unemployment rate", "U.S.", "2020-04")
        self.assertEqual(self.requests.call_count, n)
        with open(config.STAT_CACHE_PATH) as f:
            cached = f.read()
        self.assertNotIn("test-key", cached, "API keys must not be written to the cache")
        self.assertTrue(all(v["query_date"] for v in json.loads(cached)["responses"].values()))

    def test_offline_uses_only_the_cache(self):
        with patch.object(config, "STAT_OFFLINE", True):
            r = lookup_statistic("unemployment rate", "U.S.", "2020-04")
        self.assertEqual(r["records"], [])
        self.assertIn("OFFLINE", r["skipped"][0]["reason"])

    def test_daily_limit(self):
        with patch.dict(retrieval.DAILY_LIMITS, {"bls": lambda: 0}):
            r = lookup_statistic("unemployment rate", "U.S.", "2020-04")
        self.assertIn("daily", r["skipped"][0]["reason"])

    def test_periods_and_places(self):
        self.assertEqual([normalize_period(p) for p in ["2020", "April 2020", "Apr. 2020", "2020-4", "2019-2020"]],
                         ["2020", "2020-04", "2020-04", "2020-04", None])
        self.assertEqual(resolve_place("the U.S.")["kind"], "us")
        self.assertEqual(resolve_place("South Korea")["code"], "KOR")
        self.assertEqual(resolve_place("California")["code"], "06")


def record(value, rid="bls:LNS14000000:USA:2020", period="2020", source="BLS"):
    return {"record_id": rid, "source": source, "series_id": rid.split(":")[1], "place": "United States",
            "place_code": "USA", "period": period, "value": value, "unit": "percent",
            "value_text": f"{value} percent", "query_date": "2026-10-31"}


class CheckAgent(unittest.TestCase):
    TEXT = "In 2020, the U.S. unemployment rate averaged about 12%."
    FIELDS = {"value": "12%", "measure": "unemployment rate", "place": "U.S.", "period": "2020", "hedge": "approx"}

    def setUp(self):
        fake_stats.install(self)
        self.ctx = preprocess(self.TEXT)
        self.claim = self.ctx.claims[0]

    def check(self, decision, records, cite=None, fields=None, compared=True):
        self.ctx.record_official(records)
        log = [{"tool": "lookup_statistic", "args": {}, "output": {"records": records}}]
        if compared:
            log.append({"tool": "compare_numbers", "args": {},
                        "output": compare_numbers("12%", records[0]["value_text"], "approx")})
        cite = records if cite is None else cite
        return check_decision("C2", {"decision": decision, "strength": "strong",
                                     "reasoning": "The official figure is compared with the claim.",
                                     "claim_fields": fields or self.FIELDS,
                                     "evidence": [{"quote": r["value_text"], "source": r["record_id"]} for r in cite]},
                              self.claim, self.ctx, log)

    def test_a_correct_contradiction_passes(self):
        self.assertEqual(self.check("met", [record(8.1)]), [])

    def test_decision_must_follow_the_tolerance_rules(self):
        self.assertTrue(any("give 'met'" in p for p in self.check("not_met", [record(8.1)])))
        self.assertEqual(self.check("not_met", [record(11.5)]), [])  # within 10%

    def test_hedge_must_be_the_sentences(self):
        problems = self.check("met", [record(8.1)], fields={**self.FIELDS, "hedge": "none"})
        self.assertTrue(any("hedge 'approx'" in p for p in problems))

    def test_fields_must_come_from_the_text(self):
        self.assertTrue(any("doesn't name" in p for p in self.check("met", [record(8.1)], fields={**self.FIELDS, "place": "Germany"})))
        self.assertTrue(any("doesn't state 2020-04" in p
                            for p in self.check("met", [record(8.1, period="2020-04", rid="bls:LNS14000000:USA:2020-04")],
                                                fields={**self.FIELDS, "period": "2020-04"})))
        self.assertTrue(any("claim_fields" in p for p in self.check("met", [record(8.1)], fields={"value": "12%"})))

    def test_place_may_come_from_the_question(self):
        ctx = preprocess("In 2020 the unemployment rate averaged about 12%.", "What was the US unemployment rate?")
        self.ctx, self.claim = ctx, ctx.claims[0]
        self.assertEqual(self.check("met", [record(8.1)], fields={**self.FIELDS, "place": "US"}), [])

    def test_official_figure_must_be_cited_and_compared(self):
        self.assertTrue(any("official figure as evidence" in p for p in self.check("met", [record(8.1)], cite=[])))
        self.assertTrue(any("compare_numbers" in p for p in self.check("met", [record(8.1)], compared=False)))

    def test_disagreeing_sources_are_undetermined_and_both_listed(self):
        both = [record(11.5), record(8.1, rid="worldbank:SL.UEM.TOTL.ZS:USA:2020", source="World Bank")]
        self.assertTrue(any("give 'undetermined'" in p for p in self.check("met", both)))
        self.assertTrue(any("cite every official figure" in p for p in self.check("undetermined", both, cite=both[:1])))
        self.assertEqual(self.check("undetermined", both), [])
        self.assertEqual(c2_outcome("12%", "approx", both)[0], "undetermined")

    def test_saved_evidence_carries_the_fetched_record(self):
        self.ctx.record_official([record(8.1)])
        out = normalize("C2", {"decision": "met", "strength": "strong", "reasoning": "x", "claim_fields": self.FIELDS,
                               "evidence": [{"quote": "8.1 percent", "source": "bls:LNS14000000:USA:2020"}]}, self.ctx)
        self.assertEqual({k: out["evidence"][0]["official"][k] for k in ("source", "series_id", "period", "query_date")},
                         {"source": "BLS", "series_id": "LNS14000000", "period": "2020", "query_date": "2026-10-31"})


class RulesStepOne(unittest.TestCase):
    def setUp(self):
        fake_stats.install(self)

    def fields(self, text):
        return c2_fields_from_text(preprocess(text).claims[-1])

    def test_pins_the_number_down(self):
        self.assertEqual(self.fields("In April 2020, the U.S. unemployment rate rose to nearly 15%."),
                         {"value": "15%", "measure": "unemployment rate", "place": "United States",
                          "period": "2020-04", "hedge": "approx"})

    def test_place_and_time_may_come_from_the_previous_sentences(self):
        f = self.fields("Germany was hit hard in 2020. Its population was 83 million.")
        self.assertEqual((f["place"], f["period"]), ("Germany", "2020"))

    def test_the_users_question_counts_as_context(self):
        claim = preprocess("The rate averaged 12% that year.").claims[0]
        self.assertIsNone(c2_fields_from_text(claim))
        f = c2_fields_from_text(claim, "What was the US unemployment rate in 2020?")
        self.assertEqual((f["measure"], f["place"], f["period"]), ("unemployment rate", "United States", "2020"))
        # the claim's own words come first
        f = c2_fields_from_text(preprocess("Germany's population was 83 million in 2020.").claims[0],
                                "How many people live in the US in 2019?")
        self.assertEqual((f["place"], f["period"]), ("Germany", "2020"))

    def test_capital_us_is_a_place_but_us_is_not(self):
        self.assertEqual([p["code"] for p in retrieval.places_in("people who live in the US")], ["USA"])
        self.assertEqual(retrieval.places_in("tell us the rate"), [])

    def test_stops_when_something_is_missing(self):
        self.assertIsNone(self.fields("The unemployment rate rose to 15% in 2020."))  # no place
        self.assertIsNone(self.fields("The U.S. unemployment rate rose to 15%."))  # no time
        self.assertIsNone(self.fields("U.S. sales rose 15% in 2020."))  # no catalog measure


if __name__ == "__main__":
    unittest.main()
