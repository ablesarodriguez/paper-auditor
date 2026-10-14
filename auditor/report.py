"""Stage 6 - Report: the audit as Markdown.

Verdicts and numbers are laid out by code; Nemotron Ultra only writes the
narrative that explains them, so it cannot alter an outcome.
"""

import json
import re
from pathlib import Path

from .coverage import REASONS
from .llm import chat
from .verify import METHOD_ONLY, SUBSTITUTE_FAIL, SUBSTITUTE_OK
from .verify import BLOCKED, MALFORMED, NEEDS_DATA, NOT_IMPLEMENTED, NOT_VERIFIABLE, NOT_VERIFIED, VERIFIED, VERIFIED_IF, matches

LABELS = {
    VERIFIED: "Reproduced",
    VERIFIED_IF: "Reproduced under an assumption",
    NOT_VERIFIED: "Not reproduced",
    BLOCKED: "Inconclusive, depends on a missing detail",
    NOT_VERIFIABLE: "Not verifiable (hardware-dependent)",
    NOT_IMPLEMENTED: "No result",
    MALFORMED: "Not audited, claim mis-extracted",
    NEEDS_DATA: "Not auditable without the paper's data",
    SUBSTITUTE_OK: "Value not checked (data missing); behaviour holds on substitute data",
    SUBSTITUTE_FAIL: "Value not checked (data missing); behaviour does not hold on substitute data",
    METHOD_ONLY: "Value not checked (data missing); method implemented from the paper",
}

# Every claim gets a verdict. How far to trust it is said next to it, by fixed rules (verify.assess).
CONFIDENCE = {"high": "High", "caveats": "See warnings", None: "-"}

CAVEATS = {
    "pdf-scan": "this PDF is a scan and its text was transcribed by a vision model. An occasional digit "
                "or sign is misread, so a mismatch on a single table value may be a transcription error "
                "rather than a reproducibility problem.",
    "pdf-text+vision": "equations were rebuilt from the PDF by a vision model, with the text layer as a "
                       "reference. A mismatch may come from a misread formula; audit the arXiv id "
                       "instead when the paper is on arXiv.",
}

NARRATIVE_PROMPT ="""You are writing the narrative of a reproducibility audit of
the paper "{title}". An agent re-implemented each claim, ran it, compared the
result with the paper within a tolerance, and re-ran it varying each assumption
made for a detail the paper omits. The verdicts below are final: explain them,
do not change them. The facts are in the data: "matches_paper" says whether the
main run agrees with the paper, and each sensitivity entry has its own
"matches". Never write that a result matches, or fails to match, against what
those fields say. "verified_under_assumption" means the paper's numbers come
out for one value of a missing detail and not for others, which identifies the
value the authors must have used. "blocked_by_missing_detail" means the result
depends on a missing detail and no tried value settles it.

Write Markdown with exactly these sections:
## Summary
3-5 sentences: what holds up, what does not, and the single most important gap.
Whenever you mention a claim, give its id and what it is, in the words of its
"summary" field: never describe a claim from memory of another. Never present
a verdict as more certain than its "confidence", and for "not_verified" say
that the mismatch may be the agent's implementation and not the paper.
## What the paper should specify
A bullet list of the missing details, ordered by how much they changed the results.

Write plain text: no LaTeX, no dollar signs; write symbols as characters
(ω, ℓ∞, 10⁻⁶ or 1e-6).

AUDIT DATA:
{audit}
"""


def fmt(value) -> str:
    if isinstance(value, bool) or value is None:
        return {True: "yes", False: "no", None: "-"}[value]
    if isinstance(value, list):
        return ", ".join(fmt(v) for v in value)
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


SYMBOLS = {"cdot": "·", "times": "×", "pm": "±", "leq": "≤", "geq": "≥", "le": "≤", "ge": "≥", "approx": "≈",
           "infty": "∞", "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
           "eta": "η", "theta": "θ", "lambda": "λ", "mu": "μ", "nu": "ν", "pi": "π", "rho": "ρ", "sigma": "σ",
           "tau": "τ", "phi": "φ", "omega": "ω", "Delta": "Δ", "Omega": "Ω", "ell": "ℓ", "sqrt": "√", "%": "%"}


