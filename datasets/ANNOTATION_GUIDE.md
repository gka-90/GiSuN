# Annotation guide (gold set for RQ1-RQ3)

The gold set is what every GiSuN number is measured against, so two people label it
**independently** and disagreements are settled together afterwards.

## Data

| file | what |
|---|---|
| `candidates_wildchat.json` | 50 real ChatGPT answers (gpt-3.5-turbo / gpt-4, Dec 2023 - Apr 2024) from [WildChat-1M](https://huggingface.co/datasets/allenai/WildChat-1M), ODC-BY |
| `candidates_hc3.json` | 15 ChatGPT answers (Dec 2022) from [HC3](https://huggingface.co/datasets/Hello-SimpleAI/HC3), CC-BY-SA |
| `excluded.json` | conversations read and rejected by hand (off-topic, personal advice, duplicates), with the reason |
| `annotation/labels_<name>.json` | one labeling file per person |
| `gold.json` | the merged gold set (made by `evaluation.annotate merge`) |

Selection (`evaluation/collect.py`): single-turn English conversations, the question asks for
information about economy / health / politics / history / environment / society, no coding,
writing or role-play, answer 400-3000 characters, at least one claim the detectors find
(two for HC3), then a random sample balanced across domains. Each item keeps its source
(dataset, conversation hash or row, model, date): report these in the paper.

**Don't re-run `collect.py` once labeling has started**: it renumbers the items.

## How to label

Open your own `annotation/labels_<name>.json`. For every item, `labels` lists the factual
sentences of the answer, and for each one the criteria to decide, all `null`:

```json
"Botswana's GDP per capita was about $70 in 1966.": {"C1": null, "C2": null, "C3": null, "C4": null, "C5": null, "C6": null}
```

Replace each `null` with `"met"` (the problem **is** present), `"not_met"`, or
`"undetermined"` (you can't tell, even after checking). Read the whole answer first: a source
named one or two sentences earlier counts.

- Don't look at the other person's file or at GiSuN's output until you've both finished.
- Don't delete sentences. If a "sentence" is not a claim (a heading, a list fragment), mark all its criteria `not_met`.
- You may add a criterion to a sentence if it clearly applies, e.g. `"C1"` for a numberless trend claim.
- Put anything worth discussing in the item's `"notes"`.
- Check progress with `python -m evaluation.annotate status`.

Labeling everything takes several hours: about 2,600 decisions each. Do a **pilot first**:
both label the same 10 items, merge, look at kappa and the disagreements, sharpen these rules,
then do the rest.

## The criteria

"met" always means **the problem is there**.

**C1 unsourced statistic.** A number or other quantitative claim (a record, a trend, a
comparison: "the highest ever", "skyrocketed", "doubled") with no specific source in this or
the previous two sentences. A specific source = a named organisation, publication, dataset or
link. "Experts", "studies", "data shows" are **not** specific. Dates and years alone are not
statistics.

**C2 statistic contradicted.** Look the number up in a reliable source (statistics office,
official record, peer-reviewed paper). Only compare the **same measure, place, year and unit**.
`met` = a reliable source gives a clearly different figure; `not_met` = it matches (allow
rounding); `undetermined` = no matching figure found. **Write the source URL and its figure in
the item's notes** for every C2 decision that isn't `undetermined`.

**C3 loaded language.** Slanted or emotional wording where a neutral word would do
("disastrous policy", "job-killing", "regime"). Negated, quoted or merely mentioned terms don't
count ("the term 'illegal alien' is controversial"). Most sentences are neutral.

**C4 overgeneralization.** An absolute or sweeping claim (always, never, all, everyone, no one)
that turns a tendency into a rule. Literally true absolutes (physical laws, definitions) are
`not_met`.

**C5 vague attribution.** The sentence credits someone it doesn't name: "experts say",
"studies show", "research suggests", "it is widely believed". A sentence that credits **no one**
is `not_met` (missing sources are C1's job). If a specific source is named too, `not_met`.

**C6 unsupported causal claim.** Says A causes B ("leads to", "because", "due to",
"results in") without evidence or a source, especially correlation presented as cause.
Well-established, uncontroversial mechanisms ("smoking causes lung cancer") are `not_met`.

## Merge and adjudicate

```bash
python -m evaluation.annotate merge --a datasets/annotation/labels_suning.json --b datasets/annotation/labels_partner.json
```

This prints Cohen's kappa per criterion, writes the pairs you agree on to `datasets/gold.json`
and the disagreements to `datasets/annotation/adjudication.json`. Discuss each one, write the
agreed decision into `"final"`, and run merge again. Report the kappa from **before**
adjudication: it is the ceiling to read GiSuN's per-criterion F1 against.

Then `python -m evaluation.run_all` evaluates on `gold.json` automatically.
