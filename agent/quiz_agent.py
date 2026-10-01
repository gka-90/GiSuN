"""
Two Truths and a Lie, as an agent with self-checking.

two_truths_one_lie/quiz_generator.py retries blindly: a bad generation is
thrown away and the same prompt is sent again. Here the model submits its
quiz through a `submit_quiz` tool and every submission is checked:

    1. format    -- the same rules as quiz_generator._validate, but each
                    failure is explained to the model so it can fix it
    2. focus     -- the explanation has to be about the statement at
                    false_index (the README's known semantic failure)
    3. blind solve -- separate model calls see only the three statements
                    and pick the false one (up to 3 tries, 2 must agree); if
                    they pick a different one, or can't agree on any, the lie
                    is either not false or the truths aren't true

Failed checks go back to the model, which revises the same quiz instead of
starting over. If it never passes, a curated quiz from quiz_static is used
(verified=False: it was written by hand, not blind-solved).
"""

import json
import re
from collections import Counter

from agent import core
from agent.core import MODEL, Tool, run_agent
from two_truths_one_lie.quiz_generator import PLACEHOLDER_PATTERNS, _clean_json_text
from two_truths_one_lie.quiz_static import get_quiz

MAX_STEPS = 5
# Blind-solve temperatures: the first try is deterministic, the others vary so
# two agreeing answers mean more than the same answer twice
SOLVE_TEMPERATURES = (0, 0.7, 0.7)
STOPWORDS = {"the", "a", "an", "of", "in", "on", "and", "or", "to", "is", "are", "was", "were",
             "it", "that", "this", "can", "be", "by", "for", "as", "with", "from", "not", "its"}

SYSTEM_PROMPT = """You write "Two Truths and a Lie" quizzes for students.
Write three statements about the topic: two true, one false but plausible-sounding.
Submit with the submit_quiz tool. The explanation must say ONLY why the statement at
false_index is false. Your quiz will be checked; if it is rejected, fix the listed
problems and call submit_quiz again. Respond in English."""


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 2}


def _format_problems(statements, false_index, explanation) -> list[str]:
    problems = []
    if not isinstance(statements, list) or len(statements) != 3 \
            or not all(isinstance(s, str) and s.strip() for s in statements):
        return ["`statements` must be a list of exactly 3 non-empty sentences."]
    if any(s.strip().lower() in PLACEHOLDER_PATTERNS for s in statements):
        problems.append("Replace the placeholder text with real statements about the topic.")
    if not isinstance(false_index, int) or not 0 <= false_index <= 2:
        problems.append("`false_index` must be 0, 1 or 2.")
    if not isinstance(explanation, str) or len(explanation.split()) < 5:
        problems.append("`explanation` must be a full sentence saying why the false statement is false.")
    if any(re.search(r"[一-鿿]", s) for s in statements + [explanation or ""]):
        problems.append("Write everything in English.")
    return problems


def _focus_problem(statements: list[str], false_index: int, explanation: str) -> str | None:
    """The explanation should share the most content words with the false statement."""
    overlap = [len(_content_words(s) & _content_words(explanation)) for s in statements]
    best = max(range(3), key=lambda i: overlap[i])
    if overlap[best] > overlap[false_index]:
        return (f"The explanation talks about statement {best} ({statements[best]!r}), but false_index "
                f"is {false_index}. Either change false_index or rewrite the explanation so it is "
                f"only about statement {false_index}.")
    return None


def _blind_solve(statements: list[str], temperature: float = 0) -> int | None:
    """Ask the model, with no hints, which statement is false."""
    numbered = "\n".join(f"{i}: {s}" for i, s in enumerate(statements))
    prompt = (f"Exactly one of these statements is false:\n{numbered}\n\n"
              'Which one? Reply with ONLY JSON like {"false_index": 1}.')
    try:
        reply = core.chat(model=MODEL, messages=[{"role": "user", "content": prompt}],
                          options={"temperature": temperature})
        answer = int(json.loads(_clean_json_text(reply.message.content)).get("false_index"))
    except Exception:
        return None
    # 3 or -5 would crash statements[solved] in check_quiz; -1 would quietly point at the wrong one
    return answer if answer in (0, 1, 2) else None


def _blind_vote(statements: list[str]) -> tuple[int | None, list]:
    """Majority of up to 3 blind solves; None unless 2 of them agree. Unanswered
    solves don't count as votes. Returns (answer, every solve's pick)."""
    picks = []
    for temperature in SOLVE_TEMPERATURES:
        picks.append(_blind_solve(statements, temperature))
        votes = Counter(p for p in picks if p is not None).most_common(1)
        if votes and votes[0][1] >= 2:
            return votes[0][0], picks
    return None, picks


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def check_quiz(args: dict, solve_log: list) -> list[str]:
    statements, explanation = args.get("statements"), args.get("explanation")
    false_index = _as_int(args.get("false_index"))
    if isinstance(statements, str):  # small models sometimes send the list as a JSON string
        try:
            statements = json.loads(statements)
        except json.JSONDecodeError:
            pass

    problems = _format_problems(statements, false_index, explanation)
    if problems:
        return problems
    focus = _focus_problem(statements, false_index, explanation)
    if focus:
        return [focus]

    solved, picks = _blind_vote(statements)
    solve_log.append({"statements": statements, "false_index": false_index,
                      "solver_picked": solved, "solver_votes": picks})
    if solved is None:
        return ["Independent readers could not agree on which statement is the lie. Make the false "
                "statement clearly false and the other two clearly true."]
    if solved != false_index:
        return [f"An independent reader thought statement {solved} ({statements[solved]!r}) was the "
                f"lie, not statement {false_index}. Make the false statement clearly false and the "
                "other two clearly true."]
    args.update(statements=statements, false_index=false_index)
    return []


def generate_quiz_agent(topic: str) -> dict:
    """
    Same output shape as quiz_generator.generate_quiz(), plus:
        "verified": True if independent blind solves agreed with false_index (every
                    accepted model quiz); False for the curated fallback
        "steps", "trace": the agent's step log
    """
    solve_log = []
    finish = Tool(
        "submit_quiz", "Submit the quiz for checking.",
        {"type": "object", "required": ["statements", "false_index", "explanation"], "properties": {
            "statements": {"type": "array", "items": {"type": "string"}, "description": "exactly 3"},
            "false_index": {"type": "integer", "description": "index (0-2) of the false statement"},
            "explanation": {"type": "string", "description": "why ONLY that statement is false"}}},
        lambda **_: None,
    )
    run = run_agent(SYSTEM_PROMPT, f"Topic: {topic}", [], finish,
                    check=lambda args: check_quiz(args, solve_log), max_steps=MAX_STEPS)

    if run.answer is not None:
        quiz = {k: run.answer[k] for k in ("statements", "false_index", "explanation")}
        quiz.update(source="model", verified=True)  # check_quiz only accepts a blind-solve majority
    else:
        quiz = dict(get_quiz(topic), source="fallback", verified=False)
    return {**quiz, "topic": topic, "steps": run.steps, "trace": run.trace}


if __name__ == "__main__":
    import sys
    result = generate_quiz_agent(sys.argv[1] if len(sys.argv) > 1 else "photosynthesis")
    print(json.dumps(result, indent=2, ensure_ascii=False))
