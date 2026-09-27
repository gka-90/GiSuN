"""
success_rate_test.py -- runs generate_quiz() many times across all topics
and reports how often it succeeds via the model vs. falls back to the
word bank, plus how often each retry attempt was needed.

Import note: this expects quiz_generator.py to be in the same folder,
with its internal functions exposed the way they currently are
(_try_generate_once, MAX_RETRIES, TOPICS). If quiz_generator.py changes
its internal structure, this script needs matching updates.
"""

import json
import time
from collections import Counter

from two_truths_one_lie.quiz_generator import generate_quiz, _try_generate_once, MAX_RETRIES, TOPICS


def run_success_rate_test(runs_per_topic: int = 5):
    """
    For each topic, call generate_quiz() `runs_per_topic` times.
    For each call, also track which attempt (1st try, 2nd try, 3rd try,
    or fallback) actually produced the result, by re-implementing the
    retry loop here with logging instead of relying on generate_quiz()'s
    internal print statements.
    """
    results = []
    source_counts = Counter()
    attempt_counts = Counter()  # which attempt number succeeded, or "fallback"

    total_calls = len(TOPICS) * runs_per_topic
    call_num = 0

    for topic in TOPICS:
        for run in range(runs_per_topic):
            call_num += 1
            print(f"\n[{call_num}/{total_calls}] Topic: {topic} (run {run + 1}/{runs_per_topic})")

            succeeded_on_attempt = None
            final_result = None

            for attempt in range(MAX_RETRIES + 1):
                parsed, raw = _try_generate_once(topic)
                if parsed is not None:
                    succeeded_on_attempt = attempt + 1  # 1-indexed
                    parsed["source"] = "model"
                    parsed["topic"] = topic
                    final_result = parsed
                    break
                print(f"  attempt {attempt + 1} failed")

            if final_result is None:
                # matches generate_quiz()'s fallback behavior
                import random
                from two_truths_one_lie.quiz_generator import FALLBACK_QUIZZES
                fallback = random.choice(FALLBACK_QUIZZES).copy()
                fallback["source"] = "fallback"
                fallback["topic"] = topic
                final_result = fallback
                attempt_counts["fallback"] += 1
            else:
                attempt_counts[f"attempt_{succeeded_on_attempt}"] += 1

            source_counts[final_result["source"]] += 1
            results.append({
                "topic": topic,
                "run": run + 1,
                "source": final_result["source"],
                "succeeded_on_attempt": succeeded_on_attempt,
                "result": final_result,
            })

    return results, source_counts, attempt_counts


def print_summary(results, source_counts, attempt_counts, runs_per_topic):
    total = len(results)
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total calls: {total} ({len(TOPICS)} topics x {runs_per_topic} runs)")
    print()

    model_success = source_counts.get("model", 0)
    fallback_used = source_counts.get("fallback", 0)
    print(f"Succeeded via model (any attempt):  {model_success}/{total}  ({100*model_success/total:.1f}%)")
    print(f"Fell back to word bank:              {fallback_used}/{total}  ({100*fallback_used/total:.1f}%)")
    print()

    print("Breakdown by which attempt succeeded:")
    for key in ["attempt_1", "attempt_2", "attempt_3", "fallback"]:
        count = attempt_counts.get(key, 0)
        print(f"  {key}: {count}/{total} ({100*count/total:.1f}%)")

    print()
    print("Per-topic breakdown:")
    by_topic = {}
    for r in results:
        by_topic.setdefault(r["topic"], []).append(r["source"])
    for topic, sources in by_topic.items():
        model_count = sources.count("model")
        print(f"  {topic}: {model_count}/{len(sources)} succeeded via model")


if __name__ == "__main__":
    RUNS_PER_TOPIC = 5  # adjust based on how much time you have -- more runs = more reliable %

    start = time.time()
    results, source_counts, attempt_counts = run_success_rate_test(runs_per_topic=RUNS_PER_TOPIC)
    elapsed = time.time() - start

    print_summary(results, source_counts, attempt_counts, RUNS_PER_TOPIC)
    print(f"\nTotal time: {elapsed:.1f}s")

    import os
    os.makedirs("output", exist_ok=True)
    with open("output/success_rate_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("Full results saved to output/success_rate_results.json")
