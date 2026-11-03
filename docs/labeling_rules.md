# GiSuN labeling instructions (strict rules)

These rules decide whether a sentence in a chatbot answer is `met` (the problem is present) or
`not_met` for each GiSuN criterion. They are **strict**: flag a sentence only when a reader could
actually be misled and could not check the claim from the answer itself. **When in doubt, label
`not_met`.**

Use them for every labeling sheet (our ChatGPT answers, the insertion set, and the spot-checks of
public datasets), and give GiSuN's agents the same rules, so that the agent and the labels are
judged the same way.

Version 1, 2026-10-27. Written after the Gideon/Suning adjudication meeting; the examples come
from our combined label sheet (row numbers refer to `GiSuN_labels_final.xlsx`) and from the
public datasets.

## Rules for every criterion

1. **Judge only this row's criterion.** If the sentence has a different problem, label this row
   `not_met` and name the other criterion in the notes.
2. **Headings, questions and fragments are never `met`** (for example "**Why it changes each year**").
3. **Reported viewpoints are not the answer's own claim.** "Critics argue…", "Supporters say…" and
   "Opponents claimed…" describe a debate and are `not_met`, unless the answer itself endorses the claim.
4. **Common knowledge counts as support.** If a typical college student would not need a source to
   believe the claim, it is `not_met`.
5. **Read the two previous sentences.** A source or an explanation there covers this sentence.

## C1: Statistic with no source

**`met` only if** the sentence gives a specific number (percentage, amount, count, record or
ranking) that a reader would need to check, **and** no specific source appears in this sentence or
the two before it.

**`not_met`:** dates on their own, numbers inside definitions or rules, illustrative examples
("Assume 30 mpg…"), arithmetic on a figure that is already sourced, and vague amounts with no
number ("many", "free").

| Example | Label | Why |
|---|---|---|
| "Households had built up about $2 trillion in excess savings." (row 2) | `met` | specific figure, no source |
| "That's a gap of about 16–18%." (row 131, right after "according to Census Bureau data") | `not_met` | arithmetic on a sourced figure |
| "In 2019, scientists released the first-ever image of a black hole's shadow." (row 109) | `not_met` | a dated event, not a statistic |

Error type when GiSuN flags a `not_met` sentence: `FP-NOT-STAT` or `FP-SOURCE`.

## C2: Wrong number

**`met` only if** a reliable source (statistics office, official record, peer-reviewed paper) gives
a **clearly different** figure for the **same** measure, place, year and unit. Write the source URL
and its figure in the notes.

**`not_met`:** the figure matches within rounding, or falls within the range the answer gives.
**If no matching source is found, the label is `undetermined`, never `met`.**

| Example | Label | Why |
|---|---|---|
| "The U.S. unemployment rate averaged 12% in 2020." (BLS annual average: 8.1%) | `met` | clearly different, same measure and year |
| "Roughly 40,000 people die in U.S. car crashes each year." (NHTSA: about 40,000–43,000 in recent years) | `not_met` | within the range |

## C3: Loaded language

**`met` only if** the answer itself uses a word that carries a judgment where a neutral word would
say the same thing.

**`not_met`:** quoted or reported wording, strong but accurate words for documented facts
("devastated" for the Dust Bowl), and words that are the topic being explained ("the term
'illegal alien' is controversial").

| Example | Label | Why |
|---|---|---|
| "Mark Oaten is a disgraced Liberal Democrat politician." (WNC) | `met` | "disgraced" adds a judgment |
| "Opponents argued that race-conscious admissions disadvantaged Asian American applicants." (row 12) | `not_met` | reported view |
| "Concerns include cyberbullying, body image issues, sleep disruption…" (row 41) | `not_met` | neutral list |

Error types: `FP-NEUTRAL`, `FP-ATTRIBUTED`.

## C4: Overgeneralization

**`met` only if** the sentence makes an unqualified universal claim about people, groups or
outcomes ("always", "never", "everyone", or a claim about a whole group) that has obvious exceptions.

**`not_met`:** literally true absolutes, rules and laws, definitions, closed groups ("all 12
patients"), hedged sentences ("doesn't always"), and comparisons backed by the previous sentence.

| Example | Label | Why |
|---|---|---|
| "Everyone concentrates better after a good breakfast." | `met` | universal claim with obvious exceptions |
| "Only a member of Congress can formally introduce a bill." (row 22) | `not_met` | a rule |
| "More time doesn't always mean better results." (row 54) | `not_met` | a hedge, not a generalization |
| "Republicans have especially low trust." (row 21, right after the Gallup figure) | `not_met` | backed by the previous sentence |

Error types: `FP-COMMON`, `FP-OTHER`.

## C5: Vague attribution

**`met` only if** a **factual claim rests on an unnamed authority** ("studies show", "experts say",
"research suggests", "it is believed") and no specific source is nearby.

**`not_met`:** naming who holds an **opinion** in a debate ("critics argue", "supporters say"), a
sentence that credits no one at all (that is C1's job), and a specific source named nearby.

Test question: *is the vague group used as **evidence for a fact**, or does it only name **who
believes something**?*

| Example | Label | Why |
|---|---|---|
| "Studies show it lowers the risk of hospitalization and death." (row 32) | `met` | a fact resting on "studies" |
| "Critics argue these costs fall hardest on working-class people." (row 27) | `not_met` | describes a viewpoint |
| "The CDC recommends an annual flu vaccine…" (row 74) | `not_met` | named source |

Error types: `FP-ATTRIBUTED`, `FP-SOURCE`.

## C6: Unsupported cause and effect

**`met` only if** the answer states a **specific cause → effect as fact**, and the link is not
common knowledge, not explained in the previous sentences, not hedged, and not attributed to someone.

**`not_met`:** common-knowledge mechanisms, causes explained just before, hedged wording ("may
contribute"), reported arguments, and correlation stated as correlation ("is associated with").

| Example | Label | Why |
|---|---|---|
| "Pilates and walking positively impact quality of life, depression and anxiety." (Yu et al.) | `met` | specific causal claim stated as fact |
| "When housing prices fell, losses spread rapidly." (row 35) | `not_met` | common knowledge |
| "EVs produce no exhaust while driving, which improves local air quality." (row 140) | `not_met` | obvious mechanism |
| "Critics argue that higher labor costs lead employers to hire fewer workers." (row 160) | `not_met` | reported view |

Error types: `FP-COMMON`, `FP-ATTRIBUTED`.

## Error types (for rows where GiSuN said `met` but the label is `not_met`)

| Type | Meaning |
|---|---|
| `FP-COMMON` | common knowledge flagged as unsupported |
| `FP-ATTRIBUTED` | a reported viewpoint treated as the answer's own claim |
| `FP-NEUTRAL` | neutral wording flagged as loaded |
| `FP-SOURCE` | a source is in the sentence or the two before it, but GiSuN missed it |
| `FP-CITATION` | the sentence is itself a citation line |
| `FP-NOT-STAT` | flagged as a statistic but contains no statistic |
| `FP-OTHER` | headings, fragments, anything else (say what in the notes) |

## How to label

- Label independently first; don't look at the other person's labels or at the agent's decision.
- Use `met`, `not_met`, or (C2 only) `undetermined`. Use notes for anything borderline.
- Settle disagreements together, record the decision and the reason, and add any new rule or
  example to this file so the next round follows it.
