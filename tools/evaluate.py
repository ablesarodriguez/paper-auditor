"""Measure the code-made checks: plant errors in copies of real papers and count how many are caught.

    python tools/evaluate.py [--out evaluation.md]

For every paper audited in runs/ (or published in examples/ with its text in runs/),
copies of its text get one realistic error each, of the kinds a referee looks for:

- an average or total in a table that does not match its cells;
- a result quoted in the abstract that the body does not print;
- a result printed in the body with another value than in the abstract;
- a percentage that does not match the counts beside it;
- a reference to an equation, figure or table that is not defined;
- a citation with no entry in the bibliography.

Each copy goes through the same code the review uses, and an error counts as
caught when the check reports it. The unmodified papers go through it too: what
is flagged there is listed, to be judged by hand (a flag on an unmodified paper
can be a real problem of the paper).

Only the checks made by code are measured: they need no model, so this costs
nothing and gives the same numbers every time. The parts of the review written
by models are not measured here.
"""

import argparse
import copy
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auditor.ingest import pdf_tables, table_rows  # noqa: E402
from auditor.review import (abstract_numbers, abstract_of, broken_references, cell_number,  # noqa: E402
                            mostly_in, percentages, squeeze, table_checks, table_totals)

PER_KIND = 5  # most errors planted per kind and paper
KINDS = {
    "table": "Average or total in a table that does not match its cells",
    "abstract_missing": "Result of the abstract that the body does not print",
    "abstract_differs": "Result printed with another value in the body than in the abstract",
    "percentage": "Percentage that does not match the counts beside it",
    "reference": "Reference to an undefined equation, figure or table",
    "citation": "Citation with no entry in the bibliography",
}
PDFS = {"final": "papers/final.pdf", "1602.03837": "papers/arxiv_1602.03837.pdf",
        "1412.6980": "papers/arxiv_1412.6980.pdf", "lorenz1963": "papers/lorenz1963.pdf"}


def shifted(token: str, factor: float = 1.07) -> str:
    """Another value printed the same way: same decimals, clearly different."""
    decimals = len(token.split(".")[1]) if "." in token else 0
    value = float(token.replace(",", "")) * factor + 10 ** -decimals * 3
    return f"{value:.{decimals}f}"


def flagged(text: str, rows: dict | None) -> list[str]:
    """Everything the code-made checks report on a text: mismatches and concerns, as short lines."""
    out = []
    for c in table_checks(text, rows) + table_totals(text, rows) + percentages(text):
        if not c["consistent"]:
            out.append(f"{c['kind']}: {c['expression']} = {c['computed']:g} vs {c['stated']:g}")
    checks, concerns = abstract_numbers(text)
    out += [f"abstract: {c['what']}" for c in checks if not c["consistent"]]
    out += [f"concern: {c['point']}" for c in concerns + broken_references(text)]
    return out


def plant_table(text, rows, rng):
    """Change an aggregate cell (an "Avg." column or a "Total" row) by a few units of its last digit."""
    if not rows:
        return
    found =[c for c in table_checks(text, rows) + table_totals(text, rows) if c["consistent"]]
    for check in rng.sample(found, min(PER_KIND, len(found))):
        tag = next(t for t, r in rows.items() if " | ".join(r["cells"])[:300] == check["quotes"][0])
        cells = rows[tag]["cells"]
        column = next(j for j, c in enumerate(cells) if (cell_number(c) or (None,))[0] == check["stated"])
        printed = cell_number(cells[column])
        planted = copy.deepcopy(rows)
        planted[tag]["cells"][column] = f"{printed[0] + 3 * 10 ** -printed[1] + 0.5:.{printed[1]}f}"
        yield f"{tag} col {column}: {cells[column]} -> {planted[tag]['cells'][column]}", text, planted, \
            lambda out, new=planted[tag]["cells"][column]: any(f"vs {float(new):g}" in line for line in out)


def plant_abstract_missing(text, rows, rng):
    """Change a result of the abstract that the body prints, so the body no longer supports it."""
    span = abstract_of(text)
    if not span:
        return
    checks, _ = abstract_numbers(text)
    echoed = [c for c in checks if c["consistent"]]
    for check in rng.sample(echoed, min(PER_KIND, len(echoed))):
        token = check["expression"]
        at = text.find(token, span[0], span[1])
        if at < 0:
            continue
        new = shifted(token)
        yield f"abstract {token} -> {new}", text[:at] + new + text[at + len(token):], rows, \
            lambda out, new=new: any("concern: The abstract quotes" in line and new in line for line in out)


