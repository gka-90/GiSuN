"""Deterministic number comparison, so the model never does the arithmetic."""

import re
from decimal import ROUND_HALF_UP, Decimal

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


# Hedge words around a claimed number (step 1 of C2). Longest phrases first, so "no more than"
# is not read as "more than".
_HEDGE_WORDS = {
    "at_most": ["no more than", "not more than", "less than", "fewer than", "at most", "up to", "under", "below"],
    "at_least": ["no less than", "no fewer than", "more than", "greater than", "in excess of", "upwards of",
                 "at least", "exceeding", "exceeded", "exceeds", "above", "over"],
    "approx": ["approximately", "an estimated", "more or less", "close to", "roughly", "nearly", "almost",
               "around", "about", "circa", "some", "~"],
}
_HEDGE_BEFORE = re.compile(r"(?<![a-z])(" + "|".join(re.escape(w) for w in sorted(
    (w for ws in _HEDGE_WORDS.values() for w in ws), key=len, reverse=True)) + r")\s*(?:us\$|\$|€|£)?$", re.I)
_HEDGE_AFTER = [("at_least", re.compile(r"^\s*(?:\+|or (?:more|higher|above|greater)|plus\b)", re.I)),
                ("at_most", re.compile(r"^\s*or (?:less|fewer|lower|below)", re.I)),
                ("approx", re.compile(r"^\s*or so\b", re.I))]
HEDGES = ("none", "approx", "at_least", "at_most")
_RANGE = re.compile(r"^(?:between\s+)?\$?\s*(-?[\d,.]+)\s*(%|percent|per cent)?\s*(?:-|–|—|to|and)\s*\$?\s*"
                    r"(-?[\d,.]+)\s*(.*)$", re.I)


def hedge_of(sentence: str, value: str) -> str:
    """The hedge on `value` in the sentence: none | approx | at_least | at_most."""
    i = (sentence or "").lower().find((value or "").lower())
    if i < 0:
        return "none"
    if m := _HEDGE_BEFORE.search(sentence[:i].rstrip()):
        word = m.group(1).lower()
        return next(k for k, ws in _HEDGE_WORDS.items() if word in ws)
    after = sentence[i + len(value):]
    return next((k for k, rx in _HEDGE_AFTER if rx.search(after)), "none")


def parse_range(text: str) -> dict | None:
    """'15-25%', '5 to 10 percent', 'between 2 and 3 million', '$20-$40' -> low, high, unit."""
    t = (text or "").strip().lower().replace("us$", "$")
    if not (m := _RANGE.match(t)) or not re.search(r"\d", m.group(1)) or not re.search(r"\d", m.group(3)):
        return None
    high = parse_value(m.group(3) + " " + m.group(4))
    low = parse_value(m.group(1) + " " + (m.group(2) or m.group(4)))
    if not low or not high or low["unit"] != high["unit"]:
        return None
    if not m.group(2) and high["unit"] == "number" and m.group(4).strip():  # "2-3 million": the scale is shared
        low = parse_value(m.group(1) + " " + m.group(4))
    return {"low": low["value"], "high": high["value"], "unit": high["unit"]}


def _step(text: str) -> float:
    """The precision a claimed number is given to: '14.7%' -> 0.1, '331 million' -> 1e6,
    '42,000' / 'forty-two thousand' -> 1000. Used to round the official figure the same way."""
    t = (text or "").lower().replace("$", "").replace("€", "").replace("£", "")
    m = NUMBER.search(t)
    if not m:  # spelled out
        v = words_to_number(t)
        if v is None:
            return 1.0
        digits = str(int(v))
        return 10.0 ** (len(digits) - len(digits.rstrip("0"))) if v >= 1000 else 1.0
    digits, scale = m.group(1).replace(",", "").lstrip("-"), SCALE.get((m.group(2) or "").lower(), 1)
    if "." in digits:
        return scale * 10.0 ** -len(digits.split(".")[1])
    if int(digits or 0) >= 1000:  # trailing zeros of a big round number are not precision
        return scale * 10.0 ** (len(digits) - len(digits.rstrip("0")))
    return float(scale)


