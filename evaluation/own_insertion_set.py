"""
Our own insertion dataset: 25 sentences per criterion (C1, C2, C3, C5, C6; 13 met + 12 not_met) taken
from the public datasets, each with a question someone might ask ChatGPT whose answer would naturally
contain that sentence. Later: ask ChatGPT the questions, insert each sentence into its answer, and see
whether GiSuN still judges it right in context.

    python -m evaluation.own_insertion_set pick    # -> datasets/own/insertion_picks.json
    (write the questions into datasets/own/insertion_questions.json: {"C1-01": "question", ...})
    python -m evaluation.own_insertion_set build   # -> datasets/own/GiSuN_own_insertion_set.xlsx

No sentence appears twice, the two halves of a WNC or C1 pair are never both used, and nothing overlaps
the test sample in datasets/external/samples.json. Picks are drawn with fixed seeds, so they reproduce.
"""

import json
import os
import random
import re
import sys

sys.path.insert(0, os.getcwd())
from evaluation import external_testset as T
from gisun.preprocess import split_sentences

import pyarrow.parquet as pq
from openpyxl import Workbook
from openpyxl.styles import Font

OUT_DIR = "datasets/own"
PICKS = os.path.join(OUT_DIR, "insertion_picks.json")
QUESTIONS = os.path.join(OUT_DIR, "insertion_questions.json")
XLSX = os.path.join(OUT_DIR, "GiSuN_own_insertion_set.xlsx")
N_MET, N_CLEAN = 13, 12

# Sentences nobody could write a sensible question for (fragments, headers, posts about media)
_FRAGMENT = re.compile(r"^(TRIAL REGISTRATION|CONCLUSIONS?:|IMPACT:|RESULTS?:)|NCT\d", re.I)
# Per criterion: extra filters so each side really is what its label says
_C1_NAMED = re.compile(r"\b(according to|reported|forecast|announced|published|census|survey)\b", re.I)
_C2_MEDIA = re.compile(r"\b(clip|picture|photo|image|video|movie|footage|shows|post)s?\b|^No,|\bI (was|am|will)\b", re.I)
_C5_NAMED = re.compile(r"\b(he|she|they) (has |have |had )?(said|claimed)\b|\bby (his|her|their|the) ", re.I)
_C5_ATTRIB = re.compile(r"\b(said|says|claim\w*|report\w*|thought|seen|regarded|considered|believed|according|alleged\w*|critici[sz]\w*)\b", re.I)
_C6_CAUSAL = re.compile(r"\b(reduc|improv|increas|decreas|lead|leads|result|caus|impact|affect|enhanc|lower|rais|"
                        r"prevent|contribut)\w*", re.I)


def _readable(s: str) -> bool:
    return 10 <= len(s.split()) <= 45 and not _FRAGMENT.search(s) and not s.rstrip('"”').endswith("?")  # no headlines-as-questions


def _clean_source(s: str) -> str:
    """'(Source: 1 2 3 Rudmose Brown)' -> '(Source: Rudmose Brown)': drop Wikipedia's footnote numbers and arrows,
    and repair a DOI cut at its first dot ('(Source: .1111/...)' -> '(Source: doi:10.1111/...)')."""
    s = re.sub(r"\(Source: [\d\s↑^]+", "(Source: ", s)
    return s.replace("(Source: .", "(Source: doi:10.")


def _pools():
    """Large candidate pools per criterion, built with the same loaders and mappings as the workbook."""
    big = random.Random(99)
    pools = {"C1": T.c1_citation_reason(big, n_pairs=142)[0], "C2": T.c2_quantemp(big, n_each=1000)[0]}
    # C3 from the files the workbook didn't sample: WNC dev pairs and the BABE train split
    c3 = []
    for i, c in enumerate(l.rstrip("\n").split("\t") for l in open("datasets/external/wnc/biased.word.dev", encoding="utf-8")):
        cap = lambda s: s[:1].upper() + s[1:]  # WNC is lowercased; capitalize so it reads like normal text
        c3.append(T._row("WNC", cap(c[3]), "biased (before the Wikipedia edit)", "met", "", f"w{i}"))
        c3.append(T._row("WNC", cap(c[4]), "neutral (after the edit)", "not_met", "", f"w{i}"))
    for b in pq.read_table("datasets/external/babe/train.parquet").to_pylist():
        met = b["label"] == 1
        c3.append(T._row("BABE", b["text"], "biased" if met else "not biased", "met" if met else "not_met", b.get("outlet", "")))
    pools["C3"] = c3
    pools["C5"] = T.c5_szeged(big, n_each=180)[0]
    pools["C6"] = T.c6_yu(big, n_causal=395, n_corr=797, n_none=1084)[0]
    return pools