def plant_abstract_differs(text, rows, rng):
    """Print a result of the abstract with another value where the body states it."""
    span = abstract_of(text)
    if not span:
        return
    abstract = text[span[0]:span[1]]
    squeezed_abstract = squeeze(abstract)

    def in_body(at: int) -> bool:
        # A transcribed PDF repeats the abstract where its page strips overlap: that copy is not the body,
        # and an error planted there is not an error in the paper's results.
        line = text[text.rfind("\n", 0, at) + 1: text.find("\n", at) if text.find("\n", at) >= 0 else None]
        squeezed = squeeze(line)
        return not (len(squeezed) >= 40 and (squeezed in squeezed_abstract or mostly_in(squeezed, squeezed_abstract)))

    candidates = []
    for match in re.finditer(r"(?<![\w.])(\d+\.\d+)(?!\d)", abstract):
        lead = re.findall(r"[a-zA-Z]+", abstract[max(0, match.start() - 40): match.start()])[-2:]
        if len(lead) < 2:
            continue
        pattern = rf"(?i)\b{lead[0]}\W+{lead[1]}\W+(?:\$|\\num\{{|\{{)*({re.escape(match.group(1))})(?!\d)"
        for other in re.finditer(pattern, text[span[1]:]):
            if in_body(span[1] + other.start(1)):
                candidates.append((match.group(1), span[1] + other.start(1)))
    for token, at in rng.sample(candidates, min(PER_KIND, len(candidates))):
        new = shifted(token, 0.97)
        yield f"body {token} -> {new}", text[:at] + new + text[at + len(token):], rows, \
            lambda out, new=new: any(line.startswith("abstract:") and new in line for line in out)


