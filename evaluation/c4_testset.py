"""
C4 (overgeneralization) test set: a labeling workbook, a gold file to run GiSuN on, and the
agent's results written back into the workbook. Content: datasets/c4/c4_source.json.

1. build    workbook (Guide, Prompts, two label sheets, Key, Results, Summary) and
            datasets/c4/c4_intended.json, the same items with the author's intended labels
            (a smoke test you can run before anyone has labeled)
2. (both labelers fill in the yellow cells on Label_Answers and Label_Standalone, without
   opening the Key sheet; settle disagreements in Results > Adjudicated)
3. gold     labeled workbook -> datasets/c4/c4_gold.json (adjudicated label, else the label
            both of you gave; rows you disagree on and haven't settled are left out)
4. results  agent decisions from run_ablation batch folders -> the workbook's Results sheet;
            the Summary sheet recomputes precision / recall / F1 per mode and per category

    python -m evaluation.c4_testset build
    python -m evaluation.c4_testset gold --xlsx datasets/c4/C4_testset_labeled.xlsx
    python -m evaluation.run_ablation --gold datasets/c4/c4_gold.json --modes full task_only rules_only
    python -m evaluation.c4_testset results --xlsx datasets/c4/C4_testset_labeled.xlsx \
        --root evaluation/outputs/ablation_<model>_<time>
"""

import argparse
import json
import os
import random
import re
import sys

sys.path.insert(0, os.getcwd())
from gisun.preprocess import split_sentences

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

SOURCE = "datasets/c4/c4_source.json"
CHATGPT_RAW = "datasets/c4/chatgpt_raw.txt"  # real ChatGPT answers as pasted, one "### N question" block each
OUT_DIR = "datasets/c4"
# Ad text inside answer 9 that ends with a period, so the cleaning rules below would keep it
AD_LINES = {"For career planning, here’s one aptitude test option to explore matches."}
MODES = ["full", "task_only", "rules_only"]
F = "Arial"
HEAD = PatternFill("solid", fgColor="1F3864")
INPUT = PatternFill("solid", fgColor="FFF2CC")   # yellow = cells a person fills in
KEYFILL = PatternFill("solid", fgColor="F2F2F2")
THIN = Border(*(Side(style="thin", color="BFBFBF"),) * 4)
WRAP = Alignment(wrap_text=True, vertical="top")

CATEGORIES = {  # category -> (intended label, what it tests)
    "SWEEP-ABS": ("met", "sweeping claim with an absolute word (always, never, everyone, all)"),
    "SWEEP-GENERIC": ("met", "sweeping claim about a whole group with no absolute word; the word-list rule can't see it"),
    "SWEEP-SUPERLATIVE": ("met", "'the only way', 'the key', 'the best', 'guarantees'"),
    "TRUE-ABS": ("not_met", "absolute word, but literally true (math, science, definitions)"),
    "RULE": ("not_met", "absolute word describing a law, rule or requirement"),
    "SCOPED": ("not_met", "absolute word about a closed, stated group ('all 12 patients')"),
    "REPORTED": ("not_met", "a sweeping claim reported or rejected, not asserted (depends on the reported-arguments rule)"),
    "HEDGED": ("not_met", "hedged wording: may, some, often, tends to"),
    "PAIR-HEDGED": ("not_met", "hedged twin of a sweeping pair sentence"),
    "NEUTRAL": ("not_met", "ordinary specific or sourced sentence"),
    "REAL": ("", "real ChatGPT sentence: no intended label, your labels are the only gold"),
}
_ABS = re.compile(r"\b(always|never|every\w*|all|nobody|no one|none|completely|cannot|can't|don't|doesn't|nothing|equally)\b", re.I)
_SUPER = re.compile(r"\b(only|best|key|guarantee\w*)\b", re.I)
_HEADING = re.compile(r"^\*\*[^*]+\*\*$")  # a line that is only a bold heading


