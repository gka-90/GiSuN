"""
Annotation workflow for the gold set (open problems #9, #10). Guidelines: datasets/ANNOTATION_GUIDE.md.

1. sheet   one blank labeling file per annotator, from the collected candidates
           (evaluation/collect.py). Every factual sentence the pipeline would judge gets the
           criteria to decide, all set to null: no machine suggestions, so the labels are not
           anchored on what the rules or the model already say.
2. (both annotators fill in their own file independently: "met" / "not_met" / "undetermined")
3. status  how much of each file is labeled
4. merge   agreement (Cohen's kappa) + gold set: pairs both of you labeled the same go straight
           into the gold set, the rest go to an adjudication file. Fill in "final" there
           together, run merge again, and the adjudicated pairs join the gold set.

    python -m evaluation.annotate sheet --candidates datasets/candidates_wildchat.json datasets/candidates_hc3.json --annotators gideon partner
    python -m evaluation.annotate status
    python -m evaluation.annotate merge --a datasets/annotation/labels_gideon.json --b datasets/annotation/labels_partner.json

Output gold format = datasets/gold_example.json (labels: {sentence: {criterion: decision}}),
plus "domain" and "source" per item, so evaluation/evaluate.py reads it unchanged.
"""

import argparse
import glob
import json
import os

from evaluation.agreement import agreement
from gisun.criteria import DECISIONS
from gisun.preprocess import preprocess

ANNOTATION_DIR = os.path.join("datasets", "annotation")
OPEN = ["C3", "C4", "C5", "C6"]  # wording criteria: any factual sentence can have these problems


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    return path


def criteria_for(claim: dict) -> list[str]:
    """C1 for quantitative sentences, C2 for numbers a source could confirm, C3-C6 for every sentence."""
    out = []
    if claim["stat_values"] or "quantitative" in claim["signals"]:
        out.append("C1")
    if claim["checkable_values"]:
        out.append("C2")
    return out + OPEN


def make_sheet(candidates: list[dict]) -> list[dict]:
    items = []
    for c in candidates:
        ctx = preprocess(c["text"], c.get("question", ""), all_sentences=True)  # what the model modes judge
        items.append({"id": c["id"], "domain": c.get("domain"), "question": c.get("question", ""),
                      "text": c["text"], "source": c.get("source"),
                      "labels": {cl["sentence"]: {cid: None for cid in criteria_for(cl)} for cl in ctx.claims},
                      "notes": ""})
    return items


def status(path: str) -> dict:
    values = [d for item in _load(path) for crits in item["labels"].values() for d in crits.values()]
    bad = sorted({d for d in values if d is not None and d not in DECISIONS})
    done = sum(d in DECISIONS for d in values)
    return {"file": path, "labeled": done, "total": len(values),
            "percent": round(100 * done / max(len(values), 1), 1), "invalid_values": bad}


def merge(path_a: str, path_b: str, adjudication_path: str, gold_path: str) -> dict:
    a, b = _load(path_a), _load(path_b)
    b_by_id = {item["id"]: item for item in b}
    adjudicated = {}
    if os.path.exists(adjudication_path):
        for row in _load(adjudication_path):
            if row.get("final") in DECISIONS:
                adjudicated[(row["item"], row["sentence"], row["criterion"])] = row["final"]

    gold, open_rows = [], []
    for item in a:
        other = b_by_id.get(item["id"])
        if other is None:
            continue
        labels = {}
        for sentence, crits in item["labels"].items():
            for cid, da in crits.items():
                db = other["labels"].get(sentence, {}).get(cid)
                if da not in DECISIONS or db not in DECISIONS:
                    continue  # one of you hasn't labeled it yet
                key = (item["id"], sentence, cid)
                final = da if da == db else adjudicated.get(key)
                if final is None:
                    open_rows.append({"item": item["id"], "sentence": sentence, "criterion": cid,
                                      "a": da, "b": db, "final": None})
                else:
                    labels.setdefault(sentence, {})[cid] = final
        if labels:
            gold.append({"id": item["id"], "domain": item.get("domain"), "question": item.get("question", ""),
                         "text": item["text"], "source": item.get("source"), "labels": labels})

    _save(gold, gold_path)
    _save(open_rows, adjudication_path)
    pairs = sum(len(c) for g in gold for c in g["labels"].values())
    return {"agreement": {k: v for k, v in agreement(path_a, path_b).items() if k != "disagreements"},
            "gold": {"path": gold_path, "items": len(gold), "pairs": pairs},
            "to_adjudicate": {"path": adjudication_path, "pairs": len(open_rows)}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--candidates", nargs="+", default=[os.path.join("datasets", "candidates.json")])
    s.add_argument("--annotators", nargs="+", required=True)
    s.add_argument("--force", action="store_true", help="overwrite existing label files")
    st = sub.add_parser("status")
    st.add_argument("files", nargs="*")
    m = sub.add_parser("merge")
    m.add_argument("--a", required=True)
    m.add_argument("--b", required=True)
    m.add_argument("--adjudication", default=os.path.join(ANNOTATION_DIR, "adjudication.json"))
    m.add_argument("--gold", default=os.path.join("datasets", "gold.json"))
    args = ap.parse_args()

    if args.cmd == "sheet":
        sheet = make_sheet([c for path in args.candidates for c in _load(path)])
        for name in args.annotators:
            path = os.path.join(ANNOTATION_DIR, f"labels_{name}.json")
            if os.path.exists(path) and not args.force:
                print(f"skip {path}: exists (use --force to overwrite someone's labels)")
                continue
            _save(sheet, path)
            print(f"{path}: {len(sheet)} items, {status(path)['total']} decisions to make")
    elif args.cmd == "status":
        for path in args.files or sorted(glob.glob(os.path.join(ANNOTATION_DIR, "labels_*.json"))):
            print(json.dumps(status(path), ensure_ascii=False))
    else:
        print(json.dumps(merge(args.a, args.b, args.adjudication, args.gold), indent=2, ensure_ascii=False))