def plant_percentage(text, rows, rng):
    """Add a sentence with counts and a wrong percentage to the body of the paper."""
    for trial in range(PER_KIND):
        total = rng.randint(40, 900)
        count = rng.randint(5, total - 5)
        wrong = f"{100 * count / total + rng.choice([-1, 1]) * rng.uniform(1.5, 6):.1f}"
        sentence = f"\n\nOf the {total} runs, {count} of {total} ({wrong}%) converged within the budget.\n\n"
        at = rng.randint(len(text) // 3, len(text) - 1)
        at = text.find("\n\n", at)
        at = at if at > 0 else len(text) // 2
        yield f"planted {count} of {total} ({wrong}%)", text[:at] + sentence + text[at:], rows, \
            lambda out, wrong=wrong: any(f"vs {float(wrong):g}" in line for line in out)


def plant_reference(text, rows, rng):
    """Rename the label of something the paper refers to, so the reference no longer resolves."""
    if "\\documentclass" not in text:
        return
    labels = [k for k in set(re.findall(r"\\label\{([^}#]+)\}", text)) if f"ref{{{k}}}" in text]
    for key in rng.sample(sorted(labels), min(PER_KIND, len(labels))):
        yield f"label {key} renamed", text.replace(f"\\label{{{key}}}", f"\\label{{{key}-x}}"), rows, \
            lambda out, key=key: any(line.startswith("concern:") and key in line for line in out)


def plant_citation(text, rows, rng):
    """Rename a bibliography entry that is cited, so the citation has nothing to point to."""
    if "\\bibitem" not in text:
        return
    keys = [k for k in set(re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", text)) if re.search(
        rf"\\cite[pt]?\*?(?:\[[^\]]*\])*\{{[^}}]*\b{re.escape(k)}\b", text)]
    for key in rng.sample(sorted(keys), min(PER_KIND, len(keys))):
        renamed = re.sub(rf"(\\bibitem(?:\[[^\]]*\])?\{{){re.escape(key)}\}}", rf"\g<1>{key}-x}}", text)
        yield f"bibitem {key} renamed", renamed, rows, \
            lambda out, key=key: any(line.startswith("concern:") and key in line for line in out)


PLANTERS = {"table": plant_table, "abstract_missing": plant_abstract_missing,
            "abstract_differs": plant_abstract_differs, "percentage": plant_percentage,
            "reference": plant_reference, "citation": plant_citation}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "evaluation.md"))
    args = parser.parse_args()
    papers = sorted(p.parent for p in (ROOT / "runs").glob("*/paper.json") if not p.parent.name.startswith("_"))
    totals = defaultdict(lambda: [0, 0])  # kind -> [planted, caught]
    per_paper, clean_flags, misses = [], [], []
    for run in papers:
        ingested = json.loads((run / "paper.json").read_text(encoding="utf-8"))
        text = ingested["text"]
        pdf = ROOT / PDFS.get(run.name, "")
        rows = pdf_tables(pdf) if ingested["method"] != "arxiv-latex" and pdf.is_file() else None
        rows = rows if rows is not None else (table_rows(text) if "\\documentclass" in text else None)
        clean = flagged(text, rows)
        clean_flags += [(run.name, line) for line in clean]
        rng = random.Random(f"{run.name}")  # the same errors every time
        counts = {}
        for kind, plant in PLANTERS.items():
            planted = caught = 0
            for description, mutated, mutated_rows, is_caught in plant(text, rows, rng) or []:
                planted += 1
                out = [line for line in flagged(mutated, mutated_rows) if line not in clean]
                if is_caught(out):
                    caught += 1
                else:
                    misses.append((run.name, kind, description))
            totals[kind][0] += planted
            totals[kind][1] += caught
            counts[kind] = (planted, caught)
        per_paper.append((run.name, ingested["method"], counts))
        print(run.name, {k: f"{c}/{p}" for k, (p, c) in counts.items() if p}, f"clean flags: {len(clean)}")

    lines = ["# Evaluation of the code-made checks", "",
             "Errors were planted, one per copy, in the texts of the papers audited so far, and each copy went "
             "through the checks the review runs without a model. Produced by `python tools/evaluate.py`; the "
             "errors are drawn with a fixed seed, so the numbers are the same on every run.", "",
             "| Kind of error | Planted | Caught |", "| --- | --- | --- |"]
    for kind, label in KINDS.items():
        planted, caught = totals[kind]
        if planted:
            lines.append(f"| {label} | {planted} | {caught} ({100 * caught / planted:.0f}%) |")
    planted = sum(p for p, _ in totals.values())
    caught = sum(c for _, c in totals.values())
    lines += [f"| **All** | **{planted}** | **{caught} ({100 * caught / max(planted, 1):.0f}%)** |", "",
              "## By paper", "", "| Paper | Source | " + " | ".join(KINDS) + " |",
              "| --- | --- | " + " | ".join("---" for _ in KINDS) + " |"]
    for name, method, counts in per_paper:
        lines.append(f"| {name} | {method} | " + " | ".join(
            f"{counts[k][1]}/{counts[k][0]}" if counts[k][0] else "–" for k in KINDS) + " |")
    lines += ["", "\"–\" means the paper offers nothing to plant that kind of error in (no table with an "
              "average, no abstract heading, no LaTeX labels).", "",
              "## Flags on the unmodified papers", ""]
    lines += [f"- {name}: {line[:300]}" for name, line in clean_flags] or ["None."]
    lines += ["", "Each flag above was looked at by hand: both are real. In GW150914 the 35–250 Hz sweep and the "
              "1.0 × 10⁻²¹ peak strain of the abstract are only read off Figure 1. In *Attention Is All You Need* "
              "the English-French BLEU of the big model is 41.8 in the abstract and the table and 41.0 in the text. "
              "In the review, a flag of the second kind is reported only after a model confirms both values are the "
              "same quantity (it did here).", "",
              "## What this shows and what it does not", "",
              "It shows that the checks work on the text of real papers, with their LaTeX, their transcription "
              "artefacts and their many numbers, and that they stay quiet where nothing is wrong. It does not "
              "measure how many of the errors in published papers are of these kinds, and the errors were planted "
              "by the same author who wrote the checks. The concerns written by models (soundness, evidence, "
              "missing details) are not measured here.", ""]
    if misses:
        lines += ["## Planted errors that were missed", ""] + [f"- {n}, {k}: {d}" for n, k, d in misses] + [""]
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{caught}/{planted} caught. Written to {args.out}")


if __name__ == "__main__":
    main()
