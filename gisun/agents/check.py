"""
Check agent (deterministic): validates the structure and grounding of one
criterion decision. Runs inside the task loop (so the model can fix problems)
and again on the final answer.
"""

from gisun.criteria import CRITERIA, DECISIONS, STRENGTHS, claim_years
from gisun.preprocess import split_sentences

MIN_REASON_WORDS = 6
# These tools only return text from the answer itself, so a quote "from" them is a quote from
# the response. Qwen 32B named the tool as the source and kept failing the check (seen on the HPC).
RESPONSE_SOURCES = {"response", "context_window", "find_attribution", "context_cues", "claim", "sentence"}


def _source(e: dict) -> str:
    """The evidence source, with tool names that only show the answer mapped to "response"."""
    source = str(e.get("source") or "")
    return "response" if source.lower() in RESPONSE_SOURCES else source


def _same_year_source(evidence: list, years: list[str], ctx) -> bool:
    """Is one of the source quotes in a source sentence about one of the claim's years?"""
    for e in evidence:
        text = ctx.read_sources.get(str(e.get("source") or ""))
        quote = str(e.get("quote") or "").lower()
        if text and quote:
            if any(quote in s.lower() and any(y in s for y in years) for s in split_sentences(text)):
                return True
    return False


def _in_response(quote: str, claim: dict) -> bool:
    q = quote.lower().strip()
    return any(q in s.lower() for s in [claim["sentence"], *claim["context_before"]])


def check_decision(cid: str, answer: dict, claim: dict, ctx, tool_log: list[dict]) -> list[str]:
    problems = []
    decision, strength = str(answer.get("decision")), str(answer.get("strength"))
    reasoning, evidence = str(answer.get("reasoning") or ""), answer.get("evidence") or []
    if decision not in DECISIONS:
        problems.append(f"decision must be one of {list(DECISIONS)}.")
    if strength not in STRENGTHS:
        problems.append(f"strength must be one of {list(STRENGTHS)}.")
    if len(reasoning.split()) < MIN_REASON_WORDS:
        problems.append("reasoning must be a full sentence explaining the decision.")
    if not isinstance(evidence, list) or not all(isinstance(e, dict) for e in evidence):
        return problems + ['evidence must be a list of {"quote": ..., "source": ...} objects.']

    if decision in ("met", "not_met") and cid != "C6" and not evidence:
        problems.append("give at least one evidence quote for a met / not_met decision.")
    for e in evidence:
        quote, source = str(e.get("quote") or ""), _source(e)
        if not quote.strip():
            problems.append("an evidence item has an empty quote.")
        elif source == "response":
            if not _in_response(quote, claim):
                problems.append(f"{quote!r} is not in the claim or the sentences before it. Copy it exactly.")
        elif source in ctx.read_sources:
            if quote.lower() not in ctx.read_sources[source].lower():
                problems.append(f"{quote!r} is not in source {source!r}. Quote what the source actually says.")
        else:
            problems.append(f"source {source!r} was not opened in this run. For words from the answer (also when a tool showed them to you) use source 'response'; for a document use the source_id you opened with read_source.")

    if cid == "C2" and decision in ("met", "not_met"):
        compared = [t for t in tool_log if t["tool"] == "compare_numbers" and t["output"].get("comparable")]
        if not compared:
            problems.append("C2: call compare_numbers on the claim's number and the source's number first.")
        elif decision == "met" and all(t["output"]["match"] for t in compared):
            problems.append("C2: compare_numbers says the numbers match, so the claim is not contradicted.")
        elif decision == "not_met" and not any(t["output"]["match"] for t in compared):
            problems.append("C2: no comparison matched, so you can't say a source supports the number.")
    if cid == "C2" and decision == "met":
        # open problem #7: a different number is only a contradiction if it is about the same year
        years = claim_years(claim)
        if not years:
            problems.append("C2: the claim gives no year, so a different source figure can't contradict it. "
                            "Decide 'undetermined'.")
        elif not _same_year_source(evidence, years, ctx):
            problems.append(f"C2: quote the source figure from a sentence about {'/'.join(years)}; a figure for "
                            "another year doesn't contradict the claim. If there is none, decide 'undetermined'.")
    return problems


def normalize(cid: str, answer: dict) -> dict:
    return {"criterion": cid, "name": CRITERIA[cid]["name"], "decision": answer["decision"],
            "strength": answer["strength"], "reasoning": answer["reasoning"],
            # saved as "response", not the tool name the model happened to give
            "evidence": [{**e, "source": _source(e)} if isinstance(e, dict) else e for e in answer.get("evidence") or []]}