LAYOUT = {"left", "right", "big", "Big", "bigg", "Bigg", "quad", "qquad", "noindent", "displaystyle", "textstyle",
          "limits", "nolimits", "mathcal", "mathbb", "hspace", "vspace", "small", "large", "Large", "footnotesize",
          "centering", "hline", "newline", "smallskip", "medskip", "bigskip", "item", "par", "it", "bf", "rm", "em",
          # structure, also when a quoted excerpt cuts it in the middle
          "multicolumn", "multirow", "section", "subsection", "subsubsection", "paragraph", "label", "cite", "citep",
          "citet", "ref", "eqref", "begin", "end", "caption", "footnote", "url", "href", "includegraphics",
          "toprule", "midrule", "bottomrule", "cline", "cmidrule", "textwidth", "linewidth"}


def readable(text) -> str:
    """A passage quoted from a LaTeX source, as a reader of the printed paper would see it.

    Only for display: quotes are matched against the source as they are, and this does not change them.
    """
    text = re.sub(r"\[T\d+\.R\d+\]\s*\|?\s*", "", str(text))                      # the auditor's own row tags
    # LaTeX fractions as a/b
    text = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}|\\[dt]?frac\s*(\w)(\w)",
                  lambda m: "/".join(x if len(x) == 1 or x.isalnum() else f"({x})" for x in
                                     (m.group(1, 2) if m.group(1) is not None else m.group(3, 4))), text)
    # t^{-1/2} as t^(-1/2), β_{1} as β_1: written so by the paper or by a model describing it
    text = re.sub(r"([\^_])\{([^{}]*)\}", lambda m: m.group(1) + (m.group(2) if len(m.group(2)) == 1 else f"({m.group(2)})"), text)
    if not re.search(r"[\\$]", text):
        return " ".join(text.split())  # plain text (a transcribed PDF): its braces are the paper's own
    text = re.sub(r"\\multicolumn\{[^{}]*\}\{[^{}]*\}\{((?:[^{}]|\{[^{}]*\})*)\}", r"\1", text)
    text = re.sub(r"\\(?:sub)*section\*?\{[^{}]*\}?|\\(?:label|cite[pt]?)\{[^{}]*\}?", "", text)
    text = re.sub(r"\\multicolumn(?:\{[^{}]*\}?){0,2}", "", text)  # what is left of one an excerpt cut short
    text = re.sub(r"(?:Table|Figure|Eq\.?|Section)?~?\\(?:eq|auto|c|C)?ref\{[^{}]*\}", lambda m: m.group(0).split("\\")[0].rstrip("~") + " (ref.)" if m.group(0).split("\\")[0] else "(ref.)", text)
    text = re.sub(r"\\(?:textbf|textit|emph|mathrm|mathbf|text|boldmath|textsubscript|textsuperscript|num|mathit|operatorname)\b\s*", "", text)
    # a symbol becomes the symbol, layout disappears, and an author's own macro (\dmodel) keeps its name
    text = re.sub(r"\\([A-Za-z]+|%)", lambda m: SYMBOLS.get(m.group(1), "" if m.group(1) in LAYOUT else m.group(1)), text)
    text = text.replace("$", "").replace("~", " ").replace("{", "").replace("}", "")
    return " ".join(text.split())


def shown_result(c: dict):
    """The result the verdict rests on: the run that matches the paper when the default one does not."""
    if c["verdict"] == VERIFIED_IF and not c.get("matches_paper"):
        return next((v["obtained"] for v in c["sensitivity"] if v["matches"]), c.get("obtained"))
    return c.get("obtained")


