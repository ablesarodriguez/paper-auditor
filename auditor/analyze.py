"""Stage 3 - Analyze: decide how to implement each claim and what to assume
for the details the paper leaves out (Nemotron Ultra + Tavily search).

Three things keep the assumptions honest:
- a detail the plan called missing is dropped if the paper states it after
  all, which Ultra must prove with a quote that is then looked up in the text;
- Tavily searches for the authors' code and for the works the paper defers to,
  and the cited papers it finds on arXiv are read in full;
- a claim with no missing detail gets no assumption.
"""

import json
import os
import re

from .ingest import arxiv_latex, tidy_tables
from .llm import chat_json
from .memo import recall

MAX_QUERIES = 4
MAX_SOURCES = 1          # a second long text makes the model lose track of the task
SOURCE_CHARS = 25000
MIN_TITLE_OVERLAP = 0.8
MAX_ASSUMPTIONS = 3
MAX_ALTERNATIVES = 2

QUERIES_PROMPT = """These claims from the paper "{title}" are being reproduced.
Some details needed to reproduce them are missing from the paper:

{missing}

Write up to {n} web search queries that could recover those details: a standard
value of an omitted constant, or a later work that restates the setup. Write
each query as plain keywords, without quotation marks.
Reply with a JSON object and nothing else: {{"queries": ["..."]}}
"""

ANALYSIS_PROMPT = """You are planning the reproduction of claims from the paper below.

STEP 1 - Re-check what is missing. Each claim lists "missing_details". Search
the paper again for every one of them, including figure and table captions and
the description of the numerical experiments. If the paper does state it, report
it under "stated" with an exact quote copied character by character from the
paper (the quote is checked automatically; a detail without a matching quote
stays missing).

STEP 2 - For each detail that really is missing, make an explicit assumption: a
parameter with a default value and up to {max_alt} plausible alternative values.
The alternatives will be run to measure how much the result depends on the
assumption, so they must be values a careful reader could reasonably have chosen
instead, not extremes. Each assumption must be a simple choice (a number, a flag
or a named variant) that a short script can switch between. Do not make
assumptions about the authors' hardware or machine arithmetic, and never make an
assumption about something that is not in the claim's missing_details. An
assumption is an input of the computation, never the quantity the claim reports:
if what is missing is how a reported value was defined or measured, the
assumption is the definition (a named variant), not the value. A claim
with nothing missing gets an empty list. Use at most {max_assumptions}
assumptions per claim, keeping the ones most likely to affect the result.

When a cited source or a web search result below states a missing detail of the
experiment (an initial condition, a parameter value, a time span), use that
value as the default, give no alternatives, and set "source" to its URL. That is
the only use of those texts: they are other papers, about other methods. Never
take the method, its equations or its coefficients from them; the method is the
one in the paper being audited.

STEP 3 - Write a short implementation approach for each claim. Include every
formula or value taken from a cited source that the implementer will need, since
the implementer only sees this paper. The implementer will follow the approach
to the letter, so every setup value in it (initial conditions, amplitudes,
parameters, time span) must be the one the paper gives for that experiment, for
example read off the exact solution it compares with, or else be one of the
assumptions above. Never fill in a convenient default such as 1 for a value the
paper states.

Reply with a JSON object and nothing else:
{{"claims": {{"C1": {{
   "stated": [{{"detail": "the missing_details entry, copied", "name": "short_name",
               "value": "what the paper says", "quote": "exact words from the paper"}}],
   "assumptions": [{{
     "name": "python_identifier",
     "missing_detail": "the missing_details entry it stands for",
     "default": number | string | bool,
     "alternatives": [values of the same type],
     "rationale": "why these values",
     "source": "URL the default was taken from, or null"
   }}],
   "approach": "method and steps, 2-6 sentences"
}}}}}}

CLAIMS:
{claims}

WEB SEARCH RESULTS:
{search}

CITED SOURCES FOUND ON ARXIV:
{sources}

PAPER:
{paper}

Now reply with the JSON object described above, one entry per claim, and nothing else.
"""


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3}


