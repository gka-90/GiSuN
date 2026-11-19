"""Citation check (gisun/tools/citations.py): links -> sentences, numbers on a page, the user-facing lines."""
import unittest

from gisun.tools.citations import (appears, attach_citations, check_claim, claim_numbers, html_to_text,
                                   number_check, numbers_on_page, provider_for)

TEXT = ("New York's unemployment rate was 4.3% in September 2026. "
        "About 431,800 people were unemployed. Prices rose quickly.")
SENTS = ["New York's unemployment rate was 4.3% in September 2026.",
         "About 431,800 people were unemployed.", "Prices rose quickly."]


def claim(sentence, values):
    return {"sentence": sentence, "checkable_values": values, "stat_values": values}


class TestLinks(unittest.TestCase):
    def test_provider(self):
        self.assertEqual(provider_for("https://www.bls.gov/eag/eag.ny.htm"), "bls")
        self.assertEqual(provider_for("https://fred.stlouisfed.org/series/UNRATE"), "fred")
        self.assertIsNone(provider_for("https://www.nytimes.com/x"))
        self.assertIsNone(provider_for("https://notbls.gov.example.com/"))

    def test_link_goes_to_the_sentence_it_ends(self):
        c1, c2 = claim(SENTS[0], ["4.3%"]), claim(SENTS[1], ["431,800"])
        cites = [{"url": "https://www.bls.gov/lau/", "offset": len(SENTS[0])}]
        unused = attach_citations([c1, c2], TEXT, SENTS, cites)
        self.assertEqual(c1["citations"], ["https://www.bls.gov/lau/"])
        self.assertEqual(c1["cited_providers"], ["bls"])
        self.assertEqual(c2["citations"], [])
        self.assertEqual(unused, [])

    def test_bad_links_are_ignored(self):
        c1 = claim(SENTS[0], ["4.3%"])
        attach_citations([c1], TEXT, SENTS, [{"url": "javascript:x", "offset": 3}, {"url": "https://a.org"}])
        self.assertEqual(c1["citations"], [])


