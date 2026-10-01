"""
Deterministic combining rules: the LLM never picks the final risk level.
Kept deliberately simple -- per-criterion errors add up, so the more complex
the combination, the more an early mistake gets amplified.

Claim risk:
    high     C2 met (a reliable source contradicts the number), or points >= 3
    medium   points >= 1
    low      nothing met
  + "unverified": a statistic with no source (C1 met) that C2 could not check either
Response level = the highest claim risk.
"""

from gisun.criteria import CRITERIA

ORDER = {"low": 0, "medium": 1, "high": 2}


def score_claim(decisions: dict[str, dict]) -> dict:
    points, reasons = 0, []
    for cid, d in decisions.items():
        if d["decision"] == "met":
            p = CRITERIA[cid]["severity"].get(d["strength"], 1)
            points += p
            reasons.append(f"{cid} {CRITERIA[cid]['name']} (+{p})")
    if decisions.get("C2", {}).get("decision") == "met" or points >= 3:
        risk = "high"
    elif points >= 1:
        risk = "medium"
    else:
        risk = "low"
    unverified = decisions.get("C1", {}).get("decision") == "met" and \
        decisions.get("C2", {}).get("decision", "undetermined") == "undetermined"
    return {"risk": risk, "points": points, "because": reasons, "unverified": unverified}


def score_response(claim_scores: list[dict]) -> dict:
    if not claim_scores:
        return {"level": "low", "claims": 0, "high": 0, "medium": 0, "unverified": 0}
    return {"level": max((s["risk"] for s in claim_scores), key=ORDER.get),
            "claims": len(claim_scores),
            "high": sum(s["risk"] == "high" for s in claim_scores),
            "medium": sum(s["risk"] == "medium" for s in claim_scores),
            "unverified": sum(s["unverified"] for s in claim_scores)}
