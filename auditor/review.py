"""The referee's reading of a paper: what a careful human reviewer checks without re-running anything.

Three passes over the paper, and one rule for all: nothing reaches the report
unless it can be tied to the paper's own words.

- Internal consistency. The model points out where numbers in the paper can
  be checked against each other (a percentage and its counts, parts and their
  total, a ratio and its two terms, a value stated twice) and writes each
  check as arithmetic. The arithmetic is done here, by code, and so is the
  comparison: whether the numbers agree is not a matter of opinion.
- Findings. Strengths, concerns, a reproducibility checklist and questions
  for the authors. Each concern must carry an exact quote; a concern whose
  quote is not in the paper is dropped as unfounded.
- Challenge. A quote ties a concern to the paper without making it right, so
  the concerns that are left are argued against, and withdrawn when another
  passage of the paper answers them.
"""

import itertools
import json
import re
import unicodedata

import openai

from .ingest import table_rows
from .llm import SpendCapReached, chat_json, say
from .plan import evaluate
from .verify import printed_resolution

CHECKLIST = [
    "Data available or fully described",
    "Code available",
    "Method described fully enough to implement",
    "Parameters and settings given",
    "Hardware and software environment given",
    "Randomness controlled (seeds, repetitions)",
    "Variability reported (error bars, repeated runs)",
    "Comparisons or baselines adequate",
    "Metrics defined",
    "Limitations discussed",
]

SCALES = {"100", "1000"}  # factors of a percentage or a unit change: not numbers of the paper
FAR_APART = 1500          # characters, with spaces and punctuation removed
# A concern that a reference, label or citation is not defined: checked by code instead, in a LaTeX source.
MISSING_REFERENCE = re.compile(
    r"(?i)(?:\\ref|\\cite|\\label|\blabels?\b|\bcitations?\b|\bcited\b|\breferences?\b|\bbibliograph\w*|\bequations?\b)"
    r"[^.]{0,120}\b(?:missing|undefined|not (?:defined|appear\w*|present|found|listed|included))"
    r"|\b(?:missing|undefined)\b[^.]{0,40}(?:\blabels?\b|\bcitations?\b|\breferences?\b|\bbibliograph\w*)")
# A concern that parts of the paper are duplicated.
DUPLICATION = re.compile(r"(?i)\bduplicat\w*|\brepeated (?:nearly |almost )?(?:verbatim|twice|multiple)|"
                         r"\b(?:appears?|occurs?|repeated|printed|reproduced|shown|listed|included) "
                         r"(?:twice|two times|three times|multiple times|several times|more than once)|"
                         r"\bverbatim (?:copy|repetition)")
THOUSANDS = re.compile(r"(?<=\d)[   ](?=\d{3}(?!\d))")  # a space between thousands: "203 000"
SECOND_READER = "super"   # a different model from the one that wrote and challenged the concerns
SUPER_LIMIT = 80000       # characters: above this Super's endpoint times out (seen on LoRA and LIGO)
SIGNIFICANT = 3          # digits a checked value must have: fewer is a setting, not a result
FORMULA = re.compile(r"[=<>≤≥√∑∫∂±×·^_\\$]|[Ͱ-Ͽ]|[⁰-₟]|[∀-⋿]")  # math in a quoted piece
RUN, MOSTLY = 30, 0.8    # a quote with slips is the paper's when 80% of it is there in runs of 30+ characters
# A complaint about the transcription the model was given, not about the paper.
ABOUT_THE_COPY = re.compile(r"(?i)\b(?:provided|supplied|given|extracted|available) (?:text|pdf|copy|excerpt|transcri\w+)"
                            r"|not (?:shown|present|included|visible|reproduced) in the (?:text|pdf|copy|excerpt)"
                            r"|the review(?:er)? cannot (?:verify|see|assess)"
                            r"|\blatex (?:source|code|labels?|markup)|\b(?:citation|bibtex|bibliograph\w*|label) keys?\b")

CHECKS_PROMPT ="""You are refereeing the paper below and checking its internal
consistency, as a careful reviewer does with a calculator. Find every place
where numbers printed in the paper can be checked against each other:
- a percentage and the counts it comes from;
- parts that should add up to a total, percentages that should add up to 100;
- a ratio, speed-up or improvement and the two quantities it is the ratio of;
- the same quantity stated in two places (abstract, text, table, caption, conclusions);
- a value that follows from a formula in the paper with inputs the paper states;
- a comparison in words ("twice as fast", "12% lower") and the numbers behind it.

A check always relates SEVERAL numbers of the paper: an expression that
combines some of them, and another number of the paper that the expression
should equal. A number on its own is not a check. Write the expression with
the actual numbers, never with symbols. Do not judge whether a check holds:
the arithmetic is done afterwards.

Check RESULTS: values the paper measured or computed and reports (entries of
tables, percentages, speed-ups, errors, scores, counts, totals, averages of
listed values, differences the text quotes between two table entries). Go
through every table row by row looking for them. Do not check a setting
against its own definition (a dimension that is by construction the ratio of
two hyperparameters, a midpoint of a range), and do not compare a value with
itself.

Reply with a JSON object and nothing else:
{{"checks": [{{
   "what": "what is being checked, in one sentence, in English",
   "expression": "arithmetic on numbers printed in the paper, e.g. 113/150*100",
   "stated": 75.3,
   "quote": "exact words of the paper where the stated result appears",
   "second_quote": "for a value stated twice: the exact words of the other place; otherwise empty"
}}]}}
"stated" is a plain number and it is the number AS PRINTED in the paper (the
10000 of "reduces parameters by 10,000 times", the 75.3 of "75.3%"), never
the result of your own expression: the point is to compare the two. The
expression derives the stated number from OTHER numbers of the paper and must
not contain it. Examples of the form (not of this paper):
- the text says 113 of 150 runs succeeded and "75.3% succeeded":
  expression 113/150*100, stated 75.3;
- the method section says each of the L=6 blocks holds three d x d matrices
  with d=256, and a table states 1.18M parameters for them: expression
  6*3*256*256, stated 1.18e6 (follow the paper's own formula, every factor);
- the abstract says training is "3x faster" and a table gives 12.6 h against
  4.1 h: expression 12.6/4.1, stated 3;
- a total row of 1,204 and parts 400, 512 and 292: expression 400+512+292, stated 1204. Write
large quantities in the paper's units or with powers of ten (175e9 for
"175B"). Use only numbers, + - * / **, sqrt, log, exp and parentheses in
"expression". Copy quotes character by character, in the
language of the paper, without translating: they are looked up in the paper and
a check whose quote is not found is thrown away. List up to 25 checks, the most
consequential first; fewer is fine if the paper has few.

PAPER:
{paper}

Now reply with the JSON object described above and nothing else.
"""

