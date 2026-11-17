"""
Every criterion's decisions in one run, and for the undecided ones the reason, so a run on any
dataset (ours or a public one) says not just "undetermined" but why.

    python -m evaluation.status_report                       # the newest run on disk
    python -m evaluation.status_report evaluation/outputs/ablation_.../full
    python -m evaluation.status_report evaluation/outputs/claude_2026-10-12_full_Qwen...json

Reason codes (deterministic, from the decision and the tool calls, never the model's own words):
C2 has its own (see gisun/agents/check.py, c2_status); every other criterion gets decided,
no_tool_call, no_evidence or weighed. A failed agent is agent_failed, the C6 pre-filter prefiltered.
"""

import glob
import json
import os
import sys
from collections import Counter

ORDER = ["met", "not_met", "undetermined"]

# ── customer-facing grouping ──────────────────────────────────────────────────
# Three top-level outcomes visible to the user:
#   ⚠️  needs_review  – number didn't match official data
#   ✓  verified       – cross-checked, looks fine
#   —  unverifiable   – couldn't make a call; sub-bucket explains why
#
# Three sub-buckets for unverifiable:
#   not_covered   → add a data source to fix
#   claim_vague   → claim is under-specified (no year / place / type mismatch)
#   system_error  → lookup failure or conflicting official sources

CUSTOMER_OUTCOME = {
    "met":          "⚠️  needs_review",
    "not_met":      "✓  verified",
    "undetermined": "—  unverifiable",
}

CUSTOMER_BUCKET = {
    "no_series":           "not_covered",
    "no_series_for_place": "not_covered",
    "no_record":           "not_covered",
    "no_period":           "claim_vague",
    "no_place":            "claim_vague",
    "not_comparable":      "claim_vague",
    "not_looked_up":       "claim_vague",
    "no_measure":          "claim_vague",
    "no_tool_call":        "claim_vague",
    "weighed":             "claim_vague",
    "prefiltered":         "claim_vague",
    "lookup_error":        "system_error",
    "agent_failed":        "system_error",
    "source_conflict":     "system_error",
    "no_evidence":         "not_covered",
}

BUCKET_LABEL = {
    "not_covered": "not covered     (add a data source)",
    "claim_vague": "claim vague     (year / place / type unclear)",
    "system_error":"system error    (lookup failed or sources conflict)",
}



def newest_run() -> str | None:
    runs = glob.glob("evaluation/outputs/*/full") + glob.glob("evaluation/outputs/*_full_*.json")
    return max(runs, key=os.path.getmtime) if runs else None


def decisions(path: str):
    """(criterion, decision, status, by) for every decision in a batch folder or a test-run file."""
    if path.endswith(".json"):
        for a in json.load(open(path))["answers_detail"]:
            for c in a["claims"]:
                for cid, dec in c.get("criteria", {}).items():
                    yield cid, dec, (c.get("status") or {}).get(cid) or c.get("c2_status"), \
                        (c.get("by") or {}).get(cid)
        return
    for f in sorted(glob.glob(os.path.join(path, "*.json"))):
        if os.path.basename(f) == "batch_summary.json":
            continue
        for c in json.load(open(f))["claims"]:
            for cid, dec in c["criteria"].items():
                yield cid, dec["decision"], dec.get("status") or dec.get("c2_status"), dec.get("by")


def report(path: str) -> None:
    rows, why = Counter(), Counter()
    for cid, dec, status, by in decisions(path):
        rows[(cid, dec)] += 1
        if dec == "undetermined":
            why[(cid, status or f"by={by}")] += 1
    print(path)
    total = sum(rows.values())
    if not total:
        return print("no decisions in this run")
    print(f"\n{'criterion':11}" + "".join(f"{d:>14}" for d in ORDER) + f"{'total':>8}")
    for cid in sorted({c for c, _ in rows}):
        n = sum(v for (c, _), v in rows.items() if c == cid)
        print(f"{cid:11}" + "".join(f"{rows[(cid, d)]:>14}" for d in ORDER) + f"{n:>8}")
    print(f"\n{'undetermined, by reason':34}count")
    for (cid, status), n in sorted(why.items(), key=lambda kv: (kv[0][0], -kv[1])):
        print(f"{cid} {status:<32}{n}")
    customer_report(rows, why)




def customer_report(rows, why) -> None:
    """Customer-facing summary: three outcomes + three sub-buckets."""
    from collections import Counter as _C
    outcomes, buckets = _C(), _C()
    for (cid, dec), n in rows.items():
        outcomes[CUSTOMER_OUTCOME.get(dec, dec)] += n
    for (cid, status), n in why.items():
        raw = status or ""
        # old-format runs have "by=None" instead of a real status code
        if raw.startswith("by="):
            raw = "not_looked_up"
        buckets[CUSTOMER_BUCKET.get(raw, "system_error")] += n

    total = sum(outcomes.values())
    print("\n── customer view " + "─" * 42)
    for label in CUSTOMER_OUTCOME.values():
        pct = 100 * outcomes[label] / total if total else 0
        print(f"  {label:<24} {outcomes[label]:>5}  ({pct:.0f}%)")
    unv = outcomes["—  unverifiable"]
    if unv:
        print(f"\n  unverifiable breakdown ({unv} total):")
        for key, label in BUCKET_LABEL.items():
            n = buckets[key]
            pct = 100 * n / unv if unv else 0
            print(f"    {label:<42} {n:>4}  ({pct:.0f}%)")
    print("─" * 60)

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else newest_run()
    if not path:
        sys.exit("no run found under evaluation/outputs/")
    report(path)
