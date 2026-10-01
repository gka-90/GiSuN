"""Tools the task agent can be given, bound to one claim and the run context."""

from gisun.agents.loop import Tool
from gisun.tools.attribution import find_attribution
from gisun.tools.language import context_cues, wordlist_lookup
from gisun.tools.numbers import compare_numbers
from gisun.tools.retrieval import read_source, search

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

    def t_search(query: str):
        return {"results": search(query, k=5)}

    def t_read_source(source_id: str):
        doc = read_source(source_id)
        ctx.record_read(source_id, doc["text"])
        return doc

    def t_compare_numbers(claim_value: str, source_value: str):
        return compare_numbers(claim_value, source_value)

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
        "search": Tool("search", "Search reference sources. Use short, specific queries (topic + year + measure).",
                       {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
                       t_search),
        "read_source": Tool("read_source", "Open a source returned by search.",
                            {"type": "object", "required": ["source_id"],
                             "properties": {"source_id": {"type": "string"}}}, t_read_source),
        "compare_numbers": Tool("compare_numbers", "Compare the claim's number with a number from a source "
                                "(handles %, percentage points, million/billion). Always use before deciding C2.",
                                {"type": "object", "required": ["claim_value", "source_value"],
                                 "properties": {"claim_value": {"type": "string"}, "source_value": {"type": "string"}}},
                                t_compare_numbers),
    }
    return [catalog[n] for n in names]
