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


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else newest_run()
    if not path:
        sys.exit("no run found under evaluation/outputs/")
    report(path)