def _fits(cid: str, r: dict) -> bool:
    s, met = r["sentence"], r["expected"] == "met"
    if cid == "C1":
        return not (met and _C1_NAMED.search(s))
    if cid == "C2":
        return bool(re.search(r"\d", s)) and not _C2_MEDIA.search(s)
    if cid == "C5":
        return not _C5_NAMED.search(s) if met else not _C5_ATTRIB.search(s)
    if cid == "C6":
        return bool(_C6_CAUSAL.search(s)) if met else not s.rstrip('"').endswith(":")
    return True


def pick() -> dict:
    rnd = random.Random(11)
    used = {r["sentence"] for rows in json.load(open("datasets/external/samples.json")).values() for r in rows}
    out = {}
    for cid, rows in _pools().items():
        chosen, pairs, seen = [], set(), set()
        for want, n in (("met", N_MET), ("not_met", N_CLEAN)):
            got = 0
            for r in rnd.sample(rows, len(rows)):
                s = r["sentence"]
                if (r["expected"] != want or s in used or s in seen or not _readable(s) or not _fits(cid, r)
                        or (r.get("pair") and r["pair"] in pairs)):
                    continue
                if cid == "C2":
                    # PolitiFact's "Says ..." prefix, and the stray straight quotes QuanTemp leaves when it cuts quotations
                    r["sentence"] = re.sub(r"^Says\s+", "", s).replace('"', "").replace(" … ", " ")
                if cid == "C1":
                    r["sentence"] = _clean_source(s)
                chosen.append(r)
                seen.add(s)
                pairs.add(r.get("pair"))
                got += 1
                if got == n:
                    break
        for k, r in enumerate(chosen, 1):
            r["id"] = f"{cid}-{k:02d}"
        out[cid] = [{k: r[k] for k in ("id", "dataset", "sentence", "their_label", "expected", "context")} for r in chosen]
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(out, open(PICKS, "w"), indent=1, ensure_ascii=False)
    return out


TAB_NAMES = {"C1": "C1 Unsourced statistics", "C2": "C2 Wrong numbers", "C3": "C3 Loaded language",
             "C4": "C4 Overgeneralization", "C5": "C5 Vague attribution", "C6": "C6 Causal claims"}
PREVIEW = os.path.join(OUT_DIR, "GiSuN_own_insertion_set_with_C4.xlsx")
ANSWERS = os.path.join(OUT_DIR, "insertion_answers.json")  # Codex answers collected so far


def c4_rows():
    """C4 has no public dataset. Its 16 items are the 16 questions already asked of ChatGPT
    (datasets/c4/chatgpt_raw.txt, cleaned), and the sentence to insert comes from the C4 answers we wrote
    for the same questions (datasets/c4/c4_source.json): a sweeping one (met) for odd items, a clean one
    (not_met: rule, true absolute, closed group, reported or hedged) for even items, so 8 + 8."""
    src = json.load(open("datasets/c4/c4_source.json", encoding="utf-8"))
    real = {a["id"]: a for a in json.load(open("datasets/c4/chatgpt_clean.json", encoding="utf-8"))}
    clean_kinds = ("RULE", "TRUE-ABS", "SCOPED", "REPORTED", "HEDGED")
    rows, owe = [], None  # owe: the side an earlier answer couldn't supply, taken by the next one that can
    for n, a in enumerate(src["answers"], 1):
        options = lambda met: [(k, v) for k, v in a["labels"].items()
                               if (v[0] == "met") == met and (met or v[1] in clean_kinds)]
        want_met = owe if owe is not None and options(owe) else n % 2 == 1
        if owe is not None and options(owe):
            owe = None
        elif not options(want_met):  # e.g. the prime-number answer has no sweeping sentence
            owe, want_met = want_met, not want_met
        key, (label, cat, why) = options(want_met)[0]
        sentence = next(s for s in split_sentences(a["answer"]) if key.lower() in s.lower())
        sentence = re.sub(r"\*\*[^*]+\*\*\s*", "", sentence.lstrip("- "))  # drop markdown like "**Focus:** "
        rows.append({"id": f"C4-{n:02d}", "dataset": "GiSuN C4 set (written by us)", "sentence": sentence,
                     "their_label": f"{cat} ({why})", "expected": label, "context": "",
                     "question": a["question"], "answer": real.get(f"c4-c{n:02d}", {}).get("answer", "")})
    return rows