def _sweep_category(sentence: str) -> str:
    if _SUPER.search(sentence):
        return "SWEEP-SUPERLATIVE"
    return "SWEEP-ABS" if _ABS.search(sentence) else "SWEEP-GENERIC"


_END = re.compile(r"[.!?;][\"”’)]*$")


def clean_answer(text: str) -> tuple[str, list[str]]:
    """Drop what a copy from the ChatGPT page adds that isn't answer text. A line is kept only if it
    ends like a sentence; that removes headings, source chips ("PubMed", "+1"), image captions,
    one-cell-per-line tables and quiz widgets. Tab-separated tables keep their rows (each row is a
    claim) and lose their header. Returns the cleaned text and the removed lines, for the record."""
    kept, removed, prev_tab = [], [], False
    for line in text.splitlines():
        s = line.strip()
        if not s:
            prev_tab = False
            continue
        if "\t" in s:
            if prev_tab:
                kept.append(" | ".join(c.strip() for c in s.split("\t")))
            else:
                removed.append(s.replace("\t", " | ") + "  [table header]")
            prev_tab = True
            continue
        prev_tab = False
        if _END.search(s) and s not in AD_LINES:  # lead-ins ending in ":" don't match _END either
            kept.append(s)
        else:
            removed.append(s)
    return "\n".join(kept), removed


def load_chatgpt() -> list[dict]:
    """The real ChatGPT answers, cleaned. Empty if chatgpt_raw.txt doesn't exist yet."""
    if not os.path.exists(CHATGPT_RAW):
        return []
    parts = re.split(r"^### (\d+) (.*)$", open(CHATGPT_RAW, encoding="utf-8").read(), flags=re.M)[1:]
    answers = []
    for i in range(0, len(parts), 3):
        clean, removed = clean_answer(parts[i + 2])
        answers.append({"id": f"c4-c{int(parts[i]):02d}", "question": parts[i + 1].strip(), "raw": parts[i + 2].strip(),
                        "answer": clean, "removed": removed})
    return answers