FINDINGS_PROMPT = """You are an expert referee reviewing the paper below for a
journal. Write the review a careful human reviewer would write: specific to
this paper, critical where it deserves it, fair where it does not. Write in
English whatever the language of the paper.

Every strength and every concern must be tied to a passage of the paper,
quoted exactly (the quotes are looked up; a point whose quote is not found is
discarded). Prefer few well-founded points to many generic ones. Do not raise a
concern you cannot support with what the paper says or fails to say.

Reply with a JSON object and nothing else:
{{"title": "the paper's title alone, as written, without the journal, institution or degree printed around it",
 "year": "the year the paper is dated, as a number, or null if it prints none",
 "summary": "what the paper does and what it claims, in 3-5 sentences",
 "strengths": [{{"point": "...", "quote": "exact words of the paper"}}],
 "concerns": [{{
    "severity": "major" | "minor",
    "category": "soundness" | "evidence" | "completeness" | "clarity" | "consistency",
    "point": "the problem, stated precisely",
    "quote": "exact words of the paper it refers to",
    "suggestion": "what the authors should do about it"
 }}],
 "checklist": [{{"item": "<one of the items below, copied>", "status": "yes" | "partly" | "no" | "not applicable",
                "quote": "exact words that support the status, or empty", "note": "one sentence"}}],
 "questions": ["a question for the authors whose answer would change the assessment"]
}}

Categories: "soundness" is a flaw in the method or reasoning; "evidence" is a
conclusion the data shown does not support; "completeness" is something
needed to reproduce or assess the work that is missing; "clarity" is an
undefined symbol, an unexplained step, a figure that is not discussed;
"consistency" is the paper contradicting itself.

The paper's text may end with descriptions of its figures made from the images
by a vision model. Use them to judge whether figures are explained and support
the text, but do not quote them (they are not the paper's words) and do not
rely on values read off a plot.

Review the paper, not the copy you were given. The text may come from a PDF: a
table can appear as rows of numbers run together after its caption, a page can
be repeated, a figure is an image you only have a description of. None of that
is a fault of the paper, and "not present in the provided text" is never a
concern. Before saying something is missing, look for it in the whole text.
Quote plain text as it appears, without LaTeX escapes for accents. If the text
is LaTeX source, the names inside \\ref, \\label and \\cite are the authors'
internal names, which a reader sees as numbers: never comment on them. Keep
quotes short (one or two sentences) and prefer prose to formulas.

Checklist items, all of which must appear:
{checklist}

PAPER:
{paper}

Now reply with the JSON object described above and nothing else.
"""


REQUOTE_PROMPT = """A referee made the points below about the paper that follows,
but the passage quoted for each was not found in the paper: it was paraphrased,
shortened, or taken from somewhere else. For each point, find the ONE sentence
of the paper that best supports it and copy it exactly, character by
character: a single stretch of text, with no "..." and nothing left out. Pick
a sentence of prose rather than a formula. If the text is LaTeX source, copy
it as written there, commands included ($h\\omega$, not hω). If no sentence of
the paper supports the point, give an empty quote.

Reply with a JSON object and nothing else:
{{"quotes": [{{"id": 1, "quote": "..."}}]}}

POINTS:
{points}

PAPER:
{paper}

Now reply with the JSON object described above and nothing else.
"""

CONFIRM_PROMPT = """Each check below puts side by side a number the paper
states and another value, an expression computed from other numbers of the
paper or the same result printed elsewhere, and the two disagree. Before
reporting that the paper contradicts itself, make sure the two sides are about
the same thing and the computation is right. For each check, look in the paper
and answer two questions about the setup, not about whether the numbers match
(they do not, that is given):
1. "same_quantity": do both sides refer to exactly the same quantity (same
   model, setting, dataset, unit), so that if the paper were consistent they
   would be equal? False if the check mixes up quantities, units, rows or
   settings.
2. "computed_as_defined": is the expression exactly how the paper itself
   defines or computes that quantity, every factor accounted for, using the
   paper's own formula? Work it out from the paper's definitions before
   answering. False if a factor is missing or extra, or the formula is not
   the paper's. True when the expression is just a value printed in the paper.

Reply with a JSON object and nothing else:
{{"verdicts": [{{"id": 1, "same_quantity": true, "computed_as_defined": true, "why": "one sentence"}}]}}

CHECKS:
{checks}

PAPER:
{paper}

Now reply with the JSON object described above and nothing else.
"""

PREMISE_PROMPT = """A referee raised the concerns below about the paper that
follows. Each rests on a fact about the paper (something is missing, repeated,
contradictory, claimed). Another reader says the fact is wrong. Settle it by
looking in the paper yourself: is what the concern states about the paper true?

Reply with a JSON object and nothing else:
{{"checked": [{{"id": 1, "premise_true": true, "why": "one sentence saying what the paper actually contains"}}]}}

CONCERNS:
{concerns}

PAPER:
{paper}

Now reply with the JSON object described above and nothing else.
"""

CHALLENGE_PROMPT = """A referee raised the concerns below about the paper that
follows. Referees make mistakes: they say something is missing when it is in
the paper, or they misread a passage. Act as the authors answering the review.
For each concern, look through the whole paper, tables and appendices
included, for a passage showing the concern is wrong: what is said to be
missing is there, or the paper says the opposite of what the referee
understood.

Reply with a JSON object and nothing else:
{{"checked": [{{"id": 1, "verdict": "stands" | "answered" | "unsupported",
              "quote": "exact words of the paper that answer the concern, or empty",
              "why": "one sentence"}}]}}
- "answered": a passage you quote settles the concern. A passage that merely
  touches the subject does not, and neither does the one the referee quoted.
- "unsupported": the concern states as fact something about the paper that is
  not so when you check it (a section said to be repeated that appears once, a
  number said to differ that does not, a claim the paper does not make), or it
  is about the file and not the work (LaTeX labels, the layout of the copy).
  Check the fact itself in the text before choosing this.
- "stands": otherwise, including concerns that are matters of judgement.
Copy quotes character by character: they are looked up in the paper, and an
answer whose quote is not found is ignored.

CONCERNS:
{concerns}

PAPER:
{paper}

Now reply with the JSON object described above and nothing else.
"""


def optional(fallback, step, *args, **kwargs):
    """Run a step the review can do without; if the endpoint fails it, go on with `fallback`.

    The fallback is always the cautious side: an unconfirmed mismatch is not reported, an
    unchallenged concern is kept. Running out of budget is not a failure of the step and stops all.
    """
    try:
        return step(*args, **kwargs)
    except SpendCapReached:
        raise
    except (RuntimeError, openai.APIError) as error:
        say(f"  {step.__name__} skipped: {str(error)[:160]}")
        return fallback


def squeeze(text: str) -> str:
    """Letters and digits only, accents removed: "màxim" and the "m\\`axim" a model writes for it are the same."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def anchored(quote, squeezed_paper: str) -> bool:
    """Whether a quote is really in the paper, whatever its spacing, accents or markup.

    A quote with omissions ("first words ... last words") is in the paper when every piece is.
    """
    raw = [piece for piece in re.split(r"\.{3,}|…|\[\.\.\.\]", str(quote or "")) if len(squeeze(piece)) >= 12]
    found = [squeeze(p) in squeezed_paper or mostly_in(squeeze(p), squeezed_paper) for p in raw]
    if raw and all(found):
        return True
    # A formula retyped in symbols ("hω < √(42-6√29)") cannot be matched against its LaTeX source. With
    # omissions, such a piece is excused when every piece of prose is found, and the prose found is long.
    prose = [(p, ok) for p, ok in zip(raw, found) if not FORMULA.search(p)]
    return len(raw) > 1 and bool(prose) and all(ok for _, ok in prose) and sum(len(squeeze(p)) for p, _ in prose) >= 40


def mostly_in(quote: str, squeezed_paper: str) -> bool:
    """Whether a long quote is the paper's text but for a few slips: most of it is there in long runs.

    A model copying three lines of LaTeX gets a line break or an escape wrong; the passage is
    still the paper's. Runs shorter than RUN characters count for nothing, so words in common do not.
    """
    covered, start = 0, 0
    while start < len(quote):
        low, high = 0, len(quote) - start
        while low < high:  # the longest run from here that is in the paper
            middle = (low + high + 1) // 2
            low, high = (middle, high) if quote[start:start + middle] in squeezed_paper else (low, middle - 1)
        if low >= RUN:
            covered += low
            start += low
        else:
            start += 1
    return covered >= MOSTLY * len(quote)


def consistency(paper: str, squeezed_paper: str) -> list[dict]:
    """Numerical cross-checks of the paper against itself, each one computed here."""
    # With reasoning: without it the model lists the paper's numbers instead of relating them.
    proposed = chat_json("ultra", [{"role": "user", "content": CHECKS_PROMPT.format(paper=paper)}],
                         key="checks", thinking=True, max_tokens=12000, purpose="consistency")["checks"]
    # Numbers compared by their significant digits: 175B written out as 175000000000 is the paper's 175.
    paper = THOUSANDS.sub("", paper)  # "67 400" with a thin space is one number
    printed = {re.sub(r"\D", "", n).strip("0") for n in re.findall(r"\d+(?:[.,]\d+)?", paper)}
    checks = []
    for check in proposed if isinstance(proposed, list) else []:
        if not isinstance(check, dict):
            continue
        stated = number(check.get("stated"))
        expression = str(check.get("expression", ""))
        value = evaluate(expression)
        given = [check.get("quote"), check.get("second_quote")] + list(check.get("quotes") or [])
        quotes = [THOUSANDS.sub("", str(q)) for q in given if q and anchored(q, squeezed_paper)]
        if stated is None or value is None or not quotes:
            continue
        digits = re.sub(r"\D", "", repr(stated).split("e")[0]).strip("0")
        # the stated value must be a number printed in the passage: the "32" of "float32" is not a 2
        holding = [q for q in quotes if digits and digits in
                   {re.sub(r"\D", "", n).strip("0") for n in re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?", q)}]
        inputs = [re.sub(r"\D", "", n).strip("0") for n in re.findall(r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?",
                                                                       re.sub(r"[eE][-+]?\d+", "", expression))]
        if re.search(r"[-+*/]", expression.replace("e-", "e").lstrip("-")):
            # Arithmetic: every input must be a number the paper prints, and the result it is
            # compared with must be printed in a passage that was found. Sums of 0 and 1 check nothing.
            if not holding or not all(n in printed or len(n) < 2 or n in SCALES for n in inputs) \
                    or not any(len(n) >= 2 and n not in SCALES for n in inputs) or digits in inputs:
                continue  # the last: 175e9/10000 against 10,000 is the number compared with itself
            kind = "arithmetic"
        else:
            # The same value in two places: both passages must be found, both must contain it, and
            # they must be far apart (abstract and results, say), or it is one sentence quoted twice.
            places = sorted(p for p in (squeezed_paper.find(squeeze(q)) for q in holding) if p >= 0)
            if len(places) < 2 or places[-1] - places[0] < FAR_APART:
                continue
            if float(stated).is_integer() and len(str(int(abs(stated)))) < 4:
                continue  # a minibatch of 100 said twice: a setting, not a result
            kind = "restated"
        rounded = approximate(stated, holding)
        short = len(re.sub(r"\D", "", repr(stated).split("e")[0]).lstrip("0").removesuffix("0")) < SIGNIFICANT
        # 512/8 = 64 relates a setting to its own definition and cannot disagree; 36 + 29 - 3.0 = 62 relates
        # several measured numbers and can. A short value counts when two numbers of the paper meet in it.
        several = len({n for n in inputs if len(n) >= 2 and n not in SCALES}) >= 2
        if short and not (kind == "arithmetic" and (rounded or several)):
            continue
        allowed = max(printed_resolution(stated), 1e-9 * abs(stated))
        zeros = len(str(int(abs(stated)))) - len(str(int(abs(stated))).rstrip("0")) if float(stated).is_integer() else 0
        if zeros >= 2:  # "1 in 22 500 years": an integer ending in zeros was rounded at the last digit that is not
            allowed = max(allowed, 0.5 * 10 ** zeros)
        if rounded:
            # "by 10,000 times", "about 3x": a round figure claims only its leading digits
            figures = len(str(int(abs(stated))).rstrip("0")) if float(stated).is_integer() else None
            if figures:
                allowed = 0.5 * 10.0 ** (len(str(int(abs(stated)))) - figures)
        if any(c["expression"].replace(" ", "") == expression.replace(" ", "") and c["stated"] == stated for c in checks):
            continue  # the same arithmetic, worded differently
        low, high = reach(expression, value)
        checks.append({"what": str(check.get("what", ""))[:300], "kind": kind, "expression": expression,
                       "computed": value, "stated": stated, "consistent": low - allowed <= stated <= high + allowed,
                       "quotes": [" ".join(q.split())[:300] for q in holding]})
    return checks


def cell_number(cell: str) -> tuple[float, int] | None:
    """The number in a table cell and its decimals, or None if the cell is not a plain number.

    "87.5\\textsubscript{$\\pm$.3}" and "\\textbf{95.1}" are numbers; "0.3M" and "MNLI" are not.
    """
    text = re.sub(r"\\textsubscript\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "", cell)
    text = re.split(r"\$?\\pm|±", text)[0]
    text = re.sub(r"\\(?:textbf|textit|underline|mathbf|emph|bf)\b|[{}$\s*†‡]", "", text)
    match = re.fullmatch(r"-?\d+(?:\.(\d+))?%?", text)
    return (float(text.rstrip("%")), len(match.group(1) or "")) if match else None


def plain(latex: str) -> str:
    """LaTeX markup removed, for a label in the report: "$\\text{RoBERTa}_\\text{base}$" is "RoBERTa base"."""
    text = re.sub(r"\\(?:text\w*|mathrm|mathbf|emph|textsubscript|textsuperscript)\b|\\[a-zA-Z]+\*?", " ", latex)
    return " ".join(re.sub(r"[${}^~]|(?<!\w)_|_(?!\w)", " ", text).replace("_", " ").split())


AGGREGATE = re.compile(r"(?i)^\W*(avg|average|mean|total|sum|overall)\W*$")


def table_checks(latex: str, rows: dict | None = None) -> list[dict]:
    """Averages and totals in a table's rows, recomputed by code from the cells beside them.

    A column headed "Avg." or "Total" is checked in every row against the run of plain numbers
    immediately to its left. Each cell stands for anything that rounds to it, and the aggregate
    may sit two units of its last digit away, so rounding is never reported as a mismatch.
    The rows are those of the LaTeX source, or, for a PDF, those PyMuPDF read from it.
    """
    rows = rows if rows is not None else table_rows(latex)
    checks = []
    for tag, row in rows.items():
        table = tag.split(".")[0]
        headers = [r["cells"] for t, r in rows.items() if t.split(".")[0] == table
                   and int(t.split("R")[1]) < int(tag.split("R")[1])
                   and any(AGGREGATE.match(plain(c)) for c in r["cells"])]
        if not headers or len(headers[-1]) != len(row["cells"]):
            continue
        header = headers[-1]
        column = next(i for i, c in enumerate(header) if AGGREGATE.match(plain(c)))
        # A cell holding two values ("88.2/87.9", MNLI matched/mismatched) says the average is taken over
        # metrics the table does not all show (as GLUE's is): it cannot be recomputed from the cells.
        if any(re.search(r"\d\s*/\s*\d", c) for c in row["cells"][1:column]):
            continue
        stated = cell_number(row["cells"][column])
        run = []
        for i in range(column - 1, -1, -1):
            value = cell_number(row["cells"][i])
            if value is None:
                break
            run.insert(0, (i, value))
        if stated is None or len(run) < 2:
            continue
        mean = not re.search(r"(?i)total|sum", header[column])
        candidates = [run] + [run[1:], run[:-1]] * (len(run) > 2)  # a leading or trailing column may not count
        label = plain(row["cells"][0])[:60]
        def agrees(used: list) -> bool:
            values = [v for _, (v, _) in used]
            computed = sum(values) / len(values) if mean else sum(values)
            slack = max(0.5 * 10 ** -d for _, (_, d) in used) * (1 if mean else len(used))
            allowed = printed_resolution(float(f"{stated[0]:.{stated[1]}f}")) if stated[1] else 0.5
            return abs(computed - stated[0]) <= allowed + slack

        used = next((u for u in candidates if agrees(u)), run)  # the first reading that agrees, or the whole run
        values = [v for _, (v, _) in used]
        names = [header[j] for j, _ in used]
        checks.append({
            "what": f"{plain(header[column])} of {', '.join(plain(n) for n in names)} in row \"{label}\" "
                    f"of the table captioned \"{plain(row['caption'])[:70]}\"",
            "kind": "table",
            "expression": (f"({' + '.join(f'{v:g}' for v in values)}) / {len(values)}" if mean
                           else " + ".join(f"{v:g}" for v in values)),
            "computed": sum(values) / len(values) if mean else sum(values), "stated": stated[0],
            "consistent": agrees(used), "quotes": [" | ".join(row["cells"])[:300]], "by": "code"})
    return checks[:40]


PERCENT_OF = [
    # "113 of 150 (75.3%)", "113/150 (75.3 %)", "113 de 150 (75,3%)"
    (re.compile(r"(?<![\d.,])(\d+)\s*(?:of|out of|/|de|sobre)\s*(\d+)\b[^.\d%]{0,40}?\(?\s*(\d+(?:[.,]\d+)?)\s*\\?%"), (0, 1, 2)),
    # "75.3% (113/150)", "75.3 % (113 of 150)"
    (re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*\\?%\s*\(\s*(\d+)\s*(?:of|out of|/|de|sobre)\s*(\d+)\s*\)"), (1, 2, 0)),
]


def percentages(text: str) -> list[dict]:
    """Percentages printed beside the counts they come from, recomputed by code."""
    checks, seen = [], set()
    for pattern, (part, whole, share) in PERCENT_OF:
        for match in pattern.finditer(text):
            groups = match.groups()
            count, total = int(groups[part]), int(groups[whole])
            printed_share = groups[share].replace(",", ".")
            if not 0 < count <= total or (count, total, printed_share) in seen:
                continue
            seen.add((count, total, printed_share))
            stated, computed = float(printed_share), 100 * count / total
            sentence = " ".join(text[max(0, match.start() - 100): match.end() + 60].split())
            checks.append({"what": f"{printed_share}% printed beside the counts {count} of {total}", "kind": "arithmetic",
                           "expression": f"{count}/{total}*100", "computed": computed, "stated": stated,
                           "consistent": abs(computed - stated) <= printed_resolution(stated),
                           "quotes": [sentence], "by": "code"})
    return checks


def table_totals(latex: str, rows: dict | None = None) -> list[dict]:
    """Rows labelled "Total" or "Average" in a table, checked column by column against the rows above."""
    rows = rows if rows is not None else table_rows(latex)
    checks = []
    tags = list(rows)
    for index, tag in enumerate(tags):
        row = rows[tag]
        if not row["cells"] or not AGGREGATE.match(plain(row["cells"][0])):
            continue
        table = tag.split(".")[0]
        above = [rows[t]["cells"] for t in reversed(tags[:index]) if t.split(".")[0] == table]
        mean = not re.search(r"(?i)total|sum", row["cells"][0])
        for column in range(1, len(row["cells"])):
            stated = cell_number(row["cells"][column])
            if stated is None:
                continue
            values = []
            for cells in above:  # the rows directly above, up to the first that has no number there
                value = cell_number(cells[column]) if column < len(cells) and len(cells) == len(row["cells"]) else None
                if value is None:
                    break
                values.insert(0, value)
            if len(values) < 2:
                continue
            computed = sum(v for v, _ in values) / (len(values) if mean else 1)
            slack = max(0.5 * 10 ** -d for _, d in values) * (1 if mean else len(values))
            allowed = printed_resolution(float(f"{stated[0]:.{stated[1]}f}")) if stated[1] else 0.5
            header = plain(row["header"][column]) if column < len(row["header"]) else f"column {column + 1}"
            checks.append({
                "what": f"{plain(row['cells'][0])} row, column \"{header}\", of the table captioned "
                        f"\"{plain(row['caption'])[:70]}\"",
                "kind": "table",
                "expression": (f"({' + '.join(f'{v:g}' for v, _ in values)}) / {len(values)}" if mean
                               else " + ".join(f"{v:g}" for v, _ in values)),
                "computed": computed, "stated": stated[0],
                "consistent": abs(computed - stated[0]) <= allowed + slack,
                "quotes": [" | ".join(row["cells"])[:300]], "by": "code"})
    return checks[:40]


def abstract_of(text: str) -> tuple[int, int] | None:
    """Where the abstract is: the LaTeX environment, or in a transcribed PDF the text between the
    word "abstract" (or its equivalent) and the introduction."""
    latex = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, flags=re.DOTALL)
    if latex:
        return latex.start(1), latex.end(1)
    head = text[:12000]
    # a heading on a line of its own, possibly dressed in markup: "Abstract", "{\bf \large Abstract}", "**Abstract**"
    start = re.search(r"(?im)^(?:[^\w\\]|\\[a-z]+)*(?:abstract|resum|resumen|résumé|zusammenfassung)\b", head)
    intro = re.compile(r"(?im)^.{0,80}?\b(?:introduction|introducció|introducción)\b")
    if start:
        end = intro.search(head[start.end():])
        return (start.end(), start.end() + end.start()) if end else None
    # Journal letters print the abstract with no heading: it is the first long paragraph before the introduction.
    end = intro.search(head)
    if not end:
        return None
    first = next((m for m in re.finditer(r"[^\n]{300,}", head[:end.start()])), None)
    return (first.start(), end.start()) if first else None


STOPWORDS = set("the a an of in on to and or is are was were be by for with as at from that this which than its it "
                "we our has have not but also into over under between "
                # Catalan, Spanish, French, German: papers come in them too
                "de la el en y que les els i amb per del dels des le et un una uns unes al als es és són se su sus "
                "los las lo con para por como este esta estos aquest aquesta aquests mes més sobre entre "
                "une du au aux est sont der die das und mit von zu ist".split())


def context(text: str, start: int, end: int, before: int = 60) -> set[str]:
    """The words and units around a number: what makes 28.4 a BLEU score and not something else."""
    window = text[max(0, start - before): start] + " " + text[end: end + 40]
    return {w for w in re.findall(r"[a-zA-ZÀ-ɏ%×σ⊙]+", window.lower()) if w not in STOPWORDS and len(w) > 1
            or w in ("%", "×", "σ")}


def table_context(text: str, at: int, rows: dict) -> set[str]:
    """For a number in a tagged table row: the words of its table's caption, headings and row label."""
    line = text[text.rfind("\n", 0, at) + 1: text.find("\n", at) if text.find("\n", at) >= 0 else None]
    tag = re.search(r"\[(T\d+\.R\d+)\]", line)
    row = rows.get(tag.group(1)) if tag else None
    if not row:
        return set()
    words = " ".join([row["caption"], " ".join(row["header"]), row["cells"][0] if row["cells"] else ""]).lower()
    table = tag.group(1).split(".")[0]
    words += " " + " ".join(" ".join(r["cells"]) for t, r in rows.items() if t.startswith(table + ".")
                            and not any(cell_number(c) for c in r["cells"][1:])).lower()  # heading rows
    return {w for w in re.findall(r"[a-zÀ-ɏ%]+", plain(words)) if w not in STOPWORDS and len(w) > 1}


