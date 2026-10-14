# Paper Reproducibility Auditor

An agent that does a referee's work on a scientific paper. Give it a PDF or an
arXiv id and it reads the paper the way a reviewer does (is everything there,
does it hold together, can it be reproduced, how does it stand against related
work), and then tries to recompute the results that can be recomputed. It does
not promise a "replicated: yes/no": it says what it checked, how, and how far
each conclusion can be trusted.

Built for the Nebius x NVIDIA Global AI Hackathon.

## How it works

```
paper ──> Ingest ──> Figures ──> Review ──> Related work ──> Plan ──> Analyze ──> Implement ──> Verify ──> Report
          (text)     (images)    (referee)  (web search)     (claims) (assumptions) (code + runs) (verdicts)
          └──────────── the review: any paper, about a minute ───────────┘└──── the reproduction: computable results ────┘
```

### The review

It needs no data and applies to any paper. `--review-only` stops after it.

| Step | What it does | Runs on |
| --- | --- | --- |
| Figures | Finds each figure in the PDF by its caption, cuts it out and has it described, so the review is not limited to captions. Descriptions are a reading aid: values read off a plot are not used as numbers | MiniCPM-V |
| Review | Summary, strengths, major and minor concerns, a ten-point reproducibility checklist, questions for the authors | Nemotron 3 Ultra |
| Challenge | Every concern is argued against by a second reading of the whole paper. It is withdrawn when another passage answers it, or when both Ultra and Super, reading independently, find the fact it rests on is not so | Nemotron 3 Ultra, Super |
| Number checks | Code recomputes every "Avg."/"Total" column and row of the tables (from the LaTeX source, or for a PDF from its text layer, read by PyMuPDF with no model), every percentage printed beside its counts ("113 of 150 (75.3%)"), and looks for each number of the abstract in the body, in the same context (a unit or the words around it). It also finds a result of the abstract printed in the body with another value ("BLEU score of 41.8" against "BLEU score of 41.0" about the same task). The model points at further relations, which code computes. A mismatch that rests on a reading (the model's expression, or code matching by wording) is reported only if a model that did not set it up agrees both sides are the same quantity computed as the paper defines it; one off by a round factor (2, 10, 1000) is taken as a dropped factor, not an error of the paper. Rounding of printed inputs is never a mismatch | Plain code, Nemotron 3 Ultra and Super |
| Related work | Searches the web for the closest work, keeps results that are papers, takes the year from the address where it is there (arXiv id, ACL id), and checks by code whether the paper cites each one; a work later than the paper is marked as such, not as uncited | Tavily, Nemotron 3 Ultra |

A model's opinion does not reach the report on its own word:

- A concern must quote the paper. The quote is looked up in the paper's text
  (not in the figure descriptions), and a concern whose quote is not there is
  discarded. So are complaints about the copy rather than the paper.
- The concerns that survive are challenged. The report lists the withdrawn ones
  too, with the passage that answered them.
- Related works are only ones the search returned, judged from title and
  snippet, not read. A work with no year in its address can still be later
  than the paper. "Not found in the paper" means its full title is not in the
  text.
- Figures drawn as vectors carry their labels as text in the PDF; those are
  handed to the vision model so it spells them as printed.

- Some facts are checked by code, and a model's claim about them is replaced
  by the code's answer: whether every `\ref` and `\cite` of a LaTeX source is
  defined, and whether sections are duplicated. Models got both wrong: missing
  references that were there, and "duplicated sections" in two papers whose
  sections each appear once. In a PDF transcribed in overlapping strips,
  repeated text is a property of the copy, so such a concern is withdrawn.
- A concern whose quote is not found gets one more chance: the model is shown
  the paper's own text and asked for the sentence it meant.

Tested on nine papers: six arXiv LaTeX sources (Transformer, Adam's wrapper
fell back to its PDF, LoRA, VAE, ViT, a 2025 numerical-methods paper), two
PDFs (a Catalan thesis paper, the LIGO detection letter) and a 1963 scan.
What it finds:

- *Attention Is All You Need*: the English-French BLEU of the big model is
  41.8 in the abstract and the table and 41.0 in the text. Found by code,
  confirmed by a model, on every run.
- Adam: the convergence theorem assumes decaying step sizes and β₁, while the
  algorithm as written uses constants.
- LIGO: the 35–250 Hz sweep and the 1.0 × 10⁻²¹ peak strain of the abstract
  are not printed in the body (they are read off Figure 1).
- LoRA and ViT: the 14 GLUE averages and 4 "Average" rows recomputed from the
  table cells, all consistent.

An average planted wrong by one point in a copy of LoRA's table, a number of
the abstract changed to one the body does not print, and a percentage that
does not match its counts were all caught; the clean copies gave no mismatch.
Mismatches that were false and are now stopped: a model's parameter count that
dropped a factor of 2 (six of them on LoRA), and a "3.0" of the abstract
matched to a "Creative Commons 3.0" licence.

Still weak: on papers without tables of averages or percentages the number
checks find little, because the model rarely sets up a relation between
numbers correctly (it missed 36 + 29 − 62 = 3 solar masses in LIGO).

### Measured

`python tools/evaluate.py` plants errors in copies of the papers audited so
far and counts how many the checks made by code catch. On nine papers (six
LaTeX sources, two PDFs, one scan): 108 errors planted, 108 caught, across
table averages and totals, abstract results the body does not print, a result
printed with two values, percentages that do not match their counts, undefined
references and missing bibliography entries. On the unmodified papers, the
only flags are two real problems of those papers. The full table and its
limits are in [evaluation.md](evaluation.md): the errors were planted by the
author of the checks, and the parts of the review written by models are not
measured there.

### The reproduction

| Stage | What it does | Runs on |
| --- | --- | --- |
| 1. Ingest | Gets the paper text with equations intact: the arXiv LaTeX source when there is one, otherwise the PDF transcribed strip by strip (with the text layer as reference when the PDF has one) | MiniCPM-V for PDFs |
| 2. Plan | Extracts checkable claims with expected values, tolerances and missing details | Nemotron 3 Ultra |
| 3. Analyze | Turns each missing detail into an assumption with plausible alternatives; searches the web for the authors' code and omitted details | Nemotron 3 Ultra, Nano, Tavily |
| 4. Implement | Super writes a script per claim, runs it and repairs it from the error, with Ultra taking over after two failures. A result only counts if the script passes a scan for values copied from the paper, or the paper's own formula, among the numbers the reported value is computed from (a value printed beside the result for comparison does not count), and a review for fabricated computations by the model that did not write it. A mismatch gets a second opinion from Ultra that checks the script against the paper | Nemotron 3 Super, Nano, Ultra |
| 5. Verify | Compares with the paper within tolerance and re-runs each claim varying one assumption at a time | Plain code, no model |
| 6. Report | Writes the audit; verdict tables are laid out by code, the model only writes the narrative | Nemotron 3 Ultra |

The reproduction part of the report opens with what it covers: every section,
table and figure of the paper, with the claims taken from it or the reason
nothing was (theory, a description of the method, a figure, results that need
the paper's data, timings). Tables and figures are found by code, so none is
skipped silently.

Every claim gets a verdict, with the computed result next to the paper's:

- **Reproduced**: the result matches the paper, whatever is assumed.
- **Reproduced under an assumption**: the paper's numbers come out for one value
  of a detail the paper omits and not for others, which identifies the value
  the authors used.
- **Inconclusive, depends on a missing detail**: the result depends on a detail
  the paper omits and no tried value settles it.
- **Not reproduced**: the result does not match and no missing detail explains it.
- **Not verifiable**: hardware-dependent (timings, speedups).
- **Value not checked (data missing)**: the result was computed from inputs the
  paper only cites (test images, a dataset, measurements). The method is still
  rebuilt from the paper and run on substitute data that the script generates,
  to test what the claim implies beyond its number ("the parallel variant
  compresses worse than the sequential one"). The verdict says whether that
  behaviour holds there, or only that the method could be implemented. It
  never says the paper's number is right.

Supply the data and those claims are audited for real: the page takes the files
next to the PDF, and the command line takes `--data images/ results.csv`. The
generated scripts read them from one folder, and the files' fingerprint is part
of the record, so the same paper with the same data gives the same report.
- **No result**: the agent could not produce a working script.

Each verdict also carries a confidence, set by fixed rules rather than by a
model. It is **high** only when numbers printed in the paper are recomputed to
at least six agreeing significant digits in total, under no assumption. Every
other verdict lists its warnings: a match of one or two digits that a wrong
computation could also hit, a qualitative claim whose pass criterion the agent
chose, a mismatch that may be the agent's own error, two implementations that
disagree.

Claims that fail on their own get a second chance. When one result of an
experiment has been reproduced to many digits, its script fixes the setup
(scheme, parameters, initial conditions), and the claims still failing are
written again starting from it. What still disagrees is then checked against
the paper by a second model.

A detail only counts as missing if the paper really omits it: the agent has to
quote the paper to show a detail is stated, and the quote is looked up in the
text. When the paper defers a detail to a cited work, the agent searches for
that work with Tavily and, if it is on arXiv, reads it.

All model calls go to [Nebius Token Factory](https://tokenfactory.nebius.com)
through its OpenAI-compatible API.

## Install

Requires Python 3.12.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then add NEBIUS_API_KEY and TAVILY_API_KEY
```

## Use

In the browser:

```
python app.py                          # then open http://127.0.0.1:7860
```

Upload a PDF or type an arXiv id, watch the audit run, read the report. Tick
"Review only" for the referee's reading without the re-computation.

From the command line:

```
python -m auditor 2504.00560                 # an arXiv id (preferred: uses the LaTeX source)
python -m auditor papers/paper.pdf           # a PDF
python -m auditor 1706.03762 --review-only   # the review alone: about a minute, $0.10-0.25
```

Options: `--max-claims N` (default 20), `--review-only`, `--data PATH...`,
`--fresh` to rebuild the run folder.

### Public demo

`DEMO_MODE=1 HOST=0.0.0.0 python app.py` serves the page for others while
protecting the budget. It opens on three featured reports, each with the main
thing it found, and every report starts with its key findings. Budget
protection:

- The reports in `examples/` (part of the repository, so a fresh server has
  them) and in `runs/` open at once from a list, with no model call.
- A paper audited before gets its stored report, also at no cost.
- A new paper gets the review only (the re-computation is shown on the
  examples). New papers are limited per visitor (`DEMO_NEW_PER_SESSION`, 2)
  and per day (`DEMO_NEW_PER_DAY`, 6), PDFs to `DEMO_MAX_PAGES` (25) pages,
  and none is accepted once spending is within `DEMO_RESERVE_USD` (1.0) of
  `SPEND_CAP_USD`. Data uploads are off. Audits run one at a time.

To publish it for free on Hugging Face Spaces: create a Space with the Gradio
SDK, push this repository to it, and add at the top of the Space's README the
lines `---`, `sdk: gradio`, `app_file: app.py`, `---`. In the Space's settings,
add the secrets `NEBIUS_API_KEY` and `TAVILY_API_KEY` and the variables
`DEMO_MODE=1`, `HOST=0.0.0.0` and `SPEND_CAP_USD` set to what the demo may
spend (the Space keeps its own ledger, which starts at zero and is reset when
the Space restarts). A free Space sleeps after two days without visits and
wakes up, in about a minute, on the next one.

To see the page as a visitor does, `python tools/look.py [--demo] [--example
"Attention"]` starts it, opens it in a headless browser, opens an example
report, expands its folded sections and saves screenshots in `screenshots/`
(needs `pip install playwright` and `python -m playwright install chromium`).
Output goes to `runs/<paper>/`: `report.md`, `audit.json`, one folder per claim
with the generated script, and `trace/` with every model reply. For every
claim the report gives what the script was asked to do, the rule that produced
the verdict, and the script itself.

## Same paper, same report

The shared inference endpoints are not deterministic: the same request at
temperature 0 with a fixed seed returns different text from one call to the
next (9 identical requests gave 8 or 9 distinct replies for every Nemotron
model we tried). So every non-deterministic step (model call, web search, arXiv
download, script run) is computed once and recorded in `store/` under the hash
of its exact input. Each later step builds its input from the paper and from
earlier results, which pins the whole chain: auditing the same paper again,
even from an empty `runs/` folder or under another file name, gives the same
report byte for byte, with no model calls.

The first audit of a paper fixes its result. To audit a paper again from
scratch, ask for a new attempt; earlier attempts stay available:

```
python -m auditor 2504.00560 --redo         # new attempt, models asked again
python -m auditor 2504.00560 --attempt 1    # back to the first one
```

Whichever attempt was selected last is the one every later run reproduces.

Every claim the plan finds is audited, up to 20. Such an audit takes 3 to 8
minutes and costs $0.25-1.00 in model calls, most of it on the claims that do
not reproduce; claims are audited in parallel. Token Factory has no
server-side spending limit, so `auditor/llm.py` keeps a local ledger and stops
at `SPEND_CAP_USD` (default 35). The review alone takes about a minute for an
arXiv source and two for a PDF that has to be transcribed.

## Known limitations

- The review is a model's reading. Quotes and the challenge remove concerns
  that are unfounded; they do not make the remaining ones right, and a real
  problem the model did not notice is not reported. A concern withdrawn as
  "not so on a second reading" is one reading against another, with nothing to
  quote, which is why the report shows it instead of hiding it.
- Figures are described by a small vision model. It gets the kind of figure and
  most labels right and misreads some (an axis title, a legend entry). Nothing
  in the report depends on a value read off a figure.
- The endpoint sometimes answers with its own error message ("Agent failed …
  timed out") in place of a reply. Such a reply is retried and never recorded.
  A step of the review the endpoint keeps failing on is skipped on the
  cautious side (an unconfirmed mismatch is not reported, an unchallenged
  concern is kept), and a claim it keeps failing on gets "no result" while
  the other claims are audited.
- Generated scripts run in a local subprocess, in a temporary folder outside
  the project and with no environment variable beyond what Python needs: the
  API keys are not in their environment and the `.env` file is not reachable by
  a relative path. That is not a sandbox: the network and absolute paths are
  open. Do not audit untrusted papers on a machine you care about; on a public
  server, run the app in a container.
- A "not verified" verdict can still be a bug in the agent's implementation
  rather than a problem in the paper. The report shows the second opinion on
  every mismatch. In our tests about 6 of 8 claims per paper get a sound
  verdict, and which ones fail changes from run to run.
- Claims are extracted by a model and can misreport the paper. Expected values
  copied from the wrong table are recovered when the computed numbers are found
  printed in the paper; a misread qualitative claim may go unnoticed.
- For arXiv papers, table rows are the backbone of an audit and no model copies
  them: each row of each LaTeX table gets a tag, the model only points at the
  row, and the numbers, their column headings, the caption and the paragraph of
  the paper that introduces the table are filled in by code. Claims taken from
  running text or figure captions are still read by a model and can be wrong;
  for PDFs, where tables arrive as transcribed text, all claims are.
- Transcribed PDFs can contain a misread digit or formula. Pages are read in
  five strips because at three a sign in an equation was misread every time;
  that does not rule out other misreadings. Use an arXiv id when possible: the
  LaTeX source is exact.
- Compared on the same 16 claims, six models on Token Factory (Nemotron Super
  and Ultra, DeepSeek V4 Pro and Flash, Kimi K2.7 Code, gpt-oss-120b) each
  reproduced 3 to 6 on the first try, and Nemotron Super tied for best. The
  ceiling is not the choice of model: about a third of the failures came from
  how the claim was posed or how the script handed back its result, which the
  pipeline now handles in code.

## License

MIT. See [LICENSE](LICENSE).