def squeeze(text: str) -> str:
    """Letters and digits only, so that a quote matches whatever its spacing and LaTeX markup."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


# The authors' machine arithmetic is not something a script can meaningfully vary.
MACHINE = re.compile(r"precision|bits|float|arithmetic|word_?(length|size)|rounding_mode", re.IGNORECASE)


def gives_away_result(assumption: dict, claim: dict) -> bool:
    """Whether an assumption hands the script the number it is meant to compute.

    A script given its own answer can only copy it or ignore it. The value can
    hide in a string as well ("threshold_38_5"), so digits are compared.
    """
    expected = claim.get("expected_value")
    carried = squeeze(f"{assumption['name']} {json.dumps(assumption['default'])}")
    for number in expected if isinstance(expected, list) else [expected]:
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            continue
        if assumption["default"] == number:
            return True
        digits = re.sub(r"\D", "", repr(number).split("e")[0]).strip("0")
        if len(digits) >= 3 and digits in carried:
            return True
    return False


def search_missing_details(title: str, claims: list[dict]) -> tuple[list[dict], list[dict]]:
    """Ask Tavily for the details the paper omits.

    Returns the searches [{query, results}] and the cited papers read in full
    [{title, url, text}]: arXiv results whose title is named in a missing detail.
    """
    missing = [f"- {c['id']}: {d}" for c in claims for d in c["missing_details"]]
    deferred = list(dict.fromkeys(t for c in claims for t in c.get("deferred_to", [])))[:MAX_SOURCES]
    if not missing and not deferred:
        return [], []
    tavily_key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not tavily_key:
        print("  TAVILY_API_KEY not set, skipping web search")
        return [], []
    from tavily import TavilyClient

    # Fixed queries first: the authors' code settles more missing details than anything
    # else, and a work the paper defers to is where the missing setup is written down.
    queries = [f"{title} source code repository"] + [f"{t} arXiv" for t in deferred]
    if missing and len(queries) < MAX_QUERIES:
        generated = chat_json("nano", [{"role": "user", "content": QUERIES_PROMPT.format(
            title=title, missing="\n".join(missing), n=MAX_QUERIES - len(queries))}], key="queries")["queries"]
        queries += [line.strip() for q in generated if isinstance(q, str)
                    for line in q.splitlines() if line.strip()][:MAX_QUERIES - len(queries)]
    tavily = TavilyClient(api_key=tavily_key)
    searches, candidates = [], {}
    wanted, own = words(" ".join(deferred) or " ".join(missing)), words(title)
    for query in queries:
        print(f"  tavily: {query}")
        # Search results change from day to day: each query is answered once and recorded.
        results = recall("search", {"query": query, "max_results": 5}, lambda: [
            {"title": r["title"], "url": r["url"], "content": r["content"][:800]}
            for r in tavily.search(query, max_results=5)["results"]])
        searches.append({"query": query, "results": results})
        for r in results:
            arxiv = re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", r["url"])
            named = words(r["title"])
            if not arxiv or not named or len(named & own) / len(named) >= 0.9:  # not arXiv, or the paper itself
                continue
            score = len(named & wanted) / len(named)
            if score >= MIN_TITLE_OVERLAP:
                candidates.setdefault(arxiv.group(1), (score, r["title"]))

    sources = []
    for arxiv_id, (score, source_title) in sorted(candidates.items(), key=lambda c: -c[1][0])[:MAX_SOURCES]:
        text = recall("arxiv", {"id": arxiv_id}, lambda: arxiv_latex(arxiv_id))
        if text:
            print(f"  reading cited source arXiv:{arxiv_id} ({source_title})")
            sources.append({"title": source_title, "url": f"https://arxiv.org/abs/{arxiv_id}",
                            "text": tidy_tables(text)[:SOURCE_CHARS]})
    return searches, sources


def analyze(paper: str, plan: dict) -> dict:
    claims = [c for c in plan["claims"] if c["kind"] != "hardware"]
    squeezed_paper = squeeze(paper)
    searches, sources = search_missing_details(plan["title"], claims)
    analysis = chat_json("ultra", [{"role": "user", "content": ANALYSIS_PROMPT.format(
        max_alt=MAX_ALTERNATIVES, max_assumptions=MAX_ASSUMPTIONS,
        claims=json.dumps(claims, indent=1),
        search=json.dumps(searches, indent=1) if searches else "(none)",
        sources="\n\n".join(f"=== {s['title']} ({s['url']}) ===\n{s['text']}" for s in sources) or "(none)",
        paper=paper)}], key="claims", purpose="analysis", thinking=True, max_tokens=16000)["claims"]
    if isinstance(analysis, list):  # the model sometimes returns a list of entries instead of a map by id
        analysis = {str(e.get("id") or e.get("claim") or f"C{i}"): e
                    for i, e in enumerate(analysis, 1) if isinstance(e, dict)}

    for claim in claims:
        entry = analysis.setdefault(claim["id"], {})
        entry.setdefault("approach", "")
        # Rewording claims here was tried and dropped: it turned one into a remark about the paper.
        entry["statement"] = None

        # Keep only the "stated after all" details whose quote really is in the paper.
        proven = [s for s in entry.get("stated", []) if isinstance(s, dict)
                  and len(squeeze(str(s.get("quote", "")))) >= 10 and squeeze(str(s["quote"])) in squeezed_paper]
        entry["stated"], resolved = {}, set()
        for s in proven:  # it must answer one of the missing entries, wording aside; anything else is ignored
            named = words(str(s.get("detail", "")))
            best = max(claim["missing_details"], key=lambda d: len(words(d) & named), default=None)
            if best is not None and named and len(words(best) & named) / len(named) >= 0.6:
                resolved.add(best)
                # Keep the paper's own words, not the model's reading of them: the quote was
                # checked against the paper, the value it wrote next to it was not.
                entry["stated"][str(s.get("name") or best)] = f"the paper says: {' '.join(str(s['quote']).split())}"
        entry["missing_details"] = [d for d in claim["missing_details"] if d not in resolved]

        assumptions = [a for a in entry.get("assumptions", []) if isinstance(a, dict) and "name" in a
                       and "default" in a and not gives_away_result(a, claim) and not MACHINE.search(str(a["name"]))]
        assumptions = assumptions[:MAX_ASSUMPTIONS] if entry["missing_details"] else []
        for a in assumptions:
            a.setdefault("source", None)
            a.setdefault("rationale", "")
            a.setdefault("missing_detail", a["name"])
            # A value read from a source is not a guess: there is nothing to vary.
            a["alternatives"] = [] if a["source"] else [
                v for v in a.get("alternatives", []) if v != a["default"]][:MAX_ALTERNATIVES]
        entry["assumptions"] = assumptions
    return {"searches": searches, "sources": [{"title": s["title"], "url": s["url"]} for s in sources],
            "claims": analysis}