# Reviewers read an excerpt, not the whole answer: the relevant sentence plus the two before it.
# Full answers are kept on their own tab (GiSuN needs the whole text when it runs).
COLS = ["#", "ID", "Question asked", "Previous 2 sentences", "Relevant sentence (from the answer)", "Why this sentence",
        "Dataset sentence (to insert)", "Their label", "Expected", "Dataset", "Source / context",
        "Agent decision", "Correct?", "Notes"]
WIDTHS = [5, 8, 34, 44, 50, 18, 50, 22, 10, 16, 16, 12, 9, 24]

_WORDS = json.load(open("bias_wordlist.json", encoding="utf-8"))
_CUES = {  # what makes a sentence relevant to each error type
    "C3": [w for k in ("loaded_political_terms", "emotionally_charged_terms", "loaded_framing_of_events",
                       "loaded_identity_or_group_terms") for w in _WORDS[k]],
    "C4": _WORDS["absolutist_or_overgeneralizing_terms"],
    "C5": _WORDS["vague_or_unsourced_attribution"],
}
_CAUSAL = re.compile(r"\b(because|caus\w*|lead\w* to|led to|result\w* in|due to|reduc\w*|increas\w*|improv\w*|"
                     r"drives?|driven|contribut\w*|so that|therefore)\b", re.I)
_STOP = set("the a an of to in and or is are was were be for on with that this it as by at from its their".split())


def _excerpt(cid: str, answer: str, dataset_sentence: str) -> tuple[str, str, str]:
    """(previous 2 sentences, relevant sentence, why). Relevant = a sentence with this error type's cue
    (a number with no source for C1, any number for C2, a word-list hit for C3-C5, causal wording for C6);
    among those, or among all sentences when none has the cue, the one closest in topic to the dataset sentence."""
    sents = [re.sub(r"\*\*|^[-•]\s*", "", s).strip() for s in split_sentences(answer)]
    sents = [s for s in sents if len(s.split()) >= 3]
    if not sents:
        return "", "", ""
    topic = {w for w in re.findall(r"[a-z]+", dataset_sentence.lower()) if w not in _STOP}

    def cue(s):
        low = s.lower()
        if cid == "C1":
            return bool(re.search(r"\d", s)) and not T.find_attribution(s)["source_text"]
        if cid == "C2":
            return bool(re.search(r"\d", s))
        if cid == "C6":
            return bool(_CAUSAL.search(s))
        return any(re.search(rf"\b{re.escape(w.lower())}\b", low) for w in _CUES[cid])

    overlap = lambda s: len(topic & set(re.findall(r"[a-z]+", s.lower())))
    with_cue = [i for i, s in enumerate(sents) if cue(s)]
    pool = with_cue or list(range(len(sents)))
    best = max(pool, key=lambda i: (overlap(sents[i]), -i))
    why = {"C1": "number, no source in it", "C2": "contains a number", "C3": "loaded word",
           "C4": "absolute word", "C5": "vague attribution", "C6": "causal wording"}[cid] if with_cue else "closest topic"
    return " / ".join(sents[max(0, best - 2):best]), sents[best], why


