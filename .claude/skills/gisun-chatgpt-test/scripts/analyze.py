"""Run GiSuN over real ChatGPT answers and summarize (no labels needed)."""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.getcwd())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--mode", default="rules_only")
    a = ap.parse_args()
    if a.mode == "rules_only":
        os.environ["GISUN_BACKEND"] = "none"
    else:
        from gisun import llm
        try:
            llm.chat([{"role": "user", "content": "ping"}])
        except Exception as e:
            sys.exit(f"model unreachable ({e}); --mode {a.mode} would silently fall back to rules. Start Ollama or the HPC tunnel.")
    from gisun.pipeline import run

    rows, errors = [], []
    for path in a.files:
        for it in json.load(open(path, encoding="utf-8")):
            try:
                r = run(it["text"], it.get("question", ""), mode=a.mode, keep_trace=False)
            except Exception as e:
                errors.append({"id": it["id"], "error": f"{type(e).__name__}: {e}"})
                continue
            rows.append({"id": it["id"], "domain": it.get("domain", "?"), "level": r["response"]["level"],
                         "claims": [{"sentence": c["sentence"], "risk": c["score"]["risk"],
                                     "criteria": {k: v["decision"] for k, v in c["criteria"].items()}}
                                    for c in r["claims"]],
                         "flags": [(f["type"], f.get("category", ""), f["matched_value"]) for f in r["flags"]]})

    by_dom = defaultdict(list)
    for r in rows:
        by_dom[r["domain"]].append(r)
    domains = {d: {"answers": len(rs), "avg_claims": round(sum(len(r["claims"]) for r in rs) / len(rs), 1),
                   **{lv: sum(r["level"] == lv for r in rs) for lv in ("high", "medium", "low")}}
               for d, rs in sorted(by_dom.items())}
    terms = Counter(f[2].lower() for r in rows for f in r["flags"] if f[0] == "bias_framing")
    crit = Counter((k, v) for r in rows for c in r["claims"] for k, v in c["criteria"].items())
    examples = defaultdict(list)
    for r in rows:
        for c in r["claims"]:
            for k, v in c["criteria"].items():
                if v == "met" and len(examples[k]) < 3:
                    examples[k].append(f"{r['id']}: {c['sentence'][:180]}")
    out = {"mode": a.mode, "answers": len(rows), "errors": errors, "by_domain": domains,
           "top_bias_terms": terms.most_common(15),
           "criteria": {f"{k} {v}": n for (k, v), n in sorted(crit.items())},
           "met_examples": dict(examples), "answers_detail": rows}
    os.makedirs("test_reports", exist_ok=True)
    tag = os.environ.get("GISUN_MODEL", "").split("/")[-1].replace(":", "-") if a.mode != "rules_only" else ""
    base = os.path.join("test_reports", f"chatgpt_{a.mode}" + (f"_{tag}" if tag else ""))
    json.dump(out, open(base + ".json", "w"), indent=1, ensure_ascii=False)
    md = [f"# GiSuN on real ChatGPT answers ({a.mode})", f"{len(rows)} answers, {len(errors)} errors", "",
          "| domain | answers | avg claims | high | medium | low |", "|---|---|---|---|---|---|"]
    md += [f"| {d} | {v['answers']} | {v['avg_claims']} | {v['high']} | {v['medium']} | {v['low']} |" for d, v in domains.items()]
    md += ["", "## Decisions", ""] + [f"- {k}: {n}" for k, n in out["criteria"].items()]
    md += ["", "## Most-flagged terms", ""] + [f"- {t}: {n}" for t, n in out["top_bias_terms"]]
    md += ["", "## Examples of met", ""] + [f"- **{k}** {e}" for k, es in examples.items() for e in es]
    open(base + ".md", "w").write("\n".join(md))
    print("\n".join(md[:40]))
    print(f"\nfull report: {base}.json")


if __name__ == "__main__":
    main()
