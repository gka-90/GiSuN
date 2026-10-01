"""
Check agent (deterministic): validates the structure and grounding of one
criterion decision. Runs inside the task loop (so the model can fix problems)
and again on the final answer.
"""

from gisun.criteria import CRITERIA, DECISIONS, STRENGTHS

MIN_REASON_WORDS = 6


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
        quote, source = str(e.get("quote") or ""), str(e.get("source") or "")
        if not quote.strip():
            problems.append("an evidence item has an empty quote.")
        elif source == "response":
            if not _in_response(quote, claim):
                problems.append(f"{quote!r} is not in the claim or the sentences before it. Copy it exactly.")
        elif source in ctx.read_sources:
            if quote.lower() not in ctx.read_sources[source].lower():
                problems.append(f"{quote!r} is not in source {source!r}. Quote what the source actually says.")
        else:
            problems.append(f"source {source!r} was not opened in this run; use 'response' or a source_id you read.")

    if cid == "C2" and decision in ("met", "not_met"):
        compared = [t for t in tool_log if t["tool"] == "compare_numbers" and t["output"].get("comparable")]
        if not compared:
            problems.append("C2: call compare_numbers on the claim's number and the source's number first.")
        elif decision == "met" and all(t["output"]["match"] for t in compared):
            problems.append("C2: compare_numbers says the numbers match, so the claim is not contradicted.")
        elif decision == "not_met" and not any(t["output"]["match"] for t in compared):
            problems.append("C2: no comparison matched, so you can't say a source supports the number.")
    return problems


def normalize(cid: str, answer: dict) -> dict:
    return {"criterion": cid, "name": CRITERIA[cid]["name"], "decision": answer["decision"],
            "strength": answer["strength"], "reasoning": answer["reasoning"],
            "evidence": answer.get("evidence") or []}