def restated_differently(abstract: str, body: str) -> list[dict]:
    """Results of the abstract printed again in the body with another value, as far as code can tell.

    "a BLEU score of 41.8" in the abstract and "a BLEU score of 41.0" in a sentence of the body about
    the same task: the same two words lead to the number and the passages share most of their words.
    Only candidates: they go to a second model before being reported.
    """
    found = []
    own = set(re.findall(r"\d+\.\d+", abstract))  # another result of the abstract is not a variant of this one
    for match in re.finditer(r"(?<![\w.])(\d+\.\d+)(?!\d)", abstract):
        lead = re.findall(r"[a-zA-Z]+", abstract[max(0, match.start() - 40): match.start()])[-2:]
        if len(lead) < 2 or all(w.lower() in STOPWORDS for w in lead):
            continue
        decimals = len(match.group(1).split(".")[1])
        mine = context(abstract, match.start(), match.end(), before=140)
        pattern = rf"(?i)\b{lead[0]}\W+{lead[1]}\W+(?:\$|\\num\{{|\{{)*(\d+\.\d{{{decimals}}})(?!\d)"
        # the context of each side is measured from its number, so the two leading words count on both
        candidates = [(mine & context(body, o.start(1), o.end(1), before=140), o) for o in re.finditer(pattern, body)
                      if o.group(1) not in own]
        # the passage closest to the abstract's: a value printed for the same thing would share its words
        for shared, other in sorted(candidates, key=lambda c: -len(c[0]))[:1]:
            if len(shared) >= 4:
                found.append({
                    "what": f"{match.group(1)} in the abstract and {other.group(1)} in the body, both after "
                            f"\"{' '.join(lead)}\" in passages about the same thing ({', '.join(sorted(shared)[:5])})",
                    "kind": "restated", "expression": other.group(1), "computed": float(other.group(1)),
                    "stated": float(match.group(1)), "consistent": False,
                    "quotes": [" ".join(abstract[max(0, match.start() - 100): match.end() + 30].split()),
                               " ".join(body[max(0, other.start() - 100): other.end() + 30].split())],
                    "by": "code"})
    return found


