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

C1 (no source for the number) and C5 (vague "studies show") usually describe the same
missing source, so together they add at most ATTRIBUTION_CAP points (open problem #5):
"Studies show 40% ..." is one attribution problem, not two.
"""

from gisun.criteria import CRITERIA

ORDER = {"low": 0, "medium": 1, "high": 2}
ATTRIBUTION_GROUP = {"C1", "C5"}
ATTRIBUTION_CAP = 2


def score_claim(decisions: dict[str, dict]) -> dict:
    points, reasons, attribution = 0, [], 0
    for cid, d in decisions.items():
        if d["decision"] == "met":
            p = CRITERIA[cid]["severity"].get(d["strength"], 1)
            if cid in ATTRIBUTION_GROUP:  # C1 and C5 share one budget of ATTRIBUTION_CAP points
                p = min(p, ATTRIBUTION_CAP - attribution)
                attribution += p
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
