"""Deterministic number comparison, so the model never does the arithmetic."""

import re

SCALE = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "mn": 1e6,
         "billion": 1e9, "bn": 1e9, "b": 1e9, "trillion": 1e12, "tn": 1e12, "t": 1e12}
WORD_RATIO = {"half": 0.5, "a third": 1 / 3, "one third": 1 / 3, "one-third": 1 / 3, "a quarter": 0.25,
              "one quarter": 0.25, "one-quarter": 0.25, "two-thirds": 2 / 3, "two thirds": 2 / 3,
              "three-quarters": 0.75, "three quarters": 0.75, "doubled": 2.0, "tripled": 3.0, "halved": 0.5}
NUMBER = re.compile(r"(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(%|percentage points?|percent|per cent|pp|"
                    r"thousand|million|billion|trillion|bn|mn|tn|[kmbt]\b)?", re.I)
WORD_VALUES = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
WORD_VALUES.update({w: 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)})
WORD_SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
# "one in three", "9 out of 10"
IN_RATIO = re.compile(r"^(\w+)\s+(?:in|out of)\s+(\w+)$")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def years_in(text: str) -> list[str]:
    """Years a claim or source sentence is about, so C2 compares like with like."""
    return sorted(set(YEAR.findall(text or "")))


def words_to_number(text: str) -> float | None:
    """'forty-two thousand' -> 42000, 'a million' -> 1e6, 'two hundred and five' -> 205."""
    total, current, seen, numeric = 0.0, 0.0, False, False
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in WORD_VALUES:
            current += WORD_VALUES[word]
        elif word == "a" and not seen:
            current = 1
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word in WORD_SCALE:
            total += max(current, 1) * WORD_SCALE[word]
            current = 0
        elif word == "and" and seen:
            continue
        else:
            if seen:
                break
            continue
        seen, numeric = True, numeric or word != "a"
    return total + current if numeric else None  # "a" alone ("a lot") is not a number


def _number(word: str) -> float | None:
    """A single number word or digit string: "three" -> 3, "10" -> 10."""
    return float(word) if word.isdigit() else words_to_number(word)


def parse_value(text: str) -> dict | None:
    t = (text or "").strip().lower()
    for word, v in WORD_RATIO.items():
        if word in t:
            return {"value": v, "unit": "ratio"}
    if (m := IN_RATIO.match(t)) and _number(m.group(1)) is not None and _number(m.group(2)):
        return {"value": _number(m.group(1)) / _number(m.group(2)), "unit": "ratio"}
    m = NUMBER.search(t.replace("$", "").replace("€", "").replace("£", ""))
    if not m:  # no digits: try spelled-out numbers ("forty percent", "a million")
        value = words_to_number(t)
        if value is None:
            return None
        return {"value": value, "unit": "percent" if re.search(r"per ?cent", t) else "number"}
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
