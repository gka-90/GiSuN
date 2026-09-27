"""
test.py -- runs the "Two Truths and a Lie" feature using ONLY the
curated fallback word bank (no live model call). Use this to demo
or test the reliable, production-quality version of the quiz.

To test the experimental live-generation path instead, use
quiz_generator.generate_quiz(topic) directly.
"""

import json
import random

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
    {
        "statements": [
            "The American Civil War lasted four years, from 1861 to 1865.",
            "The Confederate States of America consisted of eleven southern states that seceded from the Union.",
            "The Emancipation Proclamation immediately freed all enslaved people in the entire United States.",
        ],
        "false_index": 2,
        "explanation": "The Emancipation Proclamation only applied to enslaved people in Confederate states still in rebellion; it did not free enslaved people in border states, and full abolition nationwide came later with the 13th Amendment.",
    },
    {
        "statements": [
            "Vaccines work by training the immune system to recognize a pathogen without causing the disease itself.",
            "Most vaccines contain a live, fully active version of the virus they protect against.",
            "Some vaccines require multiple doses to build full immunity.",
        ],
        "false_index": 1,
        "explanation": "Most vaccines use a weakened, inactivated, or partial form of the pathogen (or a piece of its genetic material) rather than a live, fully active virus.",
    },
    {
        "statements": [
            "A black hole's event horizon is the boundary beyond which nothing, not even light, can escape.",
            "Black holes are completely empty regions of space with no mass at all.",
            "Supermassive black holes are thought to exist at the center of most large galaxies.",
        ],
        "false_index": 1,
        "explanation": "Black holes are not empty -- they contain an extremely large amount of mass compressed into a very small volume, which is exactly why their gravity is so strong.",
    },
    {
        "statements": [
            "Neural networks are loosely inspired by the structure of neurons in the human brain.",
            "Neural networks require large amounts of labeled training data to learn through supervised learning.",
            "A trained neural network's predictions are always 100% accurate once training is complete.",
        ],
        "false_index": 2,
        "explanation": "No trained model is ever guaranteed to be 100% accurate; neural networks can still make mistakes on new, unseen data even after extensive training.",
    },
    {
        "statements": [
            "Central banks often raise interest rates to help slow down high inflation.",
            "Higher interest rates typically make borrowing more expensive, which can reduce consumer spending.",
            "Inflation and interest rates are completely unrelated and never influence one another.",
        ],
        "false_index": 2,
        "explanation": "Inflation and interest rates are closely linked; central banks routinely adjust interest rates specifically because of their effect on inflation.",
    },
]


def get_quiz(topic: str = None) -> dict:
    """Return a quiz from the curated word bank. If topic is given and
    matches a quiz's subject, return that one; otherwise pick at random."""
    if topic:
        for quiz in FALLBACK_QUIZZES:
            if topic.lower() in quiz["statements"][0].lower() or topic.lower() in str(quiz).lower():
                result = quiz.copy()
                result["source"] = "wordbank"
                return result

    result = random.choice(FALLBACK_QUIZZES).copy()
    result["source"] = "wordbank"
    return result


if __name__ == "__main__":
    quiz = get_quiz()
    print(json.dumps(quiz, indent=2, ensure_ascii=False))