"""What part of the paper an audit covers, and why the rest is left out.

An audit only speaks about results that can be recomputed. A paper is mostly
something else: motivation, theory, descriptions of the method, figures. Without
this account, a report on two tables reads as a report on the whole paper.

The tables and figures are found by code, so none can be silently skipped. The
model lists the sections and says, for every part, which claims came from it or
why none did.
"""

import json
import re

from .ingest import braced, table_rows
from .llm import chat_json

REASONS = {
    "theory": "Theory or derivation: the scripts are written from it, but it states no result to compare",
    "setup": "Describes the method: this is what the scripts implement, not a result to compare",
    "figure": "An image: described by a vision model for the review, but with no number to recompute",
    "needs_data": "Its results depend on data the paper does not contain",
    "hardware": "Reports timings or speed, which depend on the machine",
    "limit": "Has checkable results that were left out by the limit on claims",
    "other": "Other",
}

# A caption at the start of a line, in the languages papers are written in.
CAPTION = re.compile(r"(?im)^[\s*_>#-]*(Table|Tabla|Taula|Tableau|Tabelle|Fig\.|Fig|Figure|Figura|Abbildung)\s*(\d+)\s*[.:]\s*(.{0,200})")

PROMPT = """You extracted the claims below from the paper that follows, to audit
whether its results can be reproduced. Now account for the whole paper, so that
a reader knows what the audit covers and what it leaves out.

1. List the paper's top-level sections, in order, with their titles as written
   (at most 15; skip references and acknowledgements).
2. For each section, and for each table and figure listed below, give the ids
   of the claims that came from it. If none did, give the reason, one of:
   - "theory": motivation, explanation or derivation: it is used to write the
     scripts, but states no result of its own to compare
   - "setup": describes the method, an architecture or settings, which the
     scripts implement, not a result
   - "figure": an image whose content is not available as numbers in the text
   - "needs_data": its results depend on data the paper does not contain
   - "hardware": timings, speed-ups, throughput, memory
   - "limit": it has checkable results that the list of claims left out
   - "other"
   and a note of one short sentence saying what the part contains.

Reply with a JSON object and nothing else:
{{"sections": [{{"title": "...", "claims": ["C1"], "reason": null, "note": "..."}}],
 "items": [{{"id": "T1", "claims": [], "reason": "needs_data", "note": "..."}}]}}
"reason" is null when the part gave rise to claims.

TABLES AND FIGURES FOUND IN THE PAPER:
{items}

CLAIMS:
{claims}

PAPER:
{paper}

Now reply with the JSON object described above and nothing else.
"""


def inventory(paper: str) -> list[dict]:
    """The tables and figures of a paper: [{"id": "T1" | "F2", "kind", "caption"}]."""
    items = []
    if "\\documentclass" in paper or "\\begin{figure" in paper:  # LaTeX source
        tables = {}
        for tag, row in table_rows(paper).items():
            tables.setdefault(tag.split(".")[0], row["caption"])
        items += [{"id": t, "kind": "table", "caption": caption[:200]} for t, caption in tables.items()]
        figures = re.findall(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", paper, flags=re.DOTALL)
        items += [{"id": f"F{i}", "kind": "figure", "caption": braced(body, "caption")[:200]}
                  for i, body in enumerate(figures, 1)]
        return items
    found = {}
    for word, number, caption in CAPTION.findall(paper):  # transcribed PDF: go by the captions
        kind = "table" if word.lower().startswith("ta") else "figure"
        caption = " ".join(caption.split())[:200]
        # a page can be transcribed twice where strips overlap, and a caption can be cited: keep the fullest
        if len(caption) > len(found.get((kind, int(number)), "")):
            found[(kind, int(number))] = caption
    return [{"id": f"{'T' if kind == 'table' else 'F'}{number}", "kind": kind, "caption": caption}
            for (kind, number), caption in sorted(found.items(), key=lambda item: (item[0][0] != "table", item[0][1]))]


def account(paper: str, plan: dict) -> dict:
    """Return {"sections": [...], "items": [...]}: every part of the paper with its claims or the reason it has none."""
    items = inventory(paper)
    claims = [{"id": c["id"], "claim": c.get("summary") or c["statement"][:200], "location": c.get("location", "")}
              for c in plan["claims"]]
    reply = chat_json("ultra", [{"role": "user", "content": PROMPT.format(
        items=json.dumps(items, indent=1, ensure_ascii=False) or "(none found)",
        claims=json.dumps(claims, indent=1, ensure_ascii=False), paper=paper)}],
        key="sections", max_tokens=5000, purpose="coverage")
    known = {c["id"] for c in plan["claims"]}

    def clean(entry: dict) -> dict:
        ids = [c for c in entry.get("claims") or [] if c in known]
        reason = entry.get("reason")
        return {"claims": ids, "note": str(entry.get("note") or "")[:240],
                "reason": None if ids else reason if reason in REASONS else "other"}

    sections = [{"title": str(s.get("title", ""))[:120], **clean(s)}
                for s in reply.get("sections") or [] if isinstance(s, dict)][:15]
    said = {str(e.get("id")): e for e in reply.get("items") or [] if isinstance(e, dict)}
    accounted = []
    for item in items:
        entry = clean(said.get(item["id"], {"note": "not assessed"}))
        # A claim that points at a row of this table came from it, whatever the model says.
        rows = [c["id"] for c in plan["claims"] if (c.get("table_row") or "").split(".")[0] == item["id"]]
        if rows:
            entry |= {"claims": sorted(set(entry["claims"]) | set(rows), key=lambda i: int(i[1:])), "reason": None}
        accounted.append({**item, **entry})
    return {"sections": sections, "items": accounted}
