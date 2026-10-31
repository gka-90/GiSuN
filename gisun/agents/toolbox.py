"""Tools the task agent can be given, bound to one claim and the run context."""

from gisun.agents.loop import Tool
from gisun.tools.attribution import find_attribution
from gisun.tools.language import context_cues, wordlist_lookup
from gisun.tools.numbers import HEDGES, compare_numbers
from gisun.tools.retrieval import lookup_statistic

NO_ARGS = {"type": "object", "properties": {}}


def build_tools(names: list[str], claim: dict, ctx) -> list[Tool]:
    def t_find_attribution(where: str = "sentence"):
        if where == "previous":
            return [{"sentence": s, **find_attribution(s)} for s in claim["context_before"]]
        return find_attribution(claim["sentence"])

    def t_context_window():
        return {"previous_sentences": claim["context_before"], "sentence": claim["sentence"]}

    def t_context_cues(term: str):
        return context_cues(claim["sentence"], term)

    def t_lookup_statistic(measure: str, place: str, period: str):
        found = lookup_statistic(measure, place, period)
        ctx.record_official(found["records"])
        return found

    def t_compare_numbers(claim_value: str, official_value: str, hedge: str = "none"):
        return compare_numbers(claim_value, official_value, hedge)

    catalog = {
        "find_attribution": Tool("find_attribution", "Does the claim sentence (where='sentence') or the previous "
                                 "sentences (where='previous') name a specific source?",
                                 {"type": "object", "properties": {"where": {"type": "string",
                                  "enum": ["sentence", "previous"]}}}, t_find_attribution),
        "context_window": Tool("context_window", "Show the two sentences before the claim.", NO_ARGS, t_context_window),
        "context_cues": Tool("context_cues", "Is a term negated, quoted, or only mentioned in the claim sentence?",
                             {"type": "object", "required": ["term"], "properties": {"term": {"type": "string"}}},
                             t_context_cues),
        "wordlist_lookup": Tool("wordlist_lookup", "Is a term in the curated loaded-language word list?",
                                {"type": "object", "required": ["term"], "properties": {"term": {"type": "string"}}},
                                lambda term: wordlist_lookup(term)),
        "lookup_statistic": Tool(
            "lookup_statistic", "Official figures (BLS, Census, World Bank, Data Commons) for exactly this measure, "
            "place and period. Returns records with record_id, source, series_id, value_text, unit, period and "
            "query_date, or none if no official series matches exactly.",
            {"type": "object", "required": ["measure", "place", "period"], "properties": {
                "measure": {"type": "string", "description": "what is measured, e.g. 'unemployment rate'"},
                "place": {"type": "string", "description": "e.g. 'United States', 'California', 'Germany'"},
                "period": {"type": "string", "description": "a year '2020' or a month '2020-04'"}}},
            t_lookup_statistic),
        "compare_numbers": Tool(
            "compare_numbers", "Compare the claim's number with an official figure using the C2 tolerances "
            "(none: equal after rounding to the claim's precision; approx: within 10%; at_least / at_most: "
            "official is at or above / at or below; a range: official inside it). Always use before deciding C2.",
            {"type": "object", "required": ["claim_value", "official_value"], "properties": {
                "claim_value": {"type": "string"}, "official_value": {"type": "string", "description": "value_text of a record"},
                "hedge": {"type": "string", "enum": list(HEDGES)}}},
            t_compare_numbers),
    }
    return [catalog[n] for n in names]