class TestNumbers(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(claim_numbers("4.3%"), [(4.3, 1)])
        self.assertEqual(claim_numbers("431,800"), [(431800.0, 0)])
        self.assertEqual(claim_numbers("$2.3M"), [(2.3, 1)])

    def test_rounded_to_the_claims_precision(self):
        page = numbers_on_page("Rate: 4.27 percent; 431800 unemployed; table 12")
        self.assertTrue(appears((4.3, 1), page))
        self.assertTrue(appears((431800.0, 0), page))
        self.assertFalse(appears((4.4, 1), page))

    def test_html(self):
        self.assertIn("4.3", html_to_text("<html><script>var x=9.9</script><p>Rate&nbsp;4.3%</p></html>"))
        self.assertNotIn("9.9", html_to_text("<script>var x=9.9</script><p>ok</p>"))


class TestCheckClaim(unittest.TestCase):
    def fake(self, pages):
        return lambda url: pages[url]

    def test_found_not_found_unreachable_no_link(self):
        c = claim(SENTS[0], ["4.3%"])
        self.assertEqual(check_claim(c)["status"], "no_link")
        c["citations"] = ["https://a.gov"]
        self.assertEqual(check_claim(c, self.fake({"https://a.gov": {"ok": True, "text": "rate 4.3"}}))["status"], "found")
        r = check_claim(c, self.fake({"https://a.gov": {"ok": True, "text": "rate 5.1"}}))
        self.assertEqual((r["status"], r["missing"]), ("not_found", ["4.3%"]))
        self.assertEqual(check_claim(c, self.fake({"https://a.gov": {"ok": False, "reason": "403"}}))["status"], "unreachable")

    def test_no_number_no_check(self):
        self.assertIsNone(check_claim(claim(SENTS[2], [])))


class TestNumberCheck(unittest.TestCase):
    def out(self, status, c1, c2):
        crit = {}
        if c1: crit["C1"] = {"decision": c1}
        if c2: crit["C2"] = {"decision": c2}
        return {"citation_check": {"status": status}, "criteria": crit}

    def test_lines(self):
        self.assertEqual(number_check(self.out("found", "not_met", "not_met")),
                         {"source": "found", "scope": None, "official": "matches", "warn": False})
        self.assertEqual(number_check(self.out("no_link", "not_met", None))["source"], "named")
        self.assertEqual(number_check(self.out("no_link", "met", "undetermined"))["source"], "none")
        self.assertTrue(number_check(self.out("not_found", "not_met", "met"))["warn"])
        self.assertIsNone(number_check({"citation_check": None, "criteria": {}}))


if __name__ == "__main__":
    unittest.main()


class TestPreferCitedProvider(unittest.TestCase):
    def test_only_the_cited_provider_is_used(self):
        from unittest import mock
        from gisun.tools import retrieval as r
        series = [{"id": "a", "provider": "bls", "unit": "percent", "measure": "m", "variable": "X"},
                  {"id": "b", "provider": "worldbank", "unit": "percent", "measure": "m", "variable": "Y"}]
        where = {"name": "United States", "code": "USA"}
        fetch = {"bls": lambda e, w, p: ([{"value": 3.7}], "2026-11-19"),
                 "worldbank": lambda e, w, p: ([{"value": 3.9}], "2026-11-19")}
        with mock.patch.object(r, "usable_series", return_value=(series, where, "2019", "")), \
             mock.patch.dict(r.FETCH, fetch):
            both = r.lookup_statistic("m", "US", "2019")
            cited = r.lookup_statistic("m", "US", "2019", prefer=["bls"])
            other = r.lookup_statistic("m", "US", "2019", prefer=["cdc"])
        self.assertEqual(len(both["records"]), 2)
        self.assertEqual([x["value"] for x in cited["records"]], [3.7])
        self.assertIn("checked_against", cited)
        self.assertEqual(len(other["records"]), 2)   # the cited provider doesn't have this series


class TestUtf16Offsets(unittest.TestCase):
    def test_emoji_before_the_link(self):
        from gisun.api import _from_utf16
        # JavaScript counts the emoji as two units: '.' is at 4 there, at 3 in Python
        self.assertEqual(_from_utf16("a😀b. c", [{"url": "u", "offset": 4}])[0]["offset"], 3)


class TestAnswerSourceList(unittest.TestCase):
    def test_sentence_without_link_uses_the_answer_list(self):
        listed = "BLS — State Employment and Unemployment, September 2026."
        text = SENTS[0] + " " + SENTS[1] + " Sources: " + listed
        c1 = claim(SENTS[0], ["4.3%"])
        attach_citations([c1], text, SENTS[:2] + ["Sources:", listed],
                         [{"url": "https://www.bls.gov/news.release/laus.nr0.htm", "offset": text.index("BLS")}])
        self.assertEqual(c1["citations"], [])
        self.assertEqual(c1["answer_links"], ["https://www.bls.gov/news.release/laus.nr0.htm"])
        self.assertEqual(c1["cited_providers"], ["bls"])
        r = check_claim(c1, lambda url: {"ok": True, "text": "New York 4.3 percent"})
        self.assertEqual((r["status"], r["scope"]), ("found", "answer"))


class TestOneDownloadPerUrl(unittest.TestCase):
    def test_parallel_requests_share_one_download(self):
        import threading, time
        from unittest import mock
        from gisun.tools import citations as cit
        calls = []
        def slow(url):
            calls.append(url); time.sleep(0.2)
            out = {"ok": True, "text": "4.3"}
            with cit._lock:
                cit._cache[url] = out
            return out
        url = "https://example.gov/once"
        cit._cache.pop(url, None)
        with mock.patch.object(cit, "_download", side_effect=slow):
            ts = [threading.Thread(target=cit.fetch_text, args=(url,)) for _ in range(6)]
            [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(calls), 1)


class TestBrowserText(unittest.TestCase):
    def test_text_from_the_extension_is_used(self):
        from gisun.tools import citations as cit
        url = "https://www.bls.gov/eag/eag.ny.htm#prime-test"
        cit.prime([{"url": url, "offset": 0, "text": "New York 4.3 percent"}])
        self.assertEqual(cit.fetch_text(url)["via"], "browser")
        c = claim(SENTS[0], ["4.3%"]); c["citations"] = [url]
        self.assertEqual(check_claim(c)["status"], "found")

    def test_readable_reasons(self):
        from gisun.tools.citations import readable_reason
        self.assertIn("refused", readable_reason("HTTPError: HTTP Error 403: Forbidden"))
        self.assertIn("not found", readable_reason("HTTP 404"))
        self.assertIn("in time", readable_reason("TimeoutError: timed out"))


class TestListLeadIn(unittest.TestCase):
    def test_lead_in_covers_the_whole_list(self):
        from gisun.preprocess import _context_before
        s = ["New York State's unemployment rate was 4.3% in September 2026.",
             "According to the New York State Department of Labor:",
             "September 2026: 4.3%", "August 2026: 4.3%", "September 2025: 4.6%",
             "Number of unemployed residents: Approximately 431,800."]
        self.assertIn(s[1], _context_before(s, s[5]))
        self.assertNotIn(s[1], _context_before(s, s[0]))
        # a lead-in with no source, or a long sentence in between, covers nothing
        t = ["Additional figures:", "September 2026: 4.3%", "August 2026: 4.3%", "Rest of the state: 3.9%"]
        self.assertEqual(_context_before(t, t[3]), t[1:3])


class TestSingleAnswerSource(unittest.TestCase):
    def test_one_source_line_or_one_link(self):
        from gisun.tools.citations import single_answer_source
        s = ["The rate was 4.3%.", "Source: New York State Department of Labor - September 2026 report."]
        self.assertEqual(single_answer_source(s, []), s[1])
        self.assertEqual(single_answer_source(["The rate was 4.3%."], [{"url": "https://www.bls.gov/x", "offset": 3}]),
                         "Source: https://www.bls.gov/x")

    def test_several_sources_cover_every_number(self):
        from gisun.tools.citations import single_answer_source
        s = ["The rate was 4.3%.", "Sources:", "BLS - Table 1.", "FRED - NYUR."]
        links = [{"url": "https://www.bls.gov/a", "offset": 0}, {"url": "https://fred.stlouisfed.org/b", "offset": 1}]
        line = single_answer_source(s, links)
        self.assertIn("bls.gov", line)
        self.assertIn("fred.stlouisfed.org", line)
        two = ["The rate was 4.3%.", "Source: New York State Department of Labor.", "Source: Bureau of Labor Statistics."]
        self.assertEqual(single_answer_source(two, []),
                         "Source: New York State Department of Labor; Bureau of Labor Statistics")
        self.assertIsNone(single_answer_source(["The rate was 4.3%."], []))


class TestChips(unittest.TestCase):
    def test_chip_marks_the_sentence_before_it(self):
        from gisun.tools.attribution import find_attribution
        c1, c2 = claim(SENTS[0], ["4.3%"]), claim(SENTS[1], ["431,800"])
        attach_citations([c1, c2], TEXT, SENTS, [{"chip": "Department…", "offset": len(SENTS[0]) + 1}])
        self.assertEqual(c1["chips"], ["Department…"])
        self.assertEqual(c2["chips"], [])
        self.assertTrue(find_attribution("Source: Department… (a citation attached to this sentence)")["names_specific_source"])
        self.assertTrue(find_attribution("Source: St. Louis Fed (a citation attached to this sentence)")["names_specific_source"])


class TestDatesAreNotChecked(unittest.TestCase):
    def test_date_only_claim_has_nothing_to_check(self):
        from gisun.tools.citations import check_claim, is_date
        self.assertTrue(is_date("November 20, 2026"))
        self.assertTrue(is_date("2026"))
        self.assertFalse(is_date("4.3%"))
        claim = {"stat_values": ["November 20, 2026"], "citations": [{"url": "https://www.bls.gov/x"}]}
        self.assertIsNone(check_claim(claim, fetch=lambda u: self.fail("no page should be opened")))
