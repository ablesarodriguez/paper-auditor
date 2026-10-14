# How it works, in detail

The [README](../README.md) gives the overview. This page is for whoever wants
to know exactly what each step does, what keeps a model's mistake out of the
report, and where it still falls short.

- [The review](#the-review)
- [What keeps a model's opinion out of the report](#what-keeps-a-models-opinion-out-of-the-report)
- [The reproduction](#the-reproduction)
- [Verdicts and confidence](#verdicts-and-confidence)
- [Same paper, same report](#same-paper-same-report)
- [The public demo and its budget](#the-public-demo-and-its-budget)
- [Known limitations](#known-limitations)

## The review

It needs no data and applies to any paper. `--review-only` stops after it.

| Step | What it does | Runs on |
| --- | --- | --- |
| Ingest | The arXiv LaTeX source when there is one; otherwise the PDF, transcribed strip by strip, with its text layer as reference | MiniCPM-V for PDFs |
| Figures | Finds each figure in the PDF by its caption, cuts it out and has it described, so the review is not limited to captions. Labels drawn as vector text are read from the PDF and handed to the model. Descriptions are a reading aid: values read off a plot are never used as numbers | MiniCPM-V |
| Review | Summary, strengths, major and minor concerns, a ten-point reproducibility checklist, questions for the authors | Nemotron 3 Ultra |
| Challenge | Every concern is argued against by a second reading of the whole paper. It is withdrawn when another passage answers it, or when Ultra and Super, reading independently, both find the fact it rests on is not so | Nemotron 3 Ultra, Super |
| Number checks | Recomputes every "Avg." and "Total" of the tables, every percentage printed beside its counts ("113 of 150 (75.3%)"), and looks for each number of the abstract in the body, in the same context. Finds a result printed twice with two values ("BLEU score of 41.8" and "BLEU score of 41.0" about the same task). The model points at further relations; code computes them | Code; Nemotron 3 Ultra and Super confirm |
| Related work | Searches the web for the closest work, keeps results that are papers, takes the year from the address where it is there, and checks by code whether the paper cites each one; a work later than the paper is marked as such | Tavily, Nemotron 3 Ultra |

## What keeps a model's opinion out of the report

- **Every concern must quote the paper.** The quote is looked up in the
  paper's text (not in the figure descriptions); a concern whose quote is not
  there gets one more chance to name the sentence it meant, and is otherwise
  discarded. So are complaints about the copy rather than the paper.
- **Every concern is argued against.** The report lists the withdrawn ones too,
  with the passage that answered them.
- **Arithmetic is done by code, never by a model.** A mismatch that rests on a
  reading (the model's expression, or code matching by wording) is reported
  only if a model that did not set it up agrees both sides are the same
  quantity computed as the paper defines it. One off by a round factor (2, 10,
  1000) is taken as a dropped factor, not an error of the paper. Rounding of
  printed inputs is never a mismatch.
- **Some facts are decided by code outright**: whether every `\ref` and
  `\cite` of a LaTeX source is defined, and whether sections are duplicated.
  Models got both wrong before (missing references that were there,
  "duplicated sections" that appear once).
- **Related works are only ones the search returned**, judged from title and
  snippet, not read. "Not found in the paper" means its full title is not in
  the text.

What it found on real papers:

- *Attention Is All You Need*: the English-French BLEU of the big model is
  41.8 in the abstract and the table and 41.0 in the text. Found by code,
  confirmed by a model, on every run.
- *Adam*: the convergence theorem assumes decaying step sizes and β₁; the
  algorithm as written uses constants.
- The gravitational-wave discovery letter: the 35–250 Hz sweep and the
  1.0 × 10⁻²¹ peak strain of the abstract are not printed in the body (they
  are read off Figure 1).
- LoRA and ViT: the 14 GLUE averages and 4 "Average" rows recomputed from the
  table cells, all consistent.

Mismatches that were false and are now stopped: a parameter count that dropped
a factor of 2 (six of them on LoRA), and a "3.0" of the abstract matched to a
"Creative Commons 3.0" licence.

**Measured.** `python tools/evaluate.py` plants errors in copies of the papers
audited so far and counts how many the checks catch: on eleven papers, 132 of
133. The full table and its limits are in [evaluation.md](../evaluation.md):
the errors were planted by the author of the checks, and the parts of the
review written by models are not measured there.

## The reproduction

| Stage | What it does | Runs on |
| --- | --- | --- |
| Plan | Extracts checkable claims with expected values, tolerances and missing details. For arXiv papers, the numbers of a table row are copied by code, not by the model | Nemotron 3 Ultra |
| Analyze | Turns each missing detail into an assumption with plausible alternatives; searches the web for the authors' code and for details deferred to a cited work (read when it is on arXiv) | Nemotron 3 Ultra, Nano, Tavily |
| Implement | Writes a script per claim, runs it and repairs it from the error, with Ultra taking over after two failures. A result only counts if the script passes a scan for values copied from the paper among the numbers the result is computed from, and a review for fabricated computations by a model that did not write it | Nemotron 3 Super, Nano, Ultra |
| Verify | Compares with the paper within tolerance and re-runs each claim varying one assumption at a time | Code |
| Report | Lays out the verdicts by code; the model only writes the narrative | Nemotron 3 Ultra |

The reproduction part of the report opens with what it covers: every section,
table and figure of the paper, with the claims taken from it or the reason
nothing was (theory, a description of the method, results that need the
paper's data, timings). Tables and figures are found by code, so none is
skipped silently.

Claims that fail on their own get a second chance: when one result of an
experiment has been reproduced to many digits, its script fixes the setup,
and the claims still failing are written again starting from it.

## Verdicts and confidence

- **Reproduced**: the result matches the paper, whatever is assumed.
- **Reproduced under an assumption**: the paper's numbers come out for one
  value of a detail the paper omits and not for others, which identifies the
  value the authors used.
- **Inconclusive, depends on a missing detail**: no tried value settles it.
- **Not reproduced**: the result does not match and no missing detail explains it.
- **Not verifiable**: hardware-dependent (timings, speedups).
- **Value not checked (data missing)**: the result needs inputs the paper only
  cites. The method is still rebuilt and run on substitute data, to test what
  the claim implies beyond its number; it never says the paper's number is
  right. Supply the data (`--data images/ results.csv`) and the claim is
  audited for real.
- **No result**: no working script.

Confidence is set by fixed rules, not by a model. It is **high** only when
numbers printed in the paper are recomputed to at least six agreeing
significant digits in total, under no assumption. Every other verdict lists its
warnings: a match of one or two digits that a wrong computation could also
hit, a pass criterion the agent chose, a mismatch that may be the agent's own
error.

## Same paper, same report

The shared inference endpoints are not deterministic: the same request at
temperature 0 with a fixed seed returns different text from one call to the
next. So every non-deterministic step (model call, web search, arXiv download,
script run) is computed once and recorded in `store/` under the hash of its
exact input. Auditing the same paper again gives the same report byte for
byte, with no model calls.

```
python -m auditor 2504.00560 --redo         # a new attempt: the models are asked again
python -m auditor 2504.00560 --attempt 1    # back to the first one
```

A full audit takes 3 to 8 minutes and costs $0.25–1.00; the review alone about
a minute and $0.10–0.25. Token Factory has no server-side spending limit, so
`auditor/llm.py` keeps a local ledger and stops at `SPEND_CAP_USD`.

## The public demo and its budget

`DEMO_MODE=1 HOST=0.0.0.0 python app.py` serves the page for others while
protecting the budget:

- The reports in `examples/` open at once, with no model call; so does any
  paper audited before.
- A new paper gets the review only. New papers are limited per visitor
  (`DEMO_NEW_PER_SESSION`, 2) and per day (`DEMO_NEW_PER_DAY`, 6), PDFs to
  `DEMO_MAX_PAGES` (25) pages, and none is accepted once spending is within
  `DEMO_RESERVE_USD` (1.0) of `SPEND_CAP_USD`. Audits run one at a time.

To publish it for free on Render: "New > Blueprint", pick this repository, and
give it `NEBIUS_API_KEY` and `TAVILY_API_KEY`. `render.yaml` sets a $5 cap, VAT
included (`VAT_RATE=0.21`). A free service sleeps after 15 minutes without
visits and wakes up in about a minute.

`python tools/look.py [--demo]` opens the page in a headless browser and saves
screenshots in `screenshots/`.

## Known limitations

- The review is a model's reading. Quotes and the challenge remove unfounded
  concerns; they do not make the remaining ones right, and a problem the model
  did not notice is not reported.
- Figures are described by a small vision model, which misreads some labels.
  Nothing in the report depends on a value read off a figure.
- The endpoint sometimes answers with its own error message instead of a
  reply. Such a reply is retried and never recorded; a step it keeps failing
  on is skipped on the cautious side.
- Generated scripts run in a separate process, in a temporary folder, with no
  API keys in their environment. That is not a full sandbox: on a public
  server, run the app in a container.
- A "not reproduced" verdict can be a bug in the generated code rather than in
  the paper. The report shows a second opinion on every mismatch.
- Claims taken from running text, and every claim of a PDF, are read by a
  model and can misreport the paper. Use an arXiv id when possible: the LaTeX
  source is exact.
- Compared on the same 16 claims, six models on Token Factory reproduced 3 to
  6 each on the first try, and Nemotron Super tied for best. About a third of
  the failures came from how the claim was posed, which the pipeline now
  handles in code.
