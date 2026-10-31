"""
Check agent (deterministic): validates the structure and grounding of one
criterion decision. Runs inside the task loop (so the model can fix problems)
and again on the final answer.
"""

from gisun.criteria import CRITERIA, DECISIONS, STRENGTHS, c2_outcome
from gisun.tools.numbers import hedge_of, parse_value
from gisun.tools.retrieval import mentions, normalize_period, period_in_text, resolve_place

MIN_REASON_WORDS = 6
# These tools only return text from the answer itself, so a quote "from" them is a quote from
# the response. Qwen 32B named the tool as the source and kept failing the check (seen on the HPC).
RESPONSE_SOURCES = {"response", "context_window", "find_attribution", "context_cues", "claim", "sentence"}


def _source(e: dict) -> str:
    """The evidence source, with tool names that only show the answer mapped to "response"."""
    source = str(e.get("source") or "")
    return "response" if source.lower() in RESPONSE_SOURCES else source


C2_FIELDS = ("value", "measure", "place", "period", "hedge")
# Kept with every C2 figure for the human reviewer (the instruction's evidence list)
OFFICIAL_KEYS = ("source", "series_id", "measure", "place", "period", "value_text", "unit", "query_date", "note")


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
        elif source in ctx.official_records:
            rec, got = ctx.official_records[source], parse_value(quote)
            if not got or abs(got["value"] - rec["value"]) > 1e-9 * max(1.0, abs(rec["value"])):
                problems.append(f"{quote!r} is not the figure in record {source!r}; quote its value_text "
                                f"{rec['value_text']!r}.")
        else:
            problems.append(f"source {source!r} is not the answer or an official figure fetched in this run. For words "
                            "from the answer (also when a tool showed them to you) use source 'response'; for an "
                            "official figure use the record_id lookup_statistic returned.")
    if cid == "C2":
        problems += _check_c2(answer, decision, evidence, claim, ctx, tool_log)
    return problems


def _lookups(tool_log: list[dict]) -> list[list[dict]]:
    return [t["output"]["records"] for t in tool_log
            if t["tool"] == "lookup_statistic" and isinstance(t["output"], dict) and t["output"].get("records")]


def _check_c2(answer, decision, evidence, claim, ctx, tool_log) -> list[str]:
    """The C2 steps, checked: the number is pinned down from the text, every official figure the
    lookup returned is cited, compare_numbers was used, and the decision is the one the
    tolerance rules give."""
    fields = answer.get("claim_fields") if isinstance(answer.get("claim_fields"), dict) else {}
    cited = {str(e.get("source")) for e in evidence if str(e.get("source")) in ctx.official_records}
    problems = []
    # every figure from a lookup that is cited, or (when sources disagree) every figure at all, is listed
    for records in _lookups(tool_log):
        ids = [r["record_id"] for r in records]
        disagree = fields.get("value") and len({c.get("match") for c in c2_outcome(
            str(fields["value"]), str(fields.get("hedge") or "none"), records)[1] if c.get("comparable")}) > 1
        if (cited & set(ids) or disagree) and set(ids) - cited:
            problems.append(f"C2: cite every official figure the lookup returned ({', '.join(ids)}), "
                            "so a reviewer sees when sources disagree.")
    if decision not in ("met", "not_met"):
        return problems
    if not any(t["tool"] == "compare_numbers" and t["output"].get("comparable") for t in tool_log):
        problems.append("C2: call compare_numbers on the claim's number and the official value_text first.")

    missing = [k for k in C2_FIELDS if not str(fields.get(k) or "").strip()]
    if missing:
        return problems + [f"C2: fill claim_fields {missing}. If the measure, place or time can't be told from "
                           "the claim, the two sentences before it or the user's question, decide 'undetermined'."]
    text = " ".join([ctx.question or "", *claim["context_before"], claim["sentence"]])
    value, hedge = str(fields["value"]), str(fields["hedge"])
    period, place = normalize_period(str(fields["period"])), resolve_place(str(fields["place"]))
    if not period:
        problems.append("C2: period must be a year (2020) or a month (2020-04).")
    elif not period_in_text(period, text):
        problems.append(f"C2: the claim doesn't state {period}, so the time is unknown. Decide 'undetermined'.")
    if not place:
        problems.append(f"C2: can't resolve the place {fields['place']!r}.")
    elif not any(mentions(text, a) for a in [*place["aliases"], str(fields["place"])]):
        problems.append(f"C2: the claim doesn't name {place['name']}, so the place is unknown. Decide 'undetermined'.")
    if value.lower() not in claim["sentence"].lower():
        problems.append(f"C2: value {value!r} must be the number exactly as the claim writes it.")
    elif hedge != (said := hedge_of(claim["sentence"], value)):
        problems.append(f"C2: the claim's wording around {value!r} gives hedge {said!r}, not {hedge!r}.")
    if not cited:
        return problems + ["C2: give the official figure as evidence: quote = its value_text, source = its record_id "
                           "(from lookup_statistic)."]
    records = [ctx.official_records[c] for c in sorted(cited)]
    for r in records:
        if period and r["period"] != period:
            problems.append(f"C2: {r['record_id']} is for {r['period']}, not {period}: only the same period counts.")
        if place and r["place_code"] != place["code"]:
            problems.append(f"C2: {r['record_id']} is about {r['place']}, not {place['name']}.")
    outcome, cmps = c2_outcome(value, hedge, records)
    if not problems and outcome != decision:
        detail = "; ".join(f"{c['record_id']}: {c.get('rule', c.get('reason'))}, match={c.get('match')}" for c in cmps)
        problems.append(f"C2: by the tolerance rules the official figures give {outcome!r}, not {decision!r} ({detail}).")
    return problems


def normalize(cid: str, answer: dict, ctx=None) -> dict:
    official = ctx.official_records if ctx is not None else {}

    def item(e):
        if not isinstance(e, dict):
            return e
        e = {**e, "source": _source(e)}
        if e["source"] in official:  # the fetched record, not what the model wrote about it
            e["official"] = {k: official[e["source"]][k] for k in OFFICIAL_KEYS if k in official[e["source"]]}
        return e
    out = {"criterion": cid, "name": CRITERIA[cid]["name"], "decision": answer["decision"],
           "strength": answer["strength"], "reasoning": answer["reasoning"],
           # saved as "response", not the tool name the model happened to give
           "evidence": [item(e) for e in answer.get("evidence") or []]}
    if cid == "C2" and isinstance(answer.get("claim_fields"), dict):
        out["claim_fields"] = answer["claim_fields"]
    return out
