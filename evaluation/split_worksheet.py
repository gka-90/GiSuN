"""
Split agent-worksheet labeling between two annotators, with a shared overlap for agreement.

    python -m evaluation.split_worksheet --agent <agent.json> --rules <rules.json> --answers <answers.json> \
        --prefix test_reports/claude_agent_worksheet

Plan (P1 = agent met, P2 = agent undetermined):
  annotator A: P1 C1 (random sample of --c1-sample) + P1 C6
  annotator B: P1 C3, C4, C5 + all P2 (agent undetermined)
  shared:      --shared-per-criterion P1 rows per criterion (C1, C3, C4, C5, C6), labeled by BOTH, independently
Writes <prefix>_<a>.xlsx and <prefix>_<b>.xlsx and <prefix>_assignment.json.
"""

import argparse
import json
import random
import subprocess
import sys

from evaluation.make_agent_worksheet import load


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--answers", nargs="+", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--names", nargs=2, default=["suning", "gideon"])
    ap.add_argument("--c1-sample", type=int, default=50)
    ap.add_argument("--shared-per-criterion", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    agent, rules = load(a.agent), load(a.rules)

    p1 = {}
    for (aid, sent, crit), (_, v) in agent.items():
        if v == "met":
            p1.setdefault(crit, []).append((aid, sent, crit))
    p2 = [k for k, (_, v) in agent.items() if v == "undetermined" and k[2] != "C2"]  # C2 needs fact-checking; skipped
    for k in p1:
        p1[k].sort()
    c1 = rnd.sample(p1.get("C1", []), min(a.c1_sample, len(p1.get("C1", []))))

    A = set(c1) | set(p1.get("C6", []))
    B = set(p1.get("C3", []) + p1.get("C4", []) + p1.get("C5", [])) | set(p2)
    shared = set()
    for crit, pool in [("C1", c1)] + [(c, p1.get(c, [])) for c in ("C3", "C4", "C5", "C6")]:
        shared |= set(rnd.sample(sorted(pool), min(a.shared_per_criterion, len(pool))))
    A |= shared
    B |= shared

    assignment = {a.names[0]: sorted(A), a.names[1]: sorted(B), "shared": sorted(shared)}
    json.dump(assignment, open(f"{a.prefix}_assignment.json", "w"), indent=1, ensure_ascii=False)
    for name, keys in ((a.names[0], A), (a.names[1], B)):
        kf = f"{a.prefix}_{name}_keys.json"
        json.dump([[k[0], k[1], k[2], k in shared] for k in sorted(keys)], open(kf, "w"), ensure_ascii=False)
        subprocess.run([sys.executable, "-m", "evaluation.make_agent_worksheet", "--agent", a.agent, "--rules", a.rules,
                        "--answers", *a.answers, "--keys", kf, "--out", f"{a.prefix}_{name}.xlsx"], check=True)
    print(f"{a.names[0]}: {len(A)} rows, {a.names[1]}: {len(B)} rows, shared: {len(shared)}")


if __name__ == "__main__":
    main()
