"""No-API collection: make a fill-in sheet, paste ChatGPT answers into it, import it as a dataset.

    python .../sheet.py make   [--out datasets/collected/chatgpt_web_sheet.md]
    python .../sheet.py import  datasets/collected/chatgpt_web_sheet.md [--model "ChatGPT web (GPT-5)"]
"""

import argparse
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(HERE, "..", "prompts.json")
START, END = "<!-- ANSWER START -->", "<!-- ANSWER END -->"


def make(out, prompts_path=PROMPTS):
    if os.path.exists(out):
        raise SystemExit(f"{out} exists; not overwriting pasted answers")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    parts = ["# Chatbot answers for GiSuN testing\n",
             "For each prompt: open a NEW ChatGPT chat, paste the prompt, copy the whole answer "
             "(the copy button under the answer), and paste it between the two markers. "
             "Leave the markers and the ### lines unchanged.\n"]
    for p in json.load(open(prompts_path)):
        parts.append(f"\n### {p['id']} | {p['category']}\n\n**Prompt:** {p['prompt']}\n\n{START}\n\n{END}\n")
    open(out, "w", encoding="utf-8").write("".join(parts))
    print(f"sheet written: {out}")


def imp(sheet, model, provider, prompts_path=PROMPTS):
    text = open(sheet, encoding="utf-8").read()
    prompts = {p["id"]: p for p in json.load(open(prompts_path))}
    items, empty = [], []
    for m in re.finditer(r"^### (\S+) \|.*?" + re.escape(START) + r"(.*?)" + re.escape(END), text, re.S | re.M):
        pid, answer = m.group(1), m.group(2).strip()
        if pid not in prompts:
            continue
        if not answer:
            empty.append(pid)
            continue
        p = prompts[pid]
        items.append({"id": pid, "category": p["category"], "domain": p["category"], "question": p["prompt"], "text": answer,
                      "provider": provider, "model": model, "collected_at": time.strftime("%Y-%m-%d")})
    out = os.path.splitext(sheet)[0] + ".json"
    json.dump(items, open(out, "w"), indent=1, ensure_ascii=False)
    print(f"{len(items)} answers -> {out}; still empty: {len(empty)} {empty[:10]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make"); m.add_argument("--out", default="datasets/collected/claude_sheet.md"); m.add_argument("--prompts", default=PROMPTS)
    i = sub.add_parser("import"); i.add_argument("sheet"); i.add_argument("--model", default="ChatGPT web")
    i.add_argument("--provider", default="chatgpt_web"); i.add_argument("--prompts", default=PROMPTS)
    a = ap.parse_args()
    make(a.out, a.prompts) if a.cmd == "make" else imp(a.sheet, a.model, a.provider, a.prompts)
