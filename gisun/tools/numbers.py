"""Deterministic number comparison, so the model never does the arithmetic."""

import re

SCALE = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "mn": 1e6,
         "billion": 1e9, "bn": 1e9, "b": 1e9, "trillion": 1e12, "tn": 1e12, "t": 1e12}
WORD_RATIO = {"half": 0.5, "a third": 1 / 3, "one third": 1 / 3, "one-third": 1 / 3, "a quarter": 0.25,
              "one quarter": 0.25, "one-quarter": 0.25, "two-thirds": 2 / 3, "two thirds": 2 / 3,
              "three-quarters": 0.75, "three quarters": 0.75, "doubled": 2.0, "tripled": 3.0, "halved": 0.5}
NUMBER = re.compile(r"(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(%|percentage points?|percent|per cent|pp|"
                    r"thousand|million|billion|trillion|bn|mn|tn|[kmbt]\b)?", re.I)


def parse_value(text: str) -> dict | None:
    t = (text or "").strip().lower()
    for word, v in WORD_RATIO.items():
        if word in t:
            return {"value": v, "unit": "ratio"}
    m = NUMBER.search(t.replace("$", "").replace("€", "").replace("£", ""))
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").lower()
    if suffix in ("%", "percent", "per cent"):
        return {"value": value, "unit": "percent"}
    if suffix.startswith("percentage point") or suffix == "pp":
        return {"value": value, "unit": "pp"}
    return {"value": value * SCALE.get(suffix, 1), "unit": "number"}


def compare_numbers(claim_value: str, source_value: str, tolerance: float = 0.05) -> dict:
    a, b = parse_value(claim_value), parse_value(source_value)
    if a is None or b is None:
        return {"comparable": False, "reason": "could not read a number from "
                + ("claim_value" if a is None else "source_value")}
    if {a["unit"], b["unit"]} == {"percent", "pp"}:
        return {"comparable": False, "reason": "percent vs percentage points: different quantities"}
    if a["unit"] != b["unit"] and "ratio" not in (a["unit"], b["unit"]):
        return {"comparable": False, "reason": f"different units ({a['unit']} vs {b['unit']})"}
    base = max(abs(b["value"]), 1e-9)
    rel = abs(a["value"] - b["value"]) / base
    return {"comparable": True, "claim": a["value"], "source": b["value"],
            "relative_difference": round(rel, 4), "match": rel <= tolerance}
