"""Ask each question in a fresh `codex exec` session and save the answers in gold-set format."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

INSTRUCTION = ("Answer the following question the way a general-purpose AI chatbot would answer a user. "
               "Reply with the answer only. Do not run commands, read or write files, or mention this "
               "instruction.\n\nQuestion: ")


def ask(question, model, timeout):
    with tempfile.TemporaryDirectory() as empty:
        out = os.path.join(empty, "answer.md")
        cmd = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
               "-C", empty, "-o", out]
        if model:
            cmd += ["--model", model]
        cmd.append(INSTRUCTION + question)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=empty)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout).strip()[-400:])
        text = open(out, encoding="utf-8").read().strip() if os.path.exists(out) else ""
        if not text:
            raise RuntimeError("empty answer")
        return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", default="datasets/prompts_same_as_candidates.json")
    ap.add_argument("--out", default=f"datasets/collected/codex_latest_{time.strftime('%Y-%m-%d')}.json")
    ap.add_argument("--model")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()
    if not shutil.which("codex"):
        sys.exit("codex is not installed or not on PATH (npm install -g @openai/codex, then codex login)")

    prompts = json.load(open(a.prompts, encoding="utf-8"))
    done = json.load(open(a.out, encoding="utf-8")) if os.path.exists(a.out) else []
    have = {d["id"] for d in done}
    todo = [p for p in prompts if p["id"] not in have][: a.limit]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    failed = []
    for i, p in enumerate(todo, 1):
        try:
            text = ask(p["prompt"], a.model, a.timeout)
        except Exception as e:
            failed.append(p["id"])
            print(f"[{i}/{len(todo)}] {p['id']} FAILED: {e}")
            continue
        done.append({"id": p["id"], "category": p.get("category", ""), "domain": p.get("category", ""),
                     "question": p["prompt"], "text": text, "provider": "codex_exec",
                     "model": a.model or "codex default", "collected_at": time.strftime("%Y-%m-%d %H:%M")})
        json.dump(done, open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"[{i}/{len(todo)}] {p['id']} ok ({len(text)} chars)")
    print(f"\n{len(done)} answers in {a.out}; failed this run: {failed or 'none'}")


if __name__ == "__main__":
    main()