def _round_to(value: float, step: float) -> Decimal:
    return (Decimal(repr(value)) / Decimal(repr(step))).quantize(Decimal(1), rounding=ROUND_HALF_UP)


APPROX_TOLERANCE = 0.10


def compare_numbers(claim_value: str, official_value: str, hedge: str = "none") -> dict:
    """Does the official figure match the claim? (C2 tolerances)
        none      after rounding the official figure to the claim's precision, at most one unit
                  off in the claim's last digit (14.7 vs 14.8: official revisions and rounding)
        approx    within 10% of the official figure ("about", "roughly", "around", "nearly")
        at_least  official >= claim ("over", "more than", "at least")
        at_most   official <= claim ("under", "less than", "fewer than")
        a range   official inside it ("15-25%")"""
    hedge = hedge if hedge in HEDGES else "none"
    if hedge == "none" and (m := NUMBER.search(claim_value or "")):  # "about 15%" given as the value
        hedge = hedge_of(claim_value, claim_value[m.start():])
    rng, b = parse_range(claim_value), parse_value(official_value)
    a = None if rng else parse_value(claim_value)
    if (a is None and rng is None) or b is None:
        return {"comparable": False, "reason": "could not read a number from "
                + ("official_value" if b is None else "claim_value")}
    unit = rng["unit"] if rng else a["unit"]
    if {unit, b["unit"]} == {"percent", "pp"}:
        return {"comparable": False, "reason": "percent vs percentage points: different quantities"}
    if unit != b["unit"] and "ratio" not in (unit, b["unit"]):
        return {"comparable": False, "reason": f"different units ({unit} vs {b['unit']})"}
    official = b["value"]
    if b["unit"] == "ratio" and unit == "percent":
        official *= 100
    out = {"comparable": True, "official": official, "hedge": hedge}
    if rng:
        return {**out, "claim": [rng["low"], rng["high"]], "rule": "official inside the range",
                "match": rng["low"] <= official <= rng["high"]}
    claim = a["value"] * (100 if a["unit"] == "ratio" and b["unit"] == "percent" else 1)
    rel = round(abs(claim - official) / max(abs(official), 1e-9), 4)
    out.update(claim=claim, relative_difference=rel)
    if hedge == "at_least":
        return {**out, "rule": "official >= claim", "match": official >= claim}
    if hedge == "at_most":
        return {**out, "rule": "official <= claim", "match": official <= claim}
    if hedge == "approx" or a["unit"] == "ratio":  # "a third", "one in three" are approximate by nature
        return {**out, "rule": f"within {APPROX_TOLERANCE:.0%}", "match": rel <= APPROX_TOLERANCE}
    step = _step(claim_value)
    off = abs(_round_to(official, step) - _round_to(claim, step))
    return {**out, "rule": f"rounded to the claim's precision ({step:g}), at most one unit off",
            "match": off <= 1}


# ---- "is there a number at all?" (Plan agent: keep C1 whenever a number is present) ---------
# The numeric detector only flags statistic formats; "a density of 11.34 g/cm3", "averaging 22 °C" or
# "629 runs at 37.00" have numbers it doesn't flag, and the 32B Plan agent never got C1 for them.
_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?")
_NOT_A_QUANTITY = re.compile(  # calendar days and years (also "1961-62", "the 1980s"): dates, not statistics
    rf"\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?\b|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}(?![a-z])"
    r"|(?<![\d$.,])(?:1[5-9]|20)\d{2}(?:\s*[-–—/]\s*(?:(?:1[5-9]|20)\d{2}|\d{2}))?s?(?![\d%]|,\d|\.\d|\s*(?:percent|per cent))")
_DIGITS = re.compile(r"(?<![\w.,\-/:])\d[\d,]*(?:[.:]\d+)?(?:st|nd|rd|th)?(?![A-Za-z\d])")


def numbers_in(sentence: str) -> list[str]:
    """Numbers in the sentence other than years and calendar days ('11.34', '22', '40', '11th').
    Codes glued to letters ('NCT02002091', 'A890', 'COVID-19') don't count."""
    return [m.group(0) for m in _DIGITS.finditer(_NOT_A_QUANTITY.sub(" ", sentence))]
