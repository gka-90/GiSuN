"""
Label the agent's decisions to find what to fix in the agent.

    python -m evaluation.make_agent_worksheet \
        --agent test_reports/chatgpt_full_Qwen2.5-32B-Instruct-AWQ.json \
        --answers datasets/candidates_wildchat.json datasets/candidates_hc3.json \
        [--rules test_reports/chatgpt_rules_only.json] \
        --out test_reports/agent_worksheet.xlsx

Row order (label top-down; you can stop after group 2):
  1  agent said met            -> is it a false positive?
  2  agent said not_met / didn't run, but the rules flagged it -> is it a miss?
  3  agent undetermined
  4  everything else the agent said not_met (spot-check for misses)
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from gisun.preprocess import split_sentences
from gisun.tools.attribution import find_attribution

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

CRIT = {"C1": "Statistic with no specific source nearby?",
        "C2": "Does a reliable source contradict the number?",
        "C3": "Slanted / loaded wording where neutral would do?",
        "C4": "Sweeping absolute claim the evidence can't support?",
        "C5": "'Experts say' instead of a named source?",
        "C6": "Cause-and-effect stated without evidence?"}
GROUP = {1: "P1 agent: met", 2: "P2 agent: undetermined", 3: "P3 agent: not_met"}
ERRORS = ["FP-SOURCE", "FP-CITATION", "FP-ADVICE", "FP-COMMON", "FP-NEUTRAL", "FP-ATTRIBUTED",
          "FP-NOT-STAT", "FP-OTHER", "MISS-JUDGED"]
ERR_DESC = {
    "FP-SOURCE": "A named source is in the sentence or just before it, but the agent said 'no source'",
    "FP-CITATION": "The 'sentence' is a citation or reference line, not a claim",
    "FP-ADVICE": "Advice or politeness ('always consult a doctor') treated as an overgeneralization",
    "FP-COMMON": "Common knowledge that needs no source or evidence",
    "FP-NEUTRAL": "Neutral or academic wording treated as loaded language",
    "FP-ATTRIBUTED": "The view is clearly attributed ('critics argue') and reported, not asserted",
    "FP-NOT-STAT": "The number is not a statistic (a year, date, rank or count of items)",
    "FP-OTHER": "Another false positive: explain in Notes",
    "MISS-JUDGED": "A real problem the agent called not_met or undetermined",
}
F = "Arial"


def load(path):
    out = {}
    if path:
        for r in json.load(open(path, encoding="utf-8"))["answers_detail"]:
            for c in r["claims"]:
                for k, v in c["criteria"].items():
                    out[(r["id"], c["sentence"], k)] = (r.get("domain", ""), v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    ap.add_argument("--rules", help="unused; kept for compatibility")
    ap.add_argument("--answers", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--keys", help="JSON list of [answer_id, sentence, criterion, shared] to keep (for splitting work)")
    a = ap.parse_args()
    agent, rules = load(a.agent), load(a.rules)
    items = {it["id"]: it for p in a.answers for it in json.load(open(p, encoding="utf-8"))}
    q = {k: v.get("question", "") for k, v in items.items()}
    sents = {k: split_sentences(v["text"]) for k, v in items.items()}

    def before(aid, sent, n=2):
        ss = sents.get(aid, [])
        for i, x in enumerate(ss):
            if x == sent or sent in x or x in sent:
                return " / ".join(ss[max(0, i - n):i])
        return ""

    def source_note(aid, sent):
        hits = [find_attribution(x)["source_text"] for x in [sent] + before(aid, sent).split(" / ") if x]
        hits = [h for h in hits if h]
        return "; ".join(dict.fromkeys(hits)) if hits else "none found"

    rows = []
    for key, (dom, v) in agent.items():  # priority comes only from the agent's decision
        g = 1 if v == "met" else 2 if v == "undetermined" else 3
        rows.append((g, key[0], key[2], dom, key[1], v))
    rows.sort(key=lambda r: (r[0], r[2], r[1]))
    if a.keys:
        keep = {(k[0], k[1], k[2]): k[3] for k in json.load(open(a.keys, encoding="utf-8"))}
        rows = [r for r in rows if (r[1], r[4], r[2]) in keep]
        shared = {k for k, v in keep.items() if v}
        rows.sort(key=lambda r: ((r[1], r[4], r[2]) not in shared, r[0], r[2], r[1]))  # shared rows first
    else:
        shared = set()

    wb = Workbook()
    ans = wb.create_sheet("Answers")
    ans.append(["Answer ID", "Domain", "Question", "Full answer (as ChatGPT wrote it)"])
    answer_row = {}
    for k, (aid, it) in enumerate(sorted(items.items()), start=2):
        ans.append([aid, it.get("domain", ""), it.get("question", ""), it["text"][:32000]])
        answer_row[aid] = k
    ws = wb.active
    ws.title = "Label"
    ws.append(["#", "Group", "Answer ID", "Domain", "Question", "Previous 2 sentences", "Sentence",
               "Named source nearby (auto)", "Criterion", "Criterion question", "Agent decision", "Human label",
               "Notes (why is the agent wrong?)", "Agent correct?", "Error type", "Full answer",
               "Error category"])
    for i, (g, aid, crit, dom, sent, v) in enumerate(rows, start=2):
        ws.append([i - 1, GROUP[g] + (" | SHARED" if (aid, sent, crit) in shared else ""), aid, dom, q.get(aid, ""), before(aid, sent), sent, source_note(aid, sent),
                   crit, CRIT.get(crit, ""), v, None, None,
                   f'=IF(OR(L{i}="",L{i}="unsure"),"",IF(K{i}=L{i},1,IF(AND(K{i}="not run",L{i}="not_met"),1,0)))',
                   f'=IF(OR(L{i}="",L{i}="unsure"),"",IF(AND(K{i}="met",L{i}="not_met"),"false positive",'
                   f'IF(AND(K{i}<>"met",L{i}="met"),"miss","")))',
                   "open" if aid in items else "", None])
        if aid in items:
            ws.cell(i, 16).hyperlink = f"#'Answers'!A{answer_row[aid]}"
            ws.cell(i, 16).style = "Hyperlink"
    n = len(rows) + 1

    thin, hfill, yellow = Side(style="thin", color="D9D9D9"), PatternFill("solid", fgColor="1F3864"), PatternFill("solid", fgColor="FFF2CC")
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(name=F, bold=True, color="FFFFFF"), hfill, Alignment(wrap_text=True, vertical="center")
    for row in ws.iter_rows(min_row=2, max_row=n):
        for c in row:
            c.font, c.alignment, c.border = Font(name=F, size=10), Alignment(wrap_text=True, vertical="top"), Border(bottom=thin)
        row[11].fill = row[12].fill = row[16].fill = yellow
    for col, w in zip("ABCDEFGHIJKLMNOPQ", [5, 16, 10, 11, 24, 40, 50, 22, 7, 24, 11, 12, 30, 9, 13, 8, 15]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "H2"
    ws.auto_filter.ref = f"A1:Q{n}"
    dv = DataValidation(type="list", formula1='"met,not_met,unsure"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"L2:L{n}")
    dv2 = DataValidation(type="list", formula1='"' + ",".join(ERRORS) + '"', allow_blank=True)
    ws.add_data_validation(dv2)
    dv2.add(f"Q2:Q{n}")
    pfill = {1: "F4B183", 2: "FFE699", 3: "EDEDED"}
    for r in range(2, n + 1):
        g = int(str(ws.cell(r, 2).value)[1])
        ws.cell(r, 2).fill = PatternFill("solid", fgColor=pfill[g])
    ws.conditional_formatting.add(f"O2:O{n}", FormulaRule(formula=['O2<>""'], fill=PatternFill("solid", fgColor="F8CBAD")))

    s = wb.create_sheet("Summary")
    s.append(["Criterion", "Question", "Agent says met", "Labeled", "Agent accuracy",
              "False positives", "Misses", "Precision (of agent met)"])
    G, Lc, Lm = f"Label!$I$2:$I${n}", f"Label!$N$2:$N${n}", f"Label!$O$2:$O${n}"
    I = f"Label!$K$2:$K${n}"
    J = f"Label!$L$2:$L${n}"
    for j, c in enumerate(sorted(CRIT), start=2):
        s.append([c, CRIT[c], f'=COUNTIFS({G},A{j},{I},"met")',
                  f'=COUNTIFS({G},A{j},{Lc},1)+COUNTIFS({G},A{j},{Lc},0)',
                  f'=IFERROR(COUNTIFS({G},A{j},{Lc},1)/D{j},"")',
                  f'=COUNTIFS({G},A{j},{Lm},"false positive")',
                  f'=COUNTIFS({G},A{j},{Lm},"miss")',
                  f'=IFERROR(COUNTIFS({G},A{j},{I},"met",{J},"met")/(COUNTIFS({G},A{j},{I},"met",{J},"met")+F{j}),"")'])
    t = len(CRIT) + 2
    s.append(["All", "", f"=SUM(C2:C{t-1})", f"=SUM(D2:D{t-1})",
              f'=IFERROR(SUMPRODUCT(E2:E{t-1},D2:D{t-1})/D{t},"")', f"=SUM(F2:F{t-1})", f"=SUM(G2:G{t-1})",
              f'=IFERROR(COUNTIFS({I},"met",{J},"met")/(COUNTIFS({I},"met",{J},"met")+F{t}),"")'])
    for c in s[1]:
        c.font, c.fill, c.alignment = Font(name=F, bold=True, color="FFFFFF"), hfill, Alignment(wrap_text=True)
    for row in s.iter_rows(min_row=2, max_row=t):
        for c in row:
            c.font = Font(name=F, bold=(row[0].value == "All"))
        row[4].number_format = row[7].number_format = "0.0%"
    for col, w in zip("ABCDEFGH", [10, 46, 12, 10, 13, 13, 10, 14]):
        s.column_dimensions[col].width = w
    counts = {g: sum(r[0] == g for r in rows) for g in GROUP}
    notes = ["How to use",
             "Fill the yellow 'Human label' on the Label sheet: met = the problem IS in the sentence, not_met = it isn't, unsure = skip.",
             f"Priority follows the agent's decision. P1 ({counts[1]} rows): the agent said met; check for false positives. "
             f"P2 ({counts[2]} rows): the agent couldn't decide; give the right answer.",
             f"P3 ({counts[3]} rows): the agent said not_met; spot-check for misses.",
             "Context: 'Previous 2 sentences' and 'Named source nearby' help with C1/C5 (a source can sit one sentence earlier). "
             "'Named source nearby' is an automatic hint and can miss sources; click 'open' in the last column to read the whole answer.",
             "In 'Notes', say WHY the agent is wrong (e.g. 'advice, not a generalization'); these notes become the prompt fixes.",
             f"Source: {a.agent}"]
    for k, line in enumerate(notes):
        s.cell(t + 2 + k, 1, line).font = Font(name=F, bold=(k == 0), italic=(k == len(notes) - 1), color="404040")
    s.cell(t + 2 + len(notes) + 1, 1, "Error category").font = Font(name=F, bold=True)
    s.cell(t + 2 + len(notes) + 1, 2, "Meaning").font = Font(name=F, bold=True)
    s.cell(t + 2 + len(notes) + 1, 3, "Count").font = Font(name=F, bold=True)
    for k, e in enumerate(ERRORS):
        r = t + 3 + len(notes) + 1 + k
        s.cell(r, 1, e).font = Font(name=F)
        s.cell(r, 2, ERR_DESC[e]).font = Font(name=F)
        s.cell(r, 3, f'=COUNTIF(Label!$Q$2:$Q${n},A{r})').font = Font(name=F)

    gd = wb.create_sheet("Guide")
    gd.append(["Column", "What it means", "Fill it in?"])
    guide = [
        ("#", "Row number", "No"),
        ("Group", "Priority, from the agent's decision. P1 agent: met (check for false positives; label first). "
                  "P2 agent: undetermined (give the right answer). P3 agent: not_met (spot-check for misses). "
                  "'| SHARED' = labeled by both annotators.", "No"),
        ("Answer ID", "Which chatbot answer the sentence comes from", "No"),
        ("Domain", "Topic category of the question", "No"),
        ("Question", "What the user asked the chatbot", "No"),
        ("Previous 2 sentences", "Context just before the sentence; sources often sit here", "No"),
        ("Sentence", "The sentence being judged", "No"),
        ("Named source nearby (auto)", "A named source the program found in the sentence or the 2 before. A hint only: it can miss sources", "No"),
        ("Criterion", "C1-C6, the problem being checked", "No"),
        ("Criterion question", "The yes/no question for that criterion. 'met' = the problem is present", "No"),
        ("Agent decision", "What the agent decided: met, not_met or undetermined", "No"),
        ("Human label", "YOUR answer to the criterion question: met / not_met / unsure", "YES"),
        ("Notes", "Why the agent is wrong, in a few words", "YES, when the agent is wrong"),
        ("Agent correct?", "Automatic: 1 = agent matches you, 0 = it doesn't", "No"),
        ("Error type", "Automatic: 'false positive' (agent met, you not_met) or 'miss' (you met, agent didn't)", "No"),
        ("Full answer", "Click 'open' to read the whole chatbot answer on the Answers sheet", "No"),
        ("Error category", "When the agent is wrong, pick the kind of mistake (list below)", "YES, when the agent is wrong"),
    ]
    for row in guide:
        gd.append(list(row))
    gd.append([])
    gd.append(["Error category", "Meaning", ""])
    for e in ERRORS:
        gd.append([e, ERR_DESC[e], ""])
    for row in gd.iter_rows():
        for c in row:
            c.font = Font(name=F, size=10, bold=(c.row == 1 or c.value in ("Error category",)))
            c.alignment = Alignment(wrap_text=True, vertical="top")
    for col, w in zip("ABC", [26, 90, 22]):
        gd.column_dimensions[col].width = w

    wb._sheets = [wb["Guide"], wb["Summary"], wb["Label"], wb["Answers"]]
    for c in ans[1]:
        c.font, c.fill = Font(name=F, bold=True, color="FFFFFF"), hfill
    for row in ans.iter_rows(min_row=2):
        for c in row:
            c.font, c.alignment = Font(name=F, size=10), Alignment(wrap_text=True, vertical="top")
    for col, w in zip("ABCD", [10, 11, 40, 120]):
        ans.column_dimensions[col].width = w
    ans.freeze_panes = "B2"
    wb.save(a.out)
    print(f"{len(rows)} rows; groups: {counts} -> {a.out}")


if __name__ == "__main__":
    main()
