"""
One command for everything that can be checked automatically:

    1. unit tests (tests/, no model needed)
    2. gold files are well-formed: valid decisions, every labeled sentence is in the item's text
    3. RQ1-RQ3 on each gold file: rules_only always; the model modes only if the model backend
       answers (an unreachable model would silently turn every mode into the rule fallback)

Writes report.md + report.json to evaluation/outputs/report_<time>/ and exits non-zero if a
test fails, a gold file is malformed, or rules_only F1 drops below --min_f1 (a regression guard
for detector changes).

    python -m evaluation.run_all                              # datasets/gold_example.json (+ datasets/gold.json if present)
    python -m evaluation.run_all --gold datasets/gold.json --modes rules_only task_only
    python -m evaluation.run_all --skip_eval                  # unit tests + gold checks only
"""

import argparse
import json
import os
import sys
import time
import unittest
from datetime import datetime
from io import StringIO

from evaluation.run_ablation import ablate
from gisun import config, llm
from gisun.criteria import CRITERIA, DECISIONS
from gisun.pipeline import MODES

DEFAULT_GOLD = [os.path.join("datasets", "gold_example.json"), os.path.join("datasets", "gold.json")]


def run_unit_tests() -> dict:
    stream = StringIO()
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    problems = [f"{t.id()}: {err.strip().splitlines()[-1]}" for t, err in result.failures + result.errors]
    return {"ran": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
            "skipped": len(result.skipped), "ok": result.wasSuccessful(), "problems": problems}


def check_gold(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    problems, pairs = [], 0
    ids = [item.get("id") for item in items]
    for dup in {i for i in ids if ids.count(i) > 1}:
        problems.append(f"duplicate id {dup}")
    for item in items:
        for key, crits in item.get("labels", {}).items():
            if key.lower() not in item["text"].lower():
                problems.append(f"{item['id']}: labeled sentence not in text: {key[:60]!r}")
            for cid, decision in crits.items():
                pairs += 1
                if cid not in CRITERIA:
                    problems.append(f"{item['id']}: unknown criterion {cid}")
                if decision not in DECISIONS:
                    problems.append(f"{item['id']}: {cid} = {decision!r} (not one of {DECISIONS})")
    return {"items": len(items), "pairs": pairs, "ok": not problems, "problems": problems}


def model_reachable() -> tuple[bool, str]:
    if not llm.available():
        return False, f"no backend (GISUN_BACKEND={config.BACKEND})"
    try:
        llm.chat([{"role": "user", "content": "Reply with OK."}])
        return True, f"{config.BACKEND} / {config.MODEL}"
    except llm.LLMError as e:
        return False, f"{config.BACKEND} / {config.MODEL} not reachable: {str(e)[:120]}"


def to_markdown(report: dict) -> str:
    t = report["unit_tests"]
    lines = [f"# GiSuN test report ({report['time']})", "",
             f"**Unit tests:** {'PASS' if t['ok'] else 'FAIL'}: {t['ran']} run, {t['failures']} failures, "
             f"{t['errors']} errors, {t['skipped']} skipped"]
    lines += [f"- {p}" for p in t["problems"]]
    lines += ["", f"**Model:** {report['model']}", ""]
    for path, g in report["gold"].items():
        lines += [f"## {path}", "",
                  f"{g['check']['items']} items, {g['check']['pairs']} labeled pairs, "
                  f"format {'OK' if g['check']['ok'] else 'BROKEN'}"]
        lines += [f"- {p}" for p in g["check"]["problems"][:20]]
        if not g.get("modes"):
            lines.append("")
            continue
        lines += ["", "| mode | F1 | accuracy | claim risk acc | not run | sec/answer |", "|---|---|---|---|---|---|"]
        for mode, m in g["modes"].items():
            lines.append(f"| {mode} | {m['f1']} | {m['accuracy']} | {m['claim_risk_acc']} | {m['not_run']} | {m['avg_seconds']} |")
        crits = sorted({c for m in g["modes"].values() for c in m["by_criterion"]})
        lines += ["", "F1 by criterion (n = gold pairs):", "",
                  "| mode | " + " | ".join(crits) + " |", "|---|" + "---|" * len(crits)]
        for mode, m in g["modes"].items():
            cells = [f"{m['by_criterion'][c]['f1']} (n={m['by_criterion'][c]['n']})" if c in m["by_criterion"] else "-"
                     for c in crits]
            lines.append(f"| {mode} | " + " | ".join(cells) + " |")
        lines += ["", f"Outputs: `{g['outputs']}`", ""]
    if report["regressions"]:
        lines += ["## Regressions", ""] + [f"- {r}" for r in report["regressions"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", nargs="+", default=None)
    ap.add_argument("--modes", nargs="+", default=None, choices=list(MODES),
                    help="default: rules_only, plus every model mode if the model answers")
    ap.add_argument("--skip_eval", action="store_true")
    ap.add_argument("--min_f1", type=float, default=None, help="fail if rules_only F1 is below this")
    a = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join("evaluation", "outputs", f"report_{stamp}")
    t0 = time.time()
    print("unit tests ...", flush=True)
    report = {"time": stamp, "unit_tests": run_unit_tests(), "gold": {}, "regressions": []}

    reachable, model_note = model_reachable() if not a.skip_eval else (False, "skipped")
    report["model"] = model_note
    modes = a.modes or (list(MODES) if reachable else ["rules_only"])
    if not reachable and any(MODES[m]["task"] for m in modes):
        print(f"warning: {model_note}; model modes will fall back to rules_only", file=sys.stderr)

    for path in a.gold or [p for p in DEFAULT_GOLD if os.path.exists(p)]:
        entry = {"check": check_gold(path)}
        report["gold"][path] = entry
        if a.skip_eval or not entry["check"]["ok"]:
            continue
        print(f"evaluating {path}: {', '.join(modes)} ...", flush=True)
        root = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0])
        entry["outputs"] = root
        entry["modes"] = ablate(path, modes, root)
        f1 = entry["modes"].get("rules_only", {}).get("f1")
        if a.min_f1 is not None and f1 is not None and f1 < a.min_f1:
            report["regressions"].append(f"{path}: rules_only F1 {f1} < {a.min_f1}")

    report["seconds"] = round(time.time() - t0, 1)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    md = to_markdown(report)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print(f"report: {out_dir}/report.md ({report['seconds']}s)")
    ok = report["unit_tests"]["ok"] and all(g["check"]["ok"] for g in report["gold"].values()) \
        and not report["regressions"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