def build(with_c4=False, out=XLSX):
    picks = json.load(open(PICKS, encoding="utf-8"))
    questions = json.load(open(QUESTIONS, encoding="utf-8"))
    # Answers collected so far (Codex) go straight into the answer column
    answers = {a["id"]: a["text"] for a in json.load(open(ANSWERS, encoding="utf-8"))} if os.path.exists(ANSWERS) else {}
    if with_c4:  # C4 items carry their own question and (real ChatGPT) answer
        c4 = c4_rows()
        questions.update({r["id"]: r["question"] for r in c4})
        answers.update({r["id"]: r["answer"] for r in c4})
        picks = {cid: picks[cid] for cid in ("C1", "C2", "C3")} | {"C4": c4} | {cid: picks[cid] for cid in ("C5", "C6")}
    missing = [r["id"] for rows in picks.values() for r in rows if not questions.get(r["id"])]
    if missing:
        raise SystemExit(f"no question yet for: {', '.join(missing)}")
    wb = Workbook()
    guide = wb.active
    guide.title = "How to use"
    guide.column_dimensions["A"].width = 110
    lines = [
        ("GiSuN insertion set: our own dataset, 25 items per error type for C1, C2, C3, C5, C6, plus 16 for C4 "
         "(141 in total)." if with_c4 else
         "GiSuN insertion set: our own dataset, 25 items per error type (C1, C2, C3, C5, C6; 125 in total)."),
        *(["C4 has no public dataset: its 16 questions are the ones already asked of ChatGPT (answers filled in), "
           "and its sentences come from the C4 answers we wrote for the same questions (8 sweeping = met, "
           "8 clean = not_met)."] if with_c4 else []),
        "Each row: a sentence from a public dataset with its known label, and a question someone might ask ChatGPT "
        "whose answer would cover the same topic.",
        "Expected = the dataset's own label translated to our met / not_met (13 met + 12 not_met per tab). "
        "Sources and mappings: Google Doc 'GiSuN Public Datasets: Download Sources (corrected)'.",
        "No sentence appears twice, the two halves of a WNC or C1 pair are never both used, and none of these "
        "overlap the test sample in GiSuN_external_datasets.xlsx.",
        "Answers: C4 = real ChatGPT answers collected by hand; all others = GPT-6.1-Sol (reasoning low) through "
        "codex exec, one fresh session per question, asked to answer in one paragraph of about 4-5 sentences.",
        "Each row shows only an excerpt: the relevant sentence and the 2 sentences before it. 'Why this sentence' "
        "says how it was picked (the error type's cue word, or the sentence closest in topic to the dataset "
        "sentence when the answer has no cue). Full answers are on the last tab.",
        "Next: insert the dataset sentence into the answer and run GiSuN on it; Agent decision is filled in then, "
        "and Correct? updates by itself. Nothing has been run yet.",
    ]
    for i, t in enumerate(lines, 1):
        guide.cell(row=i, column=1, value=t).font = Font(name=T.F, bold=(i == 1))
    for cid, rows in picks.items():
        ws = wb.create_sheet(TAB_NAMES[cid])
        q = {"C1": "Statistic with no specific source nearby?", "C2": "Does a reliable source contradict the number?",
             "C3": "Slanted / loaded wording where neutral would do?",
             "C4": "Sweeping absolute claim the evidence can't support?", "C5": "'Experts say' instead of a named source?",
             "C6": "Cause-and-effect stated without evidence?"}[cid]
        T._cell(ws, 1, 1, f"{cid}: {q}", bold=True)
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(COLS))
        for c, (h, w) in enumerate(zip(COLS, WIDTHS), 1):
            T._cell(ws, 2, c, h, T.HEAD, bold=True, color="FFFFFF")
            ws.column_dimensions[ws.cell(row=2, column=c).column_letter].width = w
        ws.freeze_panes = "A3"
        for i, r in enumerate(rows, 1):
            x = i + 2
            before, relevant, why = _excerpt(cid, answers.get(r["id"], ""), r["sentence"])
            vals = [i, r["id"], questions[r["id"]], before, relevant, why, r["sentence"], r["their_label"],
                    r["expected"], r["dataset"], r["context"], None,
                    f'=IF(L{x}="","",IF((L{x}="met")=(I{x}="met"),1,0))', None]
            for c, v in enumerate(vals, 1):
                T._cell(ws, x, c, v)
    # Full answers, for GiSuN's run and for looking one up; nobody needs to read this tab to label
    fa = wb.create_sheet("Full answers")
    for c, (h, w) in enumerate(zip(["ID", "Question asked", "Full answer", "Answered by"], [8, 40, 100, 30]), 1):
        T._cell(fa, 1, c, h, T.HEAD, bold=True, color="FFFFFF")
        fa.column_dimensions[fa.cell(row=1, column=c).column_letter].width = w
    models = {a["id"]: a["model"] for a in json.load(open(ANSWERS, encoding="utf-8"))} if os.path.exists(ANSWERS) else {}
    for i, r in enumerate((r for rows in picks.values() for r in rows), 2):
        for c, v in enumerate([r["id"], questions[r["id"]], answers.get(r["id"]),
                               models.get(r["id"], "ChatGPT web app (collected by hand)")], 1):
            T._cell(fa, i, c, v)
    wb.save(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pick"
    if cmd == "pick":
        for cid, rows in pick().items():
            print(f"== {cid}")
            for r in rows:
                print(f"{r['id']} [{r['expected']}] ({r['dataset']}) {r['sentence']}")
    elif cmd == "build":
        build(with_c4=True)
        print("wrote", XLSX)
    elif cmd == "preview-c4":  # the same workbook with a C4 tab added, as a separate file
        build(with_c4=True, out=PREVIEW)
        print("wrote", PREVIEW)