def verdict_cell(c: dict) -> str:
    """The verdict, with the assumption values that reproduce the paper when it hinges on one."""
    label = LABELS[c["verdict"]]
    if c["verdict"] == BLOCKED:
        names = {a["name"] for a in c["assumptions"]}
        return f"{label}: " + "; ".join(f"`{d}`" if d in names else d for d in c["decisive_assumptions"])
    if c["verdict"] != VERIFIED_IF:
        return label
    defaults = {a["name"]: a["default"] for a in c["assumptions"]}
    baseline_matches = matches(c, c["obtained"])
    conditions = []
    for name in c["decisive_assumptions"]:
        good = ([defaults[name]] if baseline_matches else []) + [
            v["value"] for v in c["sensitivity"] if v["assumption"] == name and v["matches"]]
        conditions.append(f"`{name}` = {' or '.join(fmt(v) for v in good)}")
    return f"{label}: {', '.join(conditions)}"


CITED = {True: "Yes", False: "**Not found in the paper**", None: "Cannot tell from the title"}


def review_section(reading: dict | None, related: dict | None = None, figures: dict | None = None) -> list[str]:
    """The referee's reading: summary, computed cross-checks, concerns with their quotes, checklist, questions."""
    if not reading:
        return []
    lines = ["## Summary of the paper", "", reading["summary"], ""]

    checks = reading["consistency"]
    if checks:
        wrong = [c for c in checks if not c["consistent"]]
        tables = sum(c["kind"] == "table" for c in checks)
        head = ["| | What is checked | Arithmetic | Result | Paper | Where |", "| --- | --- | --- | --- | --- | --- |"]

        def rows(selected: list[dict]) -> list[str]:
            # a value found printed elsewhere is shown as printed (41.0, not 41)
            return [f"| {'✓' if c['consistent'] else '**✗**'} | {cell(readable(c['what']))} | `{cell(c['expression'])}` "
                    f"| {c['expression'] if c['kind'] == 'restated' else fmt(float(c['computed']))} | {fmt(c['stated'])} "
                    f"| \"{cell(readable(c['quotes'][-1])[:180])}\" |" for c in selected]

        echoed = sum(c["kind"] == "restated" and c.get("by") == "code" for c in checks)
        parts = [f"{tables} averages or totals in tables, recomputed from their cells" if tables else "",
                 f"{echoed} numbers of the abstract, compared with the body" if echoed else "",
                 f"{len(checks) - tables - echoed} relations between numbers pointed out by the model"
                 if len(checks) - tables - echoed else ""]
        lines += ["## Do the paper's numbers agree with each other?", "",
                  f"{len(checks)} results printed in the paper were checked against other numbers it prints: "
                  + "; ".join(p for p in parts if p) + f". All arithmetic is done by code. **{len(wrong)} {'does' if len(wrong) == 1 else 'do'} not agree.**", ""]
        if wrong:
            lines += head + rows(wrong) + [""]
        right = [c for c in checks if c["consistent"]]
        if right:
            lines += ["<details>", f"<summary>The {len(right)} that agree</summary>", ""] + head + rows(right) \
                     + ["", "</details>", ""]
        lines += ["Each printed input is taken to stand for anything that rounds to it, so rounding is not reported as "
                  "a mismatch. A mismatch in a check the model set up is reported only when a second model agrees the "
                  "check compares the right quantities.", ""]
    else:
        lines += ["## Do the paper's numbers agree with each other?", "",
                  "No reported results were found that can be checked against other numbers the paper prints "
                  "(an average or total in a table, a number of the abstract in the body, a percentage and its "
                  "counts, a ratio and its terms).", ""]

    for severity, title in (("major", "Major concerns"), ("minor", "Minor concerns")):
        concerns = [c for c in reading["concerns"] if c["severity"] == severity]
        if concerns:
            lines += [f"## {title}", ""]
            for i, c in enumerate(concerns, 1):
                lines += [f"**{i}. {readable(c['point'])}** ({c.get('category', 'other')})", "",
                          f"> {readable(c['quote'])}", ""]
                if c.get("suggestion"):
                    lines += [f"Suggested: {c['suggestion']}", ""]
    if reading.get("dropped"):
        lines += [f"{reading['dropped']} further concern(s) raised by the model were discarded: the passage they "
                  "quoted is not in the paper, or they were about the copy of the paper and not the paper.", ""]
    if reading.get("withdrawn"):
        lines += ["## Concerns raised and withdrawn", "",
                  "Each concern was argued against before being kept. These were withdrawn, either because a "
                  "passage of the paper answers them or because a second reading found them not to hold:", ""]
        lines += [f"- ~~{readable(w['point'])}~~ " + (f"The paper says: \"{readable(w['answer'])}\"" if w["answer"]
                                            else w["why"] if w.get("by") == "code"
                                            else f"Two models reading the paper again both found: {readable(w['why'])}")
                  for w in reading["withdrawn"]]
        lines.append("")

    if reading["strengths"]:
        lines += ["## Strengths", ""]
        lines += [f"- {s['point']} (\"{readable(s['quote'])[:160]}\")" for s in reading["strengths"]]
        lines.append("")

    lines += ["## Can it be reproduced from what the paper gives?", "",
              "| | Requirement | Evidence in the paper |", "| --- | --- | --- |"]
    for item in reading["checklist"]:
        evidence = item["note"] + (f" (\"{readable(item['quote'])[:140]}\")" if item["quote"] else "")
        lines.append(f"| {item['status'].capitalize()} | {item['item']} | {cell(evidence)} |")
    lines.append("")

    if related is not None:
        lines += ["## How it stands against related work", ""]
        if related["related"]:
            own = related.get("paper_year")

            def standing(r: dict) -> str:
                # a work that came out after the paper could not have been cited: not an omission
                if own and r.get("year") and r["year"] > own:
                    return "Later than the paper"
                return CITED[r["cited"]]

            lines += [related["assessment"], "",
                      "| Related work found | Year | How it relates | Cited by the paper |", "| --- | --- | --- | --- |"]
            lines += [f"| [{cell(r['title'][:110])}]({r['url']}) | {r.get('year') or ''} | {cell(r['relation'])}: "
                      f"{cell(r['note'])} | {standing(r)} |" for r in related["related"]]
            lines += ["", "Found by web search for: " + "; ".join(f"*{q}*" for q in related["queries"]) + ". "
                      "The works were judged from their titles and search snippets, not read. A year is given only "
                      "when the work's address carries it; a work with no year may also be later than the paper"
                      + (f" ({own})" if own else "") + ". \"Not found\" means the work's full title does not "
                      "appear in the paper's text.", ""]
        else:
            lines += ["The web search returned no work close enough to compare with. That is not evidence of novelty.", ""]

    if figures:
        lines += ["## The figures, as read from the images", "",
                  "Each figure was cut out of the PDF and described by a vision model, so that the review is not "
                  "limited to captions. These are descriptions, not measurements: values read off a plot are approximate.", ""]
        lines += ["<details>", f"<summary>{len(figures)} figure(s) described</summary>", ""]
        lines += [f"- **Figure {n}.** {text}" for n, text in figures.items()]
        lines += ["", "</details>", ""]

    if reading["questions"]:
        lines += ["## Questions for the authors", ""] + [f"{i}. {readable(q)}" for i, q in enumerate(reading["questions"], 1)] + [""]
    lines += ["> The summary, the concerns, the strengths and the questions are a model's judgement. A concern is kept "
              "only when the passage it quotes is in the paper and no other passage of the paper answers it. The "
              "number checks are computed.", ""]
    return lines