def derivation(value: float, token: str, sentence: str, body: str, rows: dict) -> str:
    """How an abstract number not printed in the body follows from printed ones, or ''.

    An improvement quoted beside a result ("80.5% (7.7 point absolute improvement)") is the difference
    between that result and the baseline the paper compares it with. The baseline is looked for where a
    paper puts it: in the same column of the table that prints the result, or within a few sentences of
    the result in the text. A paper prints hundreds of numbers, and differences taken across all of them
    would explain any value by coincidence.
    """
    # only a number the abstract words as a difference: "7.7% point absolute improvement", "+2.0 BLEU over"
    at = sentence.find(token)
    after = sentence[at + len(token): at + len(token) + 45] if at >= 0 else ""
    if not re.match(r"(?i)\s*(?:%|\\%|pp|points?|BLEU|F1)?\s*(?:points?\s+)?(?:absolute|relative)?\s*"
                    r"(?:improvement|gain|increase|reduction|better|higher|lower|over|above|below)", after):
        return ""
    decimals = len(token.split(".")[1]) if "." in token else 0
    half = 0.5 * 10 ** -decimals + 1e-9
    beside = {n for n in re.findall(r"(?<![\w.])\d[\d,]*\.\d+", sentence)} - {token}  # results quoted with it
    for a_text in sorted(beside):
        a = float(a_text.replace(",", ""))
        neighbours = set()
        for row in rows.values():  # the same column of the same table
            for j, c in enumerate(row["cells"]):
                if (cell_number(c) or (None,))[0] == a:
                    table = [r for r in rows.values() if r["caption"] == row["caption"] and r["header"] == row["header"]]
                    neighbours |= {cell_number(r["cells"][j])[0] for r in table
                                   if j < len(r["cells"]) and cell_number(r["cells"][j])}
        for m in re.finditer(rf"(?<![\w.]){re.escape(a_text)}(?!\d)", body):  # a few sentences around it in the text
            neighbours |= {float(n) for n in re.findall(r"(?<![\w.])\d+\.\d+(?!\d)", body[max(0, m.start() - 300): m.end() + 300])}
        for b in sorted(neighbours - {a}):
            # a baseline is of the same scale as the result it is compared with
            if 0.5 * a <= b <= 2 * a and abs(abs(a - b) - value) <= half:
                return f"{max(a, b):g} - {min(a, b):g}"
    return ""


