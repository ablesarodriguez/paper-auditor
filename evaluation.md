# Evaluation of the code-made checks

Errors were planted, one per copy, in the texts of the papers audited so far, and each copy went through the checks the review runs without a model. Produced by `python tools/evaluate.py`; the errors are drawn with a fixed seed, so the numbers are the same on every run.

| Kind of error | Planted | Caught |
| --- | --- | --- |
| Average or total in a table that does not match its cells | 9 | 9 (100%) |
| Result of the abstract that the body does not print | 16 | 15 (94%) |
| Result printed with another value in the body than in the abstract | 8 | 8 (100%) |
| Percentage that does not match the counts beside it | 55 | 55 (100%) |
| Reference to an undefined equation, figure or table | 35 | 35 (100%) |
| Citation with no entry in the bibliography | 10 | 10 (100%) |
| **All** | **133** | **132 (99%)** |

## By paper

| Paper | Source | table | abstract_missing | abstract_differs | percentage | reference | citation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1312.6114 | arxiv-latex | – | – | – | 5/5 | 5/5 | – |
| 1412.6980 | pdf-text+vision | – | – | – | 5/5 | – | – |
| 1602.03837 | pdf-text+vision | – | 4/4 | 3/3 | 5/5 | – | – |
| 1706.03762 | arxiv-latex | – | 3/3 | – | 5/5 | 5/5 | 5/5 |
| 1810.04805 | arxiv-latex | – | 4/5 | – | 5/5 | 5/5 | – |
| 1907.11692 | arxiv-latex | – | – | – | 5/5 | 5/5 | – |
| 2010.11929 | arxiv-latex | 4/4 | – | – | 5/5 | 5/5 | – |
| 2106.09685 | arxiv-latex | 5/5 | 2/2 | – | 5/5 | 5/5 | – |
| 2504.00560 | arxiv-latex | – | – | – | 5/5 | 5/5 | 5/5 |
| final | pdf-text+vision | – | 2/2 | 5/5 | 5/5 | – | – |
| lorenz1963 | pdf-scan | – | – | – | 5/5 | – | – |

"–" means the paper offers nothing to plant that kind of error in (no table with an average, no abstract heading, no LaTeX labels).

## Flags on the unmodified papers

- 1602.03837: concern: The abstract quotes 250, 1.0, which are not printed anywhere in the body of the paper, in text or tables. A reader cannot see where these results come from, unless they are read off a figure.
- 1706.03762: abstract: 41.8 in the abstract and 41.0 in the body, both after "score of" in passages about the same thing (bleu, english, french, model, score)

Each flag above was looked at by hand: both are real. In GW150914 the 35–250 Hz sweep and the 1.0 × 10⁻²¹ peak strain of the abstract are only read off Figure 1. In *Attention Is All You Need* the English-French BLEU of the big model is 41.8 in the abstract and the table and 41.0 in the text. In the review, a flag of the second kind is reported only after a model confirms both values are the same quantity (it did here).

## What this shows and what it does not

It shows that the checks work on the text of real papers, with their LaTeX, their transcription artefacts and their many numbers, and that they stay quiet where nothing is wrong. It does not measure how many of the errors in published papers are of these kinds, and the errors were planted by the same author who wrote the checks. The concerns written by models (soundness, evidence, missing details) are not measured here.

## Planted errors that were missed

- 1810.04805, abstract_missing: abstract 86.7 -> 93.1