def coverage_section(coverage: dict | None, claims: list[dict]) -> list[str]:
    """Which parts of the paper the audit speaks about, and why it is silent on the rest."""
    if not coverage:
        return []
    verdicts = {c["id"]: LABELS[c["verdict"]].lower() for c in claims}

    def audited(entry: dict) -> str:
        ids = [i for i in entry["claims"] if i in verdicts]
        if len(ids) > 1 and len({verdicts[i] for i in ids}) == 1:
            return f"{', '.join(ids)} (all: {verdicts[ids[0]]})"
        return ", ".join(f"{i} ({verdicts[i]})" for i in ids) or "-"

    def why(entry: dict) -> str:
        if entry["claims"]:
            return cell(entry["note"])
        return cell(f"{REASONS[entry['reason']]}. {entry['note']}".rstrip(". ") + ".")

    parts = coverage["sections"] + coverage["items"]
    covered = sum(bool(p["claims"]) for p in parts)
    tables = [i for i in coverage["items"] if i["kind"] == "table"]
    figures = [i for i in coverage["items"] if i["kind"] == "figure"]
    lines = ["## What this audit covers", "",
             f"An audit only speaks about results that can be recomputed. Of the {len(parts)} parts of this paper "
             f"listed below, {covered} gave rise to claims: {sum(bool(s['claims']) for s in coverage['sections'])} of "
             f"{len(coverage['sections'])} sections, {sum(bool(t['claims']) for t in tables)} of {len(tables)} tables and "
             f"{sum(bool(f['claims']) for f in figures)} of {len(figures)} figures. The rest is listed with the reason "
             "it was left out. Figures are described from their images for the review, but nothing is recomputed "
             "from an image: values read off a plot are approximate.", "",
             "| Part of the paper | Claims taken from it | What it contains, or why nothing was audited |",
             "| --- | --- | --- |"]
    for s in coverage["sections"]:
        title = re.sub(r"^\d+[.)]\s*", "", readable(s["title"]))  # "1) \quad Introduction" as "Introduction"
        lines.append(f"| Section: {cell(title)} | {audited(s)} | {why(s)} |")
    for i in coverage["items"]:
        name = f"{'Table' if i['kind'] == 'table' else 'Figure'} {i['id'][1:]}"
        lines.append(f"| {name}: {cell(readable(i['caption'])[:110])} | {audited(i)} | {cell(readable(why(i)))} |")
    return lines + [""]