def load_rows(src: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Sentence rows for the three label sheets. Every row carries its intended label and category
    (real ChatGPT rows have none)."""
    answer_rows = []
    for n, a in enumerate(src["answers"], 1):
        # Headings are skipped: they aren't claims (the pipeline's heading bug is tested separately)
        sentences = [s for s in split_sentences(a["answer"]) if not _HEADING.match(s)]
        for k, s in enumerate(sentences, 1):
            hit = [v for key, v in a["labels"].items() if key.lower() in s.lower()]
            label, cat, why = hit[0] if hit else ("not_met", "NEUTRAL", "")
            answer_rows.append({"row": f"A{n:02d}-{k:02d}", "set": "answer", "item": a["id"], "question": a["question"],
                                "previous": sentences[k - 2] if k > 1 else "", "sentence": s,
                                "intended": label, "category": cat, "why": why, "pair": ""})
    chatgpt_rows = []
    for a in load_chatgpt():
        # Questions ("Would you rather...?") and fragments under 3 words aren't claims to label
        sentences = [s for s in split_sentences(a["answer"]) if not s.endswith("?") and len(s.split()) >= 3]
        for k, s in enumerate(sentences, 1):
            chatgpt_rows.append({"row": f"C{a['id'][-2:]}-{k:02d}", "set": "chatgpt", "item": a["id"],
                                 "question": a["question"], "previous": sentences[k - 2] if k > 1 else "",
                                 "sentence": s, "intended": "", "category": "REAL", "why": "", "pair": ""})
    standalone = []
    for p in src["pairs"]:
        standalone.append({"set": "pair", "sentence": p["sweeping"], "intended": "met",
                           "category": _sweep_category(p["sweeping"]), "why": "sweeping half of a pair", "pair": p["id"]})
        standalone.append({"set": "pair", "sentence": p["hedged"], "intended": "not_met",
                           "category": "PAIR-HEDGED", "why": "hedged half of a pair", "pair": p["id"]})
    for t in src["traps"]:
        standalone.append({"set": "trap", "sentence": t["sentence"], "intended": CATEGORIES[t["category"]][0],
                           "category": t["category"], "why": t["why"], "pair": ""})
    # Fixed shuffle so the two halves of a pair aren't next to each other (labelers would compare them)
    random.Random(7).shuffle(standalone)
    for k, r in enumerate(standalone, 1):
        r["row"] = f"S{k:03d}"
    return answer_rows, chatgpt_rows, standalone


def _header(ws, cols, widths):
    for c, (name, w) in enumerate(zip(cols, widths), 1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font, cell.fill, cell.alignment, cell.border = Font(name=F, bold=True, color="FFFFFF"), HEAD, WRAP, THIN
        ws.column_dimensions[cell.column_letter].width = w
    ws.freeze_panes = "A2"


def _put(ws, r, c, v, fill=None, bold=False):
    cell = ws.cell(row=r, column=c, value=v)
    cell.font, cell.alignment, cell.border = Font(name=F, bold=bold), WRAP, THIN
    if fill:
        cell.fill = fill
    return cell


def _label_dropdown(ws, ref):
    dv = DataValidation(type="list", formula1='"met,not_met,unsure"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(ref)


def build(src: dict, xlsx: str):
    answer_rows, chatgpt_rows, standalone = load_rows(src)
    chatgpt = {a["id"]: a for a in load_chatgpt()}
    wb = Workbook()

    # --- Guide
    g = wb.active
    g.title = "Guide"
    g.column_dimensions["A"].width = 26
    g.column_dimensions["B"].width = 100
    guide = [
        ("C4 test set", ""),
        ("Criterion", "C4 overgeneralization: does the sentence make a sweeping claim (always, never, everyone, "
                      "or a claim about a whole group) that the evidence can't support?"),
        ("Label met", "The sentence itself asserts a sweeping claim that goes beyond what is known."),
        ("Label not_met", "Hedged wording; an absolute that is literally true (math, science, definitions); a rule or "
                          "law; an absolute about a closed group (\"all 12 patients\"); or a sweeping claim the "
                          "sentence only reports or rejects (\"critics argue...\", \"the myth that...\")."),
        ("Label unsure", "Use it rarely, and say why in Notes."),
        ("Judge only C4", "If the sentence has a different problem (no source, loaded word, causal claim), note it in "
                          "Notes but label C4 only."),
        ("Where to type", "Only the yellow cells: your own column on Label_Answers and Label_Standalone (dropdown), "
                          "Notes, and later Results > Adjudicated. Everything else is filled in or computed."),
        ("Don't open Key", "The Key sheet has the intended labels. Label first, independently, then compare."),
        ("Example row", "Sentence: \"Remote work always increases productivity.\"  Label: met.  "
                        "Note: \"always\" turns a mixed finding into a rule."),
        ("Example row", "Sentence: \"Every week has seven days.\"  Label: not_met.  Note: true by definition."),
        ("Sets", "Label_Answers: 16 ChatGPT-style answers written for this test, sentence by sentence (question "
                 "and previous sentence for context). Label_ChatGPT: the real ChatGPT answers to the same 16 "
                 "questions, cleaned of page elements (headings, source chips, image captions, the ad); these "
                 "have no intended label. Label_Standalone: 40 sweeping/hedged pairs and 40 traps, shuffled."),
        ("Source", src["meta"]["written_by"]),
        ("Afterwards", "python -m evaluation.c4_testset gold, run GiSuN, then python -m evaluation.c4_testset "
                       "results. The Summary sheet then shows precision, recall and F1 per mode and per category."),
    ]
    for r, (a, b) in enumerate(guide, 1):
        _put(g, r, 1, a, bold=True)
        _put(g, r, 2, b)
    g["A1"].font = Font(name=F, bold=True, size=14)
    r = len(guide) + 2
    _put(g, r, 1, "Category", bold=True)
    _put(g, r, 2, "What it tests (intended label)", bold=True)
    for cat, (label, desc) in CATEGORIES.items():
        r += 1
        _put(g, r, 1, cat)
        _put(g, r, 2, f"{desc} ({label})")

    # --- Prompts
    p = wb.create_sheet("Prompts")
    _header(p, ["Prompt ID", "Group", "Question", "Answer", "Answer source", "Real ChatGPT answer (cleaned)",
                "Removed when cleaning"], [10, 18, 34, 70, 22, 70, 40])
    for r, a in enumerate(src["answers"], 2):
        real = chatgpt.get(f"c4-c{r - 1:02d}")  # same question order: answer n <-> ChatGPT answer n
        for c, v in enumerate([a["id"], a["group"], a["question"], a["answer"], "written in ChatGPT style (Claude)",
                               real["answer"] if real else None,
                               "\n".join(real["removed"]) if real else None], 1):
            _put(p, r, c, v)

    # --- Label sheets
    la = wb.create_sheet("Label_Answers")
    _header(la, ["Row ID", "Prompt ID", "Question", "Previous sentence", "Sentence", "Gideon C4", "Suning C4", "Notes"],
            [10, 10, 28, 40, 60, 12, 12, 30])
    for r, row in enumerate(answer_rows, 2):
        for c, v in enumerate([row["row"], row["item"], row["question"], row["previous"], row["sentence"]], 1):
            _put(la, r, c, v)
        for c in (6, 7, 8):
            _put(la, r, c, None, INPUT)
    _label_dropdown(la, f"F2:G{len(answer_rows) + 1}")

    # Real ChatGPT answers: same columns as Label_Answers
    lc = wb.create_sheet("Label_ChatGPT")
    _header(lc, ["Row ID", "Answer ID", "Question", "Previous sentence", "Sentence", "Gideon C4", "Suning C4", "Notes"],
            [10, 10, 28, 40, 60, 12, 12, 30])
    for r, row in enumerate(chatgpt_rows, 2):
        for c, v in enumerate([row["row"], row["item"], row["question"], row["previous"], row["sentence"]], 1):
            _put(lc, r, c, v)
        for c in (6, 7, 8):
            _put(lc, r, c, None, INPUT)
    if chatgpt_rows:
        _label_dropdown(lc, f"F2:G{len(chatgpt_rows) + 1}")

    ls = wb.create_sheet("Label_Standalone")
    _header(ls, ["Row ID", "Sentence", "Gideon C4", "Suning C4", "Notes"], [10, 80, 12, 12, 30])
    for r, row in enumerate(standalone, 2):
        _put(ls, r, 1, row["row"])
        _put(ls, r, 2, row["sentence"])
        for c in (3, 4, 5):
            _put(ls, r, c, None, INPUT)
    _label_dropdown(ls, f"C2:D{len(standalone) + 1}")

    # --- Key (intended labels, same row order as Results)
    k = wb.create_sheet("Key")
    _header(k, ["Row ID", "Set", "Category", "Intended C4", "Pair ID", "Why"], [10, 10, 20, 12, 8, 60])
    rows = answer_rows + chatgpt_rows + standalone
    for r, row in enumerate(rows, 2):
        for c, v in enumerate([row["row"], row["set"], row["category"], row["intended"] or None, row["pair"], row["why"]], 1):
            _put(k, r, c, v, KEYFILL)

    # --- Results: one row per sentence; labels pulled from the label sheets, agent columns filled by `results`
    res = wb.create_sheet("Results")
    _header(res, ["Row ID", "Set", "Category", "Intended", "Gideon", "Suning", "Adjudicated", "Final gold",
                  "Both labeled", "Agree", "Agent full", "Agent task_only", "Agent rules_only",
                  "Correct full", "Correct task_only", "Correct rules_only"],
            [10, 9, 18, 10, 10, 10, 12, 10, 8, 7, 11, 11, 11, 9, 9, 9])
    for r, row in enumerate(rows, 2):
        # Results row r and the row it labels on its label sheet (each sheet starts at row 2)
        if row["set"] == "answer":
            src_ref = (f"Label_Answers!F{r}", f"Label_Answers!G{r}")
        elif row["set"] == "chatgpt":
            lr = r - len(answer_rows)
            src_ref = (f"Label_ChatGPT!F{lr}", f"Label_ChatGPT!G{lr}")
        else:
            lr = r - len(answer_rows) - len(chatgpt_rows)
            src_ref = (f"Label_Standalone!C{lr}", f"Label_Standalone!D{lr}")
        vals = [row["row"], f"=Key!B{r}", f"=Key!C{r}", f'=IF(Key!D{r}="","",Key!D{r})',
                f'=IF({src_ref[0]}="","",{src_ref[0]})', f'=IF({src_ref[1]}="","",{src_ref[1]})', None,
                f'=IF(G{r}<>"",G{r},IF(AND(E{r}<>"",E{r}=F{r},E{r}<>"unsure"),E{r},""))',
                f'=IF(AND(OR(E{r}="met",E{r}="not_met"),OR(F{r}="met",F{r}="not_met")),1,0)',
                f'=IF(I{r}=1,IF(E{r}=F{r},1,0),"")', None, None, None]
        # "undetermined" and "not_run" count as not flagged
        vals += [f'=IF(OR({c}{r}="",H{r}=""),"",IF(({c}{r}="met")=(H{r}="met"),1,0))' for c in "KLM"]
        for c, v in enumerate(vals, 1):
            _put(res, r, c, v, INPUT if c == 7 else None)
    _label_dropdown(res, f"G2:G{len(rows) + 1}")
    last = len(rows) + 1

    # --- Summary (all formulas over Results)
    s = wb.create_sheet("Summary")
    s.column_dimensions["A"].width = 30
    for col in "BCDEFGHI":
        s.column_dimensions[col].width = 13
    R = lambda col: f"Results!${col}$2:${col}${last}"
    _put(s, 1, 1, "Labeler agreement", bold=True)
    agree = [("Rows both labeled (met / not_met)", f"=SUM({R('I')})"),
             ("Rows you agree on", f"=SUM({R('J')})"),
             ("Agreement", "=IFERROR(B3/B2,\"\")"),
             ("Gideon met (both-labeled rows)", f'=COUNTIFS({R("I")},1,{R("E")},"met")'),
             ("Suning met (both-labeled rows)", f'=COUNTIFS({R("I")},1,{R("F")},"met")'),
             ("Chance agreement", '=IFERROR((B5*B6+(B2-B5)*(B2-B6))/B2^2,"")'),
             ("Cohen's kappa", '=IFERROR((B4-B7)/(1-B7),"")'),
             ("Rows with a final gold label", f'=COUNTIF({R("H")},"met")+COUNTIF({R("H")},"not_met")')]
    for r, (a, f) in enumerate(agree, 2):
        _put(s, r, 1, a)
        _put(s, r, 2, f)
    s["B4"].number_format = s["B8"].number_format = s["B7"].number_format = "0.00"

    r0 = 12
    _put(s, r0, 1, "Agent vs final gold", bold=True)
    for c, h in enumerate(["Mode", "TP", "FP", "FN", "TN", "Precision", "Recall", "F1", "Accuracy"], 1):
        _put(s, r0 + 1, c, h, bold=True)
    for i, (mode, col) in enumerate(zip(MODES, "KLM")):
        r = r0 + 2 + i
        miss = lambda gold: "+".join(f'COUNTIFS({R("H")},"{gold}",{R(col)},"{d}")' for d in ("not_met", "undetermined", "not_run"))
        cells = [mode, f'=COUNTIFS({R("H")},"met",{R(col)},"met")', f'=COUNTIFS({R("H")},"not_met",{R(col)},"met")',
                 f"={miss('met')}", f"={miss('not_met')}",
                 f'=IFERROR(B{r}/(B{r}+C{r}),"")', f'=IFERROR(B{r}/(B{r}+D{r}),"")',
                 f'=IFERROR(2*F{r}*G{r}/(F{r}+G{r}),"")', f'=IFERROR((B{r}+E{r})/SUM(B{r}:E{r}),"")']
        for c, v in enumerate(cells, 1):
            cell = _put(s, r, c, v)
            if c >= 6:
                cell.number_format = "0.00"

    r0 = 18
    _put(s, r0, 1, "Accuracy by category (share of rows the agent got right)", bold=True)
    for c, h in enumerate(["Category", "Rows", "Intended", "Labelers agree", "full", "task_only", "rules_only"], 1):
        _put(s, r0 + 1, c, h, bold=True)
    for i, (cat, (label, _)) in enumerate(CATEGORIES.items()):
        r = r0 + 2 + i
        acc = lambda col: f'=IFERROR(SUMIFS({R(col)},{R("C")},A{r})/COUNTIFS({R("C")},A{r},{R(col)},">=0"),"")'
        cells = [cat, f'=COUNTIF({R("C")},A{r})', label,
                 f'=IFERROR(SUMIFS({R("J")},{R("C")},A{r})/COUNTIFS({R("C")},A{r},{R("I")},1),"")',
                 acc("N"), acc("O"), acc("P")]
        for c, v in enumerate(cells, 1):
            cell = _put(s, r, c, v)
            if c >= 4:
                cell.number_format = "0.00"

    # Pair test: a pair counts only if the sweeping half is flagged and the hedged half is not
    r0 = r0 + 3 + len(CATEGORIES)
    _put(s, r0, 1, "Pair test (both halves right, full mode)", bold=True)
    pair_rows = {}
    for idx, row in enumerate(rows, 2):
        if row["pair"]:
            pair_rows.setdefault(row["pair"], {})[row["intended"]] = idx
    first = r0 + 2
    _put(s, r0 + 1, 1, "Pair", bold=True)
    _put(s, r0 + 1, 2, "Both right", bold=True)
    for i, (pid, d) in enumerate(sorted(pair_rows.items())):
        r = first + i
        _put(s, r, 1, pid)
        _put(s, r, 2, f'=IF(OR(Results!N{d["met"]}="",Results!N{d["not_met"]}=""),"",'
                      f'IF(AND(Results!N{d["met"]}=1,Results!N{d["not_met"]}=1),1,0))')
    endp = first + len(pair_rows) - 1
    _put(s, r0, 4, "Pairs both right", bold=True)
    _put(s, r0, 5, f'=IFERROR(SUM(B{first}:B{endp})/COUNT(B{first}:B{endp}),"")').number_format = "0.00"

    os.makedirs(os.path.dirname(xlsx), exist_ok=True)
    wb.save(xlsx)
    return answer_rows, chatgpt_rows, standalone


def to_gold(answer_rows, chatgpt_rows, standalone, label_of, src) -> list[dict]:
    """Gold-format items: each answer (written or real ChatGPT, cleaned) is one item, each standalone
    sentence is its own item."""
    questions = {a["id"]: a for a in src["answers"] + load_chatgpt()}
    items = {}
    for row in answer_rows + chatgpt_rows:
        label = label_of(row)
        item = items.setdefault(row["item"], {"id": row["item"], "question": questions[row["item"]]["question"],
                                              "text": questions[row["item"]]["answer"], "domain": "c4_test",
                                              "source": f"c4_testset:{row['set']}", "labels": {}})
        if label:
            item["labels"][row["sentence"]] = {"C4": label}
    for row in standalone:
        label = label_of(row)
        if label:
            items[row["row"]] = {"id": row["row"], "question": "", "text": row["sentence"], "domain": "c4_test",
                                 "source": f"c4_testset:{row['set']}", "labels": {row["sentence"]: {"C4": label}}}
    return [i for i in items.values() if i["labels"]]


def _final_labels(xlsx: str) -> dict:
    """Row ID -> final label, computed here (not read from formulas, which have no cached values
    until the file is opened and saved in Excel or Google Sheets)."""
    wb = load_workbook(xlsx)
    labels = {}
    for name, (g, s) in {"Label_Answers": (6, 7), "Label_ChatGPT": (6, 7), "Label_Standalone": (3, 4)}.items():
        if name not in wb.sheetnames:  # a workbook built before the ChatGPT answers were added
            continue
        for row in wb[name].iter_rows(min_row=2, values_only=True):
            if row[0]:
                labels[row[0]] = [row[g - 1], row[s - 1], None]
    for row in wb["Results"].iter_rows(min_row=2, values_only=True):
        if row[0] in labels:
            labels[row[0]][2] = row[6]
    final = {}
    for rid, (g, s, adj) in labels.items():
        if adj in ("met", "not_met"):
            final[rid] = adj
        elif g == s and g in ("met", "not_met"):
            final[rid] = g
    return final


def results(xlsx: str, root: str):
    """Write each mode's C4 decision per sentence into Results (columns K-M)."""
    src = json.load(open(SOURCE, encoding="utf-8"))
    answer_rows, chatgpt_rows, standalone = load_rows(src)
    wb = load_workbook(xlsx)
    ws = wb["Results"]
    for mode, col in zip(MODES, (11, 12, 13)):
        batch = os.path.join(root, mode)
        if not os.path.isdir(batch):
            continue
        for r, row in enumerate(answer_rows + chatgpt_rows + standalone, 2):
            item_id = row["item"] if row["set"] in ("answer", "chatgpt") else row["row"]
            path = os.path.join(batch, f"{item_id}.json")
            if not os.path.exists(path):
                continue
            result = json.load(open(path, encoding="utf-8"))
            claim = next((c for c in result["claims"] if row["sentence"].lower() in c["sentence"].lower()), None)
            pred = claim["criteria"].get("C4") if claim else None
            ws.cell(row=r, column=col, value=pred["decision"] if pred else "not_run")
    wb.save(xlsx)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["build", "gold", "results"])
    ap.add_argument("--xlsx", default=os.path.join(OUT_DIR, "C4_testset.xlsx"))
    ap.add_argument("--root", help="results: the run_ablation output folder (contains full/, task_only/, rules_only/)")
    a = ap.parse_args()
    src = json.load(open(SOURCE, encoding="utf-8"))
    if a.command == "build":
        answer_rows, chatgpt_rows, standalone = build(src, a.xlsx)
        # Real ChatGPT rows have no intended label, so the smoke-test file leaves them out
        intended = to_gold(answer_rows, chatgpt_rows, standalone, lambda row: row["intended"], src)
        json.dump(intended, open(os.path.join(OUT_DIR, "c4_intended.json"), "w"), indent=2, ensure_ascii=False)
        # The cleaned ChatGPT answers next to the raw ones, with every removed line, for the record
        json.dump(load_chatgpt(), open(os.path.join(OUT_DIR, "chatgpt_clean.json"), "w"), indent=2, ensure_ascii=False)
        print(f"{a.xlsx}: {len(answer_rows)} written-answer sentences, {len(chatgpt_rows)} real ChatGPT sentences, "
              f"{len(standalone)} standalone; {OUT_DIR}/c4_intended.json: {len(intended)} items")
    elif a.command == "gold":
        answer_rows, chatgpt_rows, standalone = load_rows(src)
        final = _final_labels(a.xlsx)
        gold = to_gold(answer_rows, chatgpt_rows, standalone, lambda row: final.get(row["row"]), src)
        json.dump(gold, open(os.path.join(OUT_DIR, "c4_gold.json"), "w"), indent=2, ensure_ascii=False)
        print(f"{OUT_DIR}/c4_gold.json: {len(final)} labeled rows in {len(gold)} items")
    else:
        results(a.xlsx, a.root)
        print(f"wrote agent decisions into {a.xlsx} (Results sheet)")