def abstract_numbers(text: str) -> tuple[list[dict], list[dict]]:
    """The results the abstract quotes, each looked for in the rest of the paper.

    Returns (checks, concerns): a number found again in the body is a restated value that agrees; a
    number the body never prints is a claim of the abstract the paper does not show in text or tables.
    """
    text = re.sub(r"(?<=\d)[   ](?=\d{3}\b)", "", text)  # "203 000" with a thin space is one number
    span = abstract_of(text)
    if not span:
        return [], []
    rows = table_rows(text)
    abstract = text[span[0]:span[1]]
    # A PDF is transcribed in overlapping strips, so the abstract comes again near itself; and a paper
    # may repeat it on a title page. Those copies are not the body: every sentence of the body that is a
    # sentence of the abstract is left out.
    squeezed_abstract = squeeze(abstract)
    def echo(line: str) -> bool:  # a line that is the abstract again, not one that only begins like it
        squeezed = squeeze(line)
        return len(squeezed) >= 40 and (squeezed in squeezed_abstract or mostly_in(squeezed, squeezed_abstract))

    body = "\n".join(line for line in (text[:span[0]] + "\n" + text[span[1]:]).split("\n") if not echo(line))
    body_numbers = {n.replace(",", "") for n in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", body)}
    checks, missing, seen = [], [], set()
    for match in re.finditer(r"(?<![\w.\-])(\d[\d,]*\.\d+|\d{1,3}(?:,\d{3})+|\d{3,})(?![\w.]*\d)", abstract):
        token = match.group(1).replace(",", "")
        before, after = abstract[max(0, match.start() - 30):match.start()], abstract[match.end():match.end() + 1]
        if token in seen or re.fullmatch(r"(?:19|20)\d{2}", token) or "\\cite" in before \
                or after == "/" or re.search(r"(?i)doi|arxiv|isbn|issn|https?:", before):
            continue  # a year, a citation, a DOI or an identifier: not a result
        seen.add(token)
        sentence = next((s for s in re.split(r"(?<=[.!?])\s+", abstract) if match.group(0) in s), match.group(0))
        sentence = " ".join(sentence.split())[:300]
        if token in body_numbers:
            # The same digits elsewhere are the same result only in the same context: "3.0 solar masses"
            # is not the "3.0" of a licence. An occurrence must share a word or a unit with the abstract's.
            near = context(abstract, match.start(), match.end())
            at = next((m for m in re.finditer(rf"(?<![\w.]){re.escape(match.group(1))}(?!\d)|(?<![\w.]){re.escape(token)}(?!\d)", body)
                       if near & (context(body, m.start(), m.end()) | table_context(body, m.start(), rows))), None)
            if not at:
                continue  # printed again, but not visibly as the same quantity: neither confirmed nor missing
            where = " ".join(body[max(0, at.start() - 100): at.end() + 30].split())
            checks.append({"what": f"{match.group(1)}, quoted in the abstract, is also printed in the body of the paper",
                           "kind": "restated", "expression": match.group(1), "computed": float(token),
                           "stated": float(token), "consistent": True, "quotes": [sentence, where], "by": "code"})
        else:
            derived = derivation(float(token), token, sentence, body, rows)
            if derived:  # "80.5% (7.7 point improvement)": 7.7 = 80.5 - 72.8, with 72.8 in the results
                checks.append({"what": f"{match.group(1)}, quoted in the abstract, follows from numbers the paper "
                                       f"prints", "kind": "arithmetic", "expression": derived,
                               "computed": float(token), "stated": float(token), "consistent": True,
                               "quotes": [sentence], "by": "code"})
            else:
                missing.append((match.group(1), sentence))
    checks += restated_differently(abstract, body)
    concerns = []
    if missing:
        shown = ", ".join(n for n, _ in missing[:6])
        concerns.append({"severity": "minor", "category": "evidence", "by": "code",
                         "point": f"The abstract quotes {shown}, which {'is' if len(missing) == 1 else 'are'} not "
                                  "printed anywhere in the body of the paper, in text or tables. "
                                  "A reader cannot see where these results come from, unless they are read off a figure.",
                         "quote": missing[0][1],
                         "suggestion": "Report each number of the abstract in the results, in a table or the text."})
    return checks, concerns


def approximate(stated: float, quotes: list[str]) -> bool:
    """Whether the paper words a value as a round figure: "about 3x", "~10,000 times", "an order of 100"."""
    if not float(stated).is_integer():
        return False
    for quote in quotes:
        if re.search(r"(?i)~|≈|\babout\b|approx|\broughly\b|\baround\b|\bnearly\b|\balmost\b|\border of\b|\bup to\b", quote):
            return True
        number = f"{int(abs(stated)):,}"
        if re.search(rf"(?i)(?:{re.escape(number)}|{int(abs(stated))})\s*(?:×|x\b|times|-?fold)", quote):
            return True
    return False


def reach(expression: str, value: float) -> tuple[float, float]:
    """The lowest and highest value an expression can take given that its decimal inputs were rounded for print.

    A speed-up printed as 4.1 from times printed as 12.3 and 3.0 is not a mismatch with 12.3/3.0 = 4.1:
    each input stands for anything within half a unit of its last digit. Whole numbers are taken as exact counts.
    """
    decimals = [m for m in re.finditer(r"(?<![\w.])\d+\.(\d+)(?![\w.])", expression)]
    if not decimals or len(decimals) > 8:
        return value, value
    values = [value]
    for signs in itertools.product((-1, 1), repeat=len(decimals)):
        varied, shift = expression, 0
        for sign, m in zip(signs, decimals):
            places = len(m.group(1))
            moved = f"({float(m.group(0)) + sign * 0.5 * 10 ** -places:.{places + 2}f})"
            varied = varied[:m.start() + shift] + moved + varied[m.end() + shift:]
            shift += len(moved) - len(m.group(0))
        result = evaluate(varied)
        if result is not None:
            values.append(result)
    return min(values), max(values)


def number(value) -> float | None:
    """A number the model gave, possibly as text with a unit or a decimal comma ("75,3 %")."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    found = re.search(r"-?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?", str(value or ""))
    return float(found.group(0).replace(",", ".")) if found else None


def requote(concerns: list[dict], own_words: str) -> None:
    """Give concerns whose quote was not found a second quote, taken from the paper's own text.

    A sound point is often quoted loosely, or from the description of a figure. The model is shown the
    paper without those descriptions and asked for the sentence it meant; the new quote is looked up
    like any other, so a point that still cannot be tied to the paper is still dropped.
    """
    listed = [{"id": i, "point": c["point"], "was_quoted": str(c.get("quote"))[:400]} for i, c in enumerate(concerns, 1)]
    reply = chat_json("ultra", [{"role": "user", "content": REQUOTE_PROMPT.format(
        points=json.dumps(listed, indent=1, ensure_ascii=False), paper=own_words)}],
        key="quotes", max_tokens=3000, purpose="requote")["quotes"]
    for entry in reply if isinstance(reply, list) else []:
        try:
            concerns[int(entry.get("id")) - 1]["quote"] = str(entry.get("quote") or "")
        except (AttributeError, TypeError, ValueError, IndexError):
            continue


def findings(paper: str, squeezed_paper: str, own_words: str) -> dict:
    """The referee's assessment, with every point that could not be tied to the paper removed."""
    reply = chat_json("ultra", [{"role": "user", "content": FINDINGS_PROMPT.format(
        paper=paper, checklist="\n".join(f"- {item}" for item in CHECKLIST))}],
        key="concerns", thinking=True, max_tokens=14000, purpose="review")

    def kept(entries, required=("point", "quote")):
        return [e for e in entries or [] if isinstance(e, dict) and all(e.get(k) for k in required)
                and anchored(e["quote"], squeezed_paper) and not ABOUT_THE_COPY.search(str(e["point"]))]

    loose = [c for c in reply.get("concerns") or [] if isinstance(c, dict) and c.get("point")
             and not anchored(c.get("quote"), squeezed_paper) and not ABOUT_THE_COPY.search(str(c["point"]))]
    if loose:
        optional(None, requote, loose, own_words)
    anchored_concerns = kept(reply.get("concerns"))
    for c in anchored_concerns:
        c["severity"] = c.get("severity") if c.get("severity") in ("major", "minor") else "minor"
    # facts that code can check are settled first; only matters of reading go to the challenge
    open_concerns, settled = checked_by_code(anchored_concerns, own_words)
    concerns, withdrawn = optional((open_concerns, []), challenge, open_concerns, paper, squeezed_paper)
    withdrawn = settled + withdrawn
    said = {str(e.get("item", "")).strip().lower(): e for e in reply.get("checklist") or [] if isinstance(e, dict)}
    checklist = []
    for item in CHECKLIST:
        entry = said.get(item.lower(), {})
        status = entry.get("status") if entry.get("status") in ("yes", "partly", "no", "not applicable") else "not assessed"
        quote = entry.get("quote") if anchored(entry.get("quote"), squeezed_paper) else ""
        checklist.append({"item": item, "status": status, "quote": " ".join(str(quote).split())[:260],
                          "note": str(entry.get("note") or "")[:260]})
    year = number(reply.get("year"))
    # a year the model gives counts only if the paper prints it
    year = int(year) if year and 1800 < year < 2100 and str(int(year)) in own_words else None
    return {"title": str(reply.get("title") or "Untitled paper"), "year": year,
            "summary": str(reply.get("summary") or ""), "strengths": kept(reply.get("strengths")),
            "concerns": sorted(concerns, key=lambda c: c["severity"] != "major"),
            "dropped": len(reply.get("concerns") or []) - len(anchored_concerns), "withdrawn": withdrawn,
            "checklist": checklist,
            "questions": [str(q) for q in reply.get("questions") or [] if isinstance(q, str)][:8]}


def challenge(concerns: list[dict], paper: str, squeezed_paper: str) -> tuple[list[dict], list[dict]]:
    """Split concerns into those that stand and those the paper itself answers.

    A quote shows a concern is about the paper, not that it is right: "the table's
    values are missing" can quote the caption of a table that is there. So each
    concern is argued against, and withdrawn when the answer quotes a passage of
    the paper other than the one the concern already quoted.
    """
    if not concerns:
        return [], []
    listed = [{"id": i, "concern": c["point"], "quoted": c["quote"]} for i, c in enumerate(concerns, 1)]
    reply = chat_json("ultra", [{"role": "user", "content": CHALLENGE_PROMPT.format(
        concerns=json.dumps(listed, indent=1, ensure_ascii=False), paper=paper)}],
        key="checked", thinking=True, max_tokens=8000, purpose="challenge")["checked"]
    answers, doubted = {}, []
    for entry in reply if isinstance(reply, list) else []:
        if not isinstance(entry, dict) or entry.get("verdict") not in ("answered", "unsupported"):
            continue
        answer = squeeze(str(entry.get("quote") or ""))
        try:
            concern = concerns[int(entry.get("id")) - 1]
        except (TypeError, ValueError, IndexError):
            continue
        own = squeeze(concern["quote"])
        why = str(entry.get("why") or "")[:300]
        # An answer is one passage of the paper other than the one criticised: the claim a concern
        # questions, quoted back, does not answer it, and neither do fragments strung together.
        single = len([p for p in re.split(r"\.{3,}|…", str(entry.get("quote") or "")) if len(squeeze(p)) >= 12]) == 1
        if entry["verdict"] == "unsupported":
            doubted.append((concern, why))
        elif single and anchored(entry.get("quote"), squeezed_paper) and not mostly_repeats(answer, own):
            answers[id(concern)] = {"point": concern["point"], "answer": " ".join(str(entry["quote"]).split())[:300],
                                    "why": why}
    # Nothing can be quoted for something that is not there, so "unsupported" is one reading against
    # another. A different model settles it: the concern goes only if it too finds the premise false.
    if doubted:
        listed = [{"id": i, "concern": c["point"], "quoted": c["quote"], "the other reader says": why}
                  for i, (c, why) in enumerate(doubted, 1)]
        second = optional({"checked": []}, chat_json, SECOND_READER, [{"role": "user", "content": PREMISE_PROMPT.format(
            concerns=json.dumps(listed, indent=1, ensure_ascii=False), paper=paper)}],
            key="checked", max_tokens=2500, purpose="challenge")["checked"]
        for entry in second if isinstance(second, list) else []:
            try:
                concern, why = doubted[int(entry.get("id")) - 1]
            except (AttributeError, TypeError, ValueError, IndexError):
                continue
            if entry.get("premise_true") is False:
                answers[id(concern)] = {"point": concern["point"], "answer": "", "why": why}
    return [c for c in concerns if id(c) not in answers], list(answers.values())


def mostly_repeats(answer: str, quoted: str) -> bool:
    """Whether an answer is mostly the passage the concern quoted (squeezed texts): half of it or more.

    An answer may share a phrase with what it answers; one that is the criticised claim quoted back is no answer.
    """
    if not answer or not quoted:
        return False
    if answer in quoted or quoted in answer and len(quoted) >= 0.5 * len(answer):
        return True
    covered = sum(RUN for i in range(0, len(answer) - RUN + 1, RUN) if answer[i:i + RUN] in quoted)
    return covered >= 0.5 * len(answer)


def settled_by_code(statement: str, text: str) -> bool:
    """Whether a statement asserts a fact that code checks and finds false: a reference or citation said
    to be undefined in a LaTeX source where all are defined, or sections said to repeat that do not."""
    latex = "\\documentclass" in text
    if latex and MISSING_REFERENCE.search(statement) and not broken_references(text):
        return True
    return bool(DUPLICATION.search(statement)) and (not latex or not repeated(text))


def checked_by_code(concerns: list[dict], text: str) -> tuple[list[dict], list[dict]]:
    """Split off the concerns about facts code can check, which models get wrong: a reference or a
    citation said to be undefined (LaTeX only, where code checks them all), sections said to repeat."""
    latex = "\\documentclass" in text
    broken = broken_references(text) if latex else []
    kept, withdrawn = [], []
    for c in concerns:
        if latex and MISSING_REFERENCE.search(c["point"]):
            why = ("Checked in the LaTeX source by code: " +
                   ("every reference has a label and every citation a bibliography entry." if not broken
                    else "the references that are really undefined are listed as a separate concern."))
        elif DUPLICATION.search(c["point"]) and not latex:
            why = ("The text was transcribed from the PDF in overlapping strips, so passages repeat in the copy "
                   "used here; that says nothing about the paper.")
        elif DUPLICATION.search(c["point"]) and not repeated(text):
            why = "Checked in the LaTeX source by code: no section heading and no paragraph appears twice."
        else:
            kept.append(c)
            continue
        withdrawn.append({"point": c["point"], "answer": "", "why": why, "by": "code"})
    return kept, withdrawn


def broken_references(latex: str) -> list[dict]:
    """References a reader of the printed paper sees as "??" or "[?]", found by code in the LaTeX source.

    An equation or figure referred to but never labelled, and a work cited but absent from the
    bibliography. Citations are checked only when the bibliography is written in the source: one
    produced by BibTeX lives in a file that is not part of it.
    """
    if "\\documentclass" not in latex:
        return []
    labels = {k.strip() for k in re.findall(r"\\label\{([^}]+)\}", latex)}
    found = []
    for kind, keys, known in (
            ("reference", r"\\(?:eq|auto|c|C)?ref\*?\{([^}]+)\}", labels),
            ("citation", r"\\cite[pt]?\*?(?:\[[^\]]*\])*\{([^}]+)\}",
             {k.strip() for k in re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", latex)})):
        if kind == "citation" and not known:
            continue
        missing = {}
        for match in re.finditer(keys, latex):
            line = latex[latex.rfind("\n", 0, match.start()) + 1: match.start()]
            if re.search(r"\\(?:def|(?:re)?newcommand|providecommand)", line):
                continue  # inside the definition of a macro: #1 is a parameter, not a label
            for key in (k.strip() for k in match.group(1).split(",")):
                if key and "#" not in key and key not in known and key not in missing:
                    start = latex.rfind("\n\n", 0, match.start()) + 1
                    end = latex.find("\n\n", match.end())
                    sentence = re.split(r"(?<=[.!?])\s", latex[start:end if end > 0 else None])
                    missing[key] = next((s for s in sentence if match.group(0) in s), match.group(0))
        if missing:
            shown = ", ".join(sorted(missing)[:8]) + (" and others" if len(missing) > 8 else "")
            what = ("referred to but never defined, so the printed paper shows \"??\" in their place"
                    if kind == "reference" else "cited but missing from the bibliography, so the reader cannot "
                                                "tell which work is meant")
            found.append({"severity": "minor", "category": "clarity", "by": "code",
                          "point": f"{len(missing)} {kind}(s) {what}: {shown}.",
                          "quote": " ".join(next(iter(missing.values())).split())[:400],
                          "suggestion": f"Define or correct each {kind}."})
    return found


def review(paper: str, own_words: str | None = None, tables: dict | None = None) -> dict:
    """Review a paper. `own_words` is the paper without what was added to it (the figure descriptions):
    only that can be quoted. `tables` are the rows of a PDF's tables, read without a model; a LaTeX
    source has its own."""
    squeezed = squeeze(own_words or paper)
    text = own_words or paper
    reading = findings(paper, squeezed, text)
    # A question for the authors can rest on the same false fact as a withdrawn concern ("cite X is missing
    # from the bibliography" when it is not): the facts code checks settle the questions too.
    reading["questions"] = [q for q in reading["questions"] if not settled_by_code(q, text)]
    restated, unsupported = abstract_numbers(text)
    reading["concerns"] += broken_references(text) + unsupported
    # a value printed differently in two places is matched by wording, not computed: a second model confirms it
    differs = [c for c in restated if not c["consistent"]]
    restated = [c for c in restated if c["consistent"]] + optional([], confirmed, differs, paper, judge="ultra")
    rows = tables if tables and "\\documentclass" not in text else None
    found = table_checks(text, rows) + table_totals(text, rows) + percentages(text) + restated
    # The model's checks that repeat one code already made add nothing: the same value found again, or the
    # same arithmetic. "36 + 29 - 62 = 3.0" is not a repeat of "3.0 is printed in the body".
    restated_values = {c["stated"] for c in found if c["kind"] == "restated"}
    expressions = {c["expression"].replace(" ", "") for c in found}
    proposed = optional([], consistency, paper, squeezed)
    found += [c for c in optional([c for c in proposed if c["consistent"]], confirmed, proposed, paper)
              if not (c["kind"] == "restated" and c["stated"] in restated_values)
              and c["expression"].replace(" ", "") not in expressions]
    return {**reading, "consistency": found}


def far_apart(computed: float, stated: float) -> bool:
    """Whether two values differ by more than half of the larger: not a misprint of one another."""
    big = max(abs(computed), abs(stated))
    return big > 0 and abs(computed - stated) > 0.5 * big


def factor_off(computed: float, stated: float) -> bool:
    """Whether two values differ by a round factor (2, 3, 4, 8, 10, 100, 1000 or its inverse), within 2%."""
    if not computed or not stated:
        return False
    ratio = max(abs(computed), abs(stated)) / min(abs(computed), abs(stated))
    return any(abs(ratio / f - 1) < 0.02 for f in (2, 3, 4, 8, 10, 16, 100, 1000, 1e6, 1e9))


def confirmed(checks: list[dict], paper: str, judge: str = SECOND_READER) -> list[dict]:
    """The checks, less the mismatches another reading finds were set up wrongly.

    The arithmetic is code, but which numbers go into it is a reading, and a wrong reading produces a
    mismatch that accuses the paper of an error it does not have. So a mismatch stands only if a model
    that did not set the check up agrees both sides are the same quantity: Super for the checks Ultra
    proposed, Ultra with reasoning for the candidates code found by wording.
    """
    # A model's expression off by exactly 2, 4, 10 or 1000 has almost surely dropped a factor or a unit:
    # that is the check's error, not the paper's.
    checks = [c for c in checks if c["consistent"] or c.get("by") == "code" or not factor_off(c["computed"], c["stated"])]
    # A slip in a paper prints a value near the right one (41.0 for 41.8); a model's check that lands far from
    # the printed value (3.8 against 0.3) has almost surely put the wrong numbers together.
    checks = [c for c in checks if c["consistent"] or c.get("by") == "code" or not far_apart(c["computed"], c["stated"])]
    disputed = [c for c in checks if not c["consistent"]]
    if not disputed:
        return checks
    listed = [{"id": i, "what": c["what"], "expression": c["expression"], "stated": c["stated"],
               "where the paper states it": c["quotes"]} for i, c in enumerate(disputed, 1)]
    message = [{"role": "user", "content": CONFIRM_PROMPT.format(
        checks=json.dumps(listed, indent=1, ensure_ascii=False), paper=paper)}]
    if len(paper) > SUPER_LIMIT and judge == "super":
        judge = "ultra"  # Super's endpoint times out on papers this long: do not wait for it to fail
    # if the judge's endpoint fails (long papers time out), the other model judges instead
    for role in (judge, "ultra" if judge != "ultra" else "super"):
        reply = optional(None, chat_json, role, message, key="verdicts", thinking=role == "ultra",
                         max_tokens=6000 if role == "ultra" else 2500, purpose="confirm")
        if reply is not None:
            reply = reply["verdicts"]
            break
    else:
        return [c for c in checks if c["consistent"]]  # nobody could confirm: no accusation
    sound = set()
    for entry in reply if isinstance(reply, list) else []:
        try:
            if entry.get("same_quantity") is True and entry.get("computed_as_defined") is True:
                sound.add(id(disputed[int(entry.get("id")) - 1]))
        except (AttributeError, TypeError, ValueError, IndexError):
            continue
    return [c for c in checks if c["consistent"] or id(c) in sound]


def repeated(latex: str) -> bool:
    """Whether a LaTeX source repeats itself: a section title used twice, or paragraphs of prose that occur twice."""
    titles = [t.strip().lower() for t in re.findall(r"\\(?:sub)*section\*?\{([^}]*)\}", latex)]
    if len(titles) != len(set(titles)):
        return True
    body = latex[:latex.find("\\begin{thebibliography}")] if "\\begin{thebibliography}" in latex else latex
    prose = [p for p in (" ".join(p.split()) for p in re.split(r"\n\s*\n", body))
             if len(p) > 200 and sum(ch.isalpha() for ch in p) > 0.6 * len(p)]
    return len(prose) != len(set(prose))