def basis(c: dict) -> str:
    """In plain words, the rule that produced a claim's verdict. Written by code from the audit data."""
    verdict = c["verdict"]
    if verdict == NOT_VERIFIABLE:
        return "Not attempted: timings, speed-ups and throughput depend on the machine they were measured on."
    if verdict == NEEDS_DATA:
        return f"Not attempted: the result is computed from data the paper does not contain ({c.get('needs_data')})."
    if verdict in (SUBSTITUTE_OK, SUBSTITUTE_FAIL, METHOD_ONLY):
        tested = (f"What was tested instead: {c['without_data']} " if c.get("without_data") else
                  "Nothing of the claim can be tested without that data, so the test was only whether the method runs. ")
        return (f"The paper's value ({fmt(c['expected_value']) if c.get('expected_value') is not None else c.get('expected')}) "
                f"was not compared with anything: it was computed from {c.get('needs_data')}, which is not available. "
                f"The script implements the method from the paper and runs it on substitute data that it generates. "
                f"{tested}The script returned {'true' if c.get('obtained') else 'false'}. "
                f"What it measured: {c.get('detail') or 'not reported'}")
    if verdict == MALFORMED:
        return "Not attempted: the values this claim expects come from different places in the paper."
    if verdict == NOT_IMPLEMENTED:
        return (f"No verdict on the paper: {len(c['failed_attempts'])} scripts were written and none ran to a "
                f"result that passed the integrity checks. Last failure: {c.get('error', 'unknown')}")

    variants = c.get("sensitivity", [])
    ran = [v for v in variants if v["matches"] is not None]
    if c["kind"] == "numeric":
        tol = c["tolerance"]
        allowed = f"{tol['value']:g} {'relative' if tol['type'] == 'relative' else 'absolute'}"
        text = (f"The script returned {fmt(c.get('obtained'))}; the paper reports {fmt(c['expected_value'])}. "
                f"They were compared number by number, allowing a difference of {allowed}"
                + ("" if c.get("exact") else ", and never less than the last digit the paper prints")
                + f". Result: they {'agree' if c.get('matches_paper') else 'do not agree'}.")
        if c.get("agreeing_digits") is not None:
            text += f" The agreement covers {c['agreeing_digits']} significant digits in total; six or more counts as strong."
    else:
        text = (f"The script tested the behaviour with a criterion of its own and returned "
                f"{'true' if c.get('obtained') else 'false'}. What it measured: {c.get('detail') or 'not reported'}")
    if ran:
        matching = sum(bool(v["matches"]) for v in ran)
        text += (f" It was then re-run {len(ran)} times, each with one assumption changed "
                 f"({', '.join(sorted({v['assumption'] for v in ran}))}): {matching} of those runs match the paper.")
    elif c.get("missing_details") and verdict == BLOCKED:
        text += " The paper leaves out details that could not be turned into anything to vary, so the mismatch cannot be pinned on the paper."
    if c.get("built_on"):
        text += f" The script was written starting from the one that reproduced {c['built_on']}."
    return text


