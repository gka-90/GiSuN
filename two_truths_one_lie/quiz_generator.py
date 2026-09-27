"""
Two Truths and a Lie -- quiz generator with cleanup, validation, retry, and fallback.

Findings from testing (see Qwen_Local_Model_Test_Log.md and follow-up rounds):
- Model sometimes wraps output in ```json code fences
- false_index sometimes doesn't match the explanation's actual target
- explanation sometimes criticizes more than one statement instead of just false_index
- Sometimes generates the wrong number of statements, or copies the prompt's
  own placeholder text ("statement A", "statement B", "statement C") verbatim
- Sometimes returns invalid JSON syntax, or responds in Chinese despite an
  English-only instruction
- Across ~20 test runs, roughly 1/4 to 1/3 were fully clean (correct format,
  index matches explanation, no truncation). This module cannot fully close
  that gap -- it can only catch what is mechanically checkable.
"""

import json
import re
import random
import ollama

MODEL = "qwen2.5:1.5b"
MAX_RETRIES = 2

PLACEHOLDER_PATTERNS = {"statement a", "statement b", "statement c"}

FALLBACK_QUIZZES = [
    {
        "statements": [
            "A qubit can exist in a superposition of both 0 and 1 simultaneously.",
            "Quantum computers can break all encryption algorithms in the world in just a few seconds.",
            "Quantum entanglement allows two particles to be correlated even when separated by a great distance.",
        ],
        "false_index": 1,
        "explanation": "While quantum computers are powerful, they cannot instantly break all encryption algorithms. This is a common exaggeration.",
    },
    {
        "statements": [
            "Photosynthesis primarily takes place in the chloroplasts of plant cells.",
            "During photosynthesis, plants consume oxygen and release carbon dioxide as waste.",
            "The light-dependent reactions of photosynthesis convert solar energy into chemical energy stored in ATP.",
        ],
        "false_index": 1,
        "explanation": "Photosynthesis consumes carbon dioxide and releases oxygen, not the other way around.",
    },
]


def _build_prompt(topic: str) -> str:
    return f"""Generate three statements about {topic}: two true, one intentionally false but plausible-sounding.
Respond in English only.
Return ONLY valid JSON, with no other text before or after it, no markdown code fences, in exactly this format:
{{
  "statements": ["statement A", "statement B", "statement C"],
  "false_index": 0,
  "explanation": "Explain ONLY why the statement at false_index is false. Do not discuss or criticize the other two statements at all."
}}"""


def _clean_json_text(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _validate(parsed: dict) -> bool:
    if not isinstance(parsed, dict):
        return False
    statements = parsed.get("statements")
    false_index = parsed.get("false_index")
    explanation = parsed.get("explanation")

    if not isinstance(statements, list) or len(statements) != 3:
        return False
    if not all(isinstance(s, str) and s.strip() for s in statements):
        return False
    # Reject verbatim copies of the prompt's own placeholder text
    if any(s.strip().lower() in PLACEHOLDER_PATTERNS for s in statements):
        return False
    if not isinstance(false_index, int) or not (0 <= false_index <= 2):
        return False
    if not isinstance(explanation, str) or not explanation.strip():
        return False
    # Reject explanations that are suspiciously long / list-like, which in
    # testing correlated with the model critiquing more than one statement
    # (e.g. "The first statement... The second statement... The third...").
    lowered = explanation.lower()
    multi_critique_markers = ["the first statement", "the second statement", "the third statement"]
    if sum(marker in lowered for marker in multi_critique_markers) >= 2:
        return False
    return True


def _try_generate_once(topic: str):
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": _build_prompt(topic)}],
        )
        raw = response["message"]["content"]
    except Exception as e:
        print(f"[quiz_generator] API call failed: {e}")
        return None, None

    cleaned = _clean_json_text(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[quiz_generator] JSON parse failed: {e}\nRaw output was:\n{raw}")
        return None, raw

    if not _validate(parsed):
        print(f"[quiz_generator] Validation failed for parsed output:\n{parsed}")
        return None, raw

    return parsed, raw


def generate_quiz(topic: str) -> dict:
    last_raw = None
    for attempt in range(MAX_RETRIES + 1):
        result, raw = _try_generate_once(topic)
        last_raw = raw
        if result is not None:
            result["source"] = "model"
            result["topic"] = topic
            return result
        print(f"[quiz_generator] Attempt {attempt + 1} failed" + (", retrying..." if attempt < MAX_RETRIES else ""))

    fallback = random.choice(FALLBACK_QUIZZES).copy()
    fallback["source"] = "fallback"
    fallback["topic"] = topic
    fallback["last_raw_output"] = last_raw
    return fallback


TOPICS = [
    "photosynthesis",
    "the American Civil War",
    "how neural networks work",
    "how vaccines work",
    "inflation and interest rates",
    "black holes",
]


if __name__ == "__main__":
    import os

    os.makedirs("output", exist_ok=True)
    all_results = []

    for topic in TOPICS:
        print(f"\n=== Topic: {topic} ===")
        quiz = generate_quiz(topic)
        print(json.dumps(quiz, indent=2, ensure_ascii=False))
        all_results.append(quiz)

    with open("output/all_quiz_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(all_results)} results to output/all_quiz_results.json")