def first_sentence(text: str, limit: int = 220) -> str:
    sentence = re.split(r"(?<=[.;])\s", " ".join(str(text).split()), maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[:limit].rsplit(" ", 1)[0] + " …"


def key_findings(audit: dict) -> list[str]:
    """The few things a reader must see first, each taken from a section below, most solid first:
    what code computed or checked, then the referee's major concerns, then the re-computation."""
    reading, claims, found = audit.get("review") or {}, audit.get("claims") or [], []
    checks = reading.get("consistency") or []
    for c in [c for c in checks if not c["consistent"]][:3]:
        if c["kind"] == "restated":  # one result printed twice with two values: its description says where
            found.append(f"**Numbers that disagree:** {readable(c['what'])}.")
        else:
            found.append(f"**Numbers that disagree:** {readable(c['what'])}: the paper prints {fmt(c['stated'])}, "
                         f"recomputing `{c['expression']}` from its other numbers gives {fmt(float(c['computed']))}.")
    for c in [c for c in reading.get("concerns", []) if c.get("by") == "code"][:2]:
        found.append(f"**Found by code:** {readable(first_sentence(c['point']))}")
    for c in [c for c in reading.get("concerns", []) if c["severity"] == "major" and c.get("by") != "code"][:3]:
        found.append(f"**Major concern:** {readable(first_sentence(c['point']))}")
    if checks and not any(not c["consistent"] for c in checks):
        found.append(f"**Numbers consistent:** all {len(checks)} cross-checks of the paper's numbers agree.")
    if claims:
        solid = sum(c["confidence"] == "high" for c in claims)
        reproduced = sum(c["verdict"] in (VERIFIED, VERIFIED_IF) for c in claims)
        found.append(f"**Re-computation:** {reproduced} of {len(claims)} results reproduced by running code written "
                     f"from the paper, {solid} of them with high confidence.")
        blocked = [c for c in claims if c["verdict"] == VERIFIED_IF]
        if blocked:
            found.append(f"**Missing detail:** {', '.join(c['id'] for c in blocked)} come out only under an assumption "
                         "the paper does not state (see Warnings).")
    if not found:
        return []
    return ["## Key findings", "", *[f"- {line}" for line in found], "",
            "*Each point is detailed below with its evidence.*", ""]


def write_report(audit: dict, run: Path) -> str:
    claims = audit["claims"]
    lines = [f"# Review of: {audit['title']}", "",
             "This report does what a referee does. First it reads the paper: what it claims, whether its numbers "
             "agree with each other, what is unsound, unclear or missing, and whether it can be reproduced from what "
             "it gives. Then it tries to recompute the results that can be recomputed.", ""]
    lines += key_findings(audit)
    lines += review_section(audit.get("review"), audit.get("related"), audit.get("figures"))
    if not claims:  # the paper was only read, not recomputed
        return "\n".join(lines) + "\n"
    lines += ["# Reproduction of the paper's results", ""]

    solid = sum(c["confidence"] == "high" for c in claims)
    counts = {label: sum(c["verdict"] == key for c in claims) for key, label in LABELS.items()}
    scripted = [c for c in claims if c["verdict"] not in (NOT_VERIFIABLE, MALFORMED, NEEDS_DATA)]
    ran = sum(c["verdict"] != NOT_IMPLEMENTED for c in scripted)
    lines += [f"{len(claims)} claims audited. **{solid}** reproduced with high confidence. In all: "
              + ", ".join(f"{n} {label.lower()}" for label, n in counts.items() if n) + ".", "",
              f"The method was rebuilt from the paper's description for {len(scripted)} of them, and "
              f"{ran} of those scripts ran to a result"
              + (f". Data supplied with the paper: {audit['data'].count(chr(10)) + 1} files." if audit.get("data") else
                 ". No data was supplied with the paper.") , "",
              "High confidence means the numbers printed in the paper were recomputed to at least "
              "six agreeing significant digits in total, under no assumption. Every other verdict "
              "carries the warnings listed below the table.", ""]

    lines += coverage_section(audit.get("coverage"), claims)

    lines += ["## Claims", "",
              "| Claim | Statement | Paper | Obtained | Verdict | Confidence |", "| --- | --- | --- | --- | --- | --- |"]
    for c in claims:
        paper_value = fmt(c["expected_value"]) if c["kind"] == "numeric" else c["expected"]
        lines.append(f"| {c['id']} | {cell(readable(c.get('summary') or c['statement']))} | {cell(paper_value)} "
                     f"| {fmt(shown_result(c))} | {cell(verdict_cell(c))} | {CONFIDENCE[c['confidence']]} |")
    lines.append("")

    warned = [c for c in claims if c["warnings"]]
    if warned:
        lines += ["## Warnings", ""]
        for c in warned:
            lines.append(f"**{c['id']}** ({LABELS[c['verdict']].lower()})")
            lines += [f"- {w}" for w in c["warnings"]]
            lines.append("")

    narrative = chat("ultra", [{"role": "user", "content": NARRATIVE_PROMPT.format(
        title=audit["title"], audit=json.dumps(claims, indent=1))}], purpose="narrative")
    lines += ["> The two sections that follow were written by a model from the data in this report. "
              "The table and the warnings above are computed by fixed rules and take precedence; the "
              "reasoning behind each verdict is laid out by code in \"How each verdict was reached\".", "",
              "\n".join(readable(line) if not line.startswith("#") else line for line in narrative.splitlines()), ""]

    sensitive = [c for c in claims if c.get("sensitivity")]
    if sensitive:
        lines += ["## Sensitivity to assumptions", "",
                  "Each row re-runs the claim with one assumption changed from its default. "
                  "\"Identical output\" means the result is robust to it, or that the generated "
                  "script does not really use the parameter: check the script.", "",
                  "| Claim | Assumption | Default | Tried | Obtained | Change | Matches paper |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for c in sensitive:
            defaults = {a["name"]: a["default"] for a in c["assumptions"]}
            for v in c["sensitivity"]:
                change = ("identical output" if v["identical_output"] else
                          f"{v['relative_change']:+.2%}" if v["relative_change"] is not None else "-")
                lines.append(f"| {c['id']} | `{v['assumption']}` | {fmt(defaults[v['assumption']])} | {fmt(v['value'])} "
                             f"| {fmt(v['obtained']) if not v['error'] else 'error'} | {change} | {fmt(v['matches'])} |")
        lines.append("")

    amended = [c for c in claims if c.get("located_in_paper")]
    if amended:
        lines += ["## Corrections to the extracted claims", "",
                  "Claims are extracted by a model and can misreport the paper. These were corrected "
                  "during the audit.", ""]
        for c in amended:
            if c.get("located_in_paper"):
                lines.append(f"- **{c['id']}** expected values first extracted as {fmt(c['expected_value_as_extracted'])}, "
                             f"which the computation did not reproduce. The computed values are printed in the "
                             f"paper here, and were taken as what it reports: `{c['located_in_paper']}`")
        lines.append("")

    built = [c for c in claims if c.get("built_on")]
    if built:
        lines += ["## Claims reproduced from a sibling's script", "",
                  "These did not reproduce when implemented on their own. They did when the script was "
                  "written starting from one that had already reproduced another result of the same "
                  "experiment to many digits, which fixes the setup.", ""]
        lines += [f"- **{c['id']}** built on the script of **{c['built_on']}**." for c in built]
        lines.append("")

    reviewed = [c for c in claims if c.get("second_opinion")]
    if reviewed:
        lines += ["## Implementation review", "",
                  "When a result did not match the paper, a second model checked the script against "
                  "the paper before the mismatch was reported.", ""]
        for c in reviewed:
            opinion = c["second_opinion"]
            lines.append(f"- **{c['id']}** first result {fmt(opinion['first_obtained'])}. " + {
                "faithful": "The script was judged faithful to the paper, so the mismatch stands",
                "fixed": f"The script was corrected and re-run, giving {fmt(c.get('obtained'))}",
                "fix_did_not_help": "The script was changed and re-run, giving "
                                    f"{fmt(opinion.get('corrected_obtained'))}, which does not match either, "
                                    "so the first result is kept",
                "unavailable": "The script could not be checked, so the mismatch is unconfirmed",
                "fix_failed": "Errors were found but the corrected script did not run, so the first result is kept",
            }[opinion["verdict"]] + f": {opinion['reason']}")
        lines.append("")

    assumed = [(c, a) for c in claims for a in c.get("assumptions", [])]
    if assumed:
        lines += ["## Assumptions made", ""]
        lines += [f"- **{c['id']}** `{a['name']}` = {fmt(a['default'])}: {a['missing_detail']} ({a['rationale']})"
                  + (f" Source: {a['source']}" if a.get("source") else "") for c, a in assumed]
        lines.append("")

    if audit.get("sources"):
        lines += ["## Cited works read to recover missing details", ""]
        lines += [f"- [{s['title']}]({s['url']})" for s in audit["sources"]]
        lines.append("")

    if audit["searches"]:
        lines += ["## Web sources consulted", ""]
        for s in audit["searches"]:
            lines.append(f"- *{s['query']}*")
            lines += [f"  - [{r['title']}]({r['url']})" for r in s["results"]]
        lines.append("")

    lines += ["## How each verdict was reached", "",
              "For every claim: what was asked, what the generated script did, the rule that produced "
              "the verdict, and the script itself.", ""]
    for c in claims:
        lines += [f"### {c['id']}: {LABELS[c['verdict']]}", "",
                  f"**Claim.** {readable(c.get('summary') or c['statement'])}", ""]
        if c.get("approach"):
            lines += [f"**What the script was asked to do.** {c['approach']}", ""]
        lines += [f"**Decision.** {basis(c)}", ""]
        script = run / c["id"] / c.get("script", "script.py")
        if script.exists():
            source = script.read_text(encoding="utf-8").rstrip()
            lines += [f"<details><summary>Generated script ({len(source.splitlines())} lines, {script.name})</summary>", "",
                      "```python", source, "```", "", "</details>", ""]

    if audit["ingest_method"] in CAVEATS:
        lines += [f"> **Caveat:** {CAVEATS[audit['ingest_method']]}", ""]
    lines += ["---", f"Text obtained by: {audit['ingest_method']}. "
              "Verdicts are computed by deterministic comparison. Every script was reviewed by a model "
              "for copied or fabricated results before its output was accepted; the scripts are in the run folder."]
    return "\n".join(lines) + "\n"
