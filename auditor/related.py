"""Where a paper stands against earlier work, found with Tavily.

A referee asks two things of the literature: has this been done before, and
does the paper acknowledge the work closest to it. The search is real (Tavily);
which of its results count as related is the model's reading of their titles
and snippets; whether the paper cites a work is checked here against the
paper's own text.

Nothing is asserted beyond what the search returned: the works are not read,
and "not cited" means their title was not found in the paper.
"""

import json
import os
import re

from .llm import chat_json
from .memo import recall

MAX_QUERIES = 4
RESULTS_PER_QUERY = 5
# Places that explain or host things but are not the literature a referee compares a paper with.
NOT_LITERATURE = re.compile(r"(?i)://[^/]*(?:wikipedia\.org|medium\.com|wordpress|blogspot|substack\.com|github\.com"
                            r"|stackexchange\.com|stackoverflow\.com|mathoverflow\.net|reddit\.com|quora\.com"
                            r"|youtube\.com|scribd\.com|slideshare|towardsdatascience|machinelearningmastery"
                            r"|geeksforgeeks|kaggle\.com|linkedin\.com|blogs?\.)"
                            r"|/topics/|/glossary/|/wiki/")
# What a paper looks like from its address: a publisher or an archive, or a PDF wherever it is hosted.
LITERATURE = re.compile(r"(?i)://[^/]*(?:arxiv\.org|aclanthology\.org|openreview\.net|ieee\.org|acm\.org|springer\.com"
                        r"|sciencedirect\.com|nature\.com|mdpi\.com|wiley\.com|tandfonline\.com|aimsciences\.org"
                        r"|siam\.org|ams\.org|aps\.org|iop\.org|plos\.org|frontiersin\.org|biorxiv\.org|medrxiv\.org"
                        r"|nih\.gov|semanticscholar\.org|researchgate\.net|mlr\.press|neurips\.cc|thecvf\.com"
                        r"|jmlr\.org|hal\.science|zenodo\.org|ssrn\.com|cambridge\.org|oup\.com|science\.org"
                        r"|elifesciences\.org|copernicus\.org|ametsoc\.org|osti\.gov)"
                        r"|\.pdf(?:$|[?#])|/pdf/|/doi/")

QUERIES_PROMPT = """A referee wants to know whether the paper below has been done
before and what the closest earlier work is. Write {n} web search queries that
would find it: the specific problem, the specific method, the method applied
to this problem, and the name of the technique it builds on. Plain keywords in
English, no quotation marks, no author names.

Reply with a JSON object and nothing else: {{"queries": ["..."]}}

TITLE: {title}

WHAT THE PAPER DOES:
{summary}
"""

ASSESS_PROMPT = """A referee is placing the paper described below against earlier
work. Web search returned the results listed. Using only their titles and
snippets, pick those that are genuinely close to this paper and say how.

Reply with a JSON object and nothing else:
{{"related": [{{
    "url": "the url of the result, copied",
    "relation": "same problem" | "same method" | "builds on it" | "alternative approach",
    "note": "one sentence: what that work does and how it bears on this paper"
 }}],
 "assessment": "2-3 sentences on how new the contribution looks given these results. Say what could not be judged from snippets alone."
}}
List at most 8, closest first. A result that is a copy of the paper under
review gets the relation "this paper" (it is then set aside). Leave out
general background (lecture notes, tutorials, blog posts, encyclopedia
entries, forum threads), or unrelated. The search does not give dates: a
result may be later than the paper, so never call a work "prior" or "earlier".

THE PAPER
TITLE: {title}
WHAT IT DOES: {summary}

SEARCH RESULTS:
{results}
"""


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3]


def cited(title: str, paper: str) -> bool | None:
    """Whether a work's title appears in the paper; None when the title is too short or cut off to tell.

    A reference prints a title in one go, so all its distinctive words must fall within about the
    title's own length. Three common words ("stochastic gradient descent") prove nothing either way.
    """
    title = re.split(r"\s[-|–]\s|\s\|\s", title)[0]  # drop the site name after a dash
    distinctive = words(title)
    if len(distinctive) < 4 or title.rstrip().endswith(("...", "…")):
        return None
    text = paper.lower()
    for match in re.finditer(re.escape(distinctive[0]), text):
        window = text[max(0, match.start() - 20): match.start() + int(1.5 * len(title)) + 40]
        if all(w in window for w in distinctive):
            return True
    return False


def same_paper(result: dict, title: str, squeezed_paper: str) -> bool:
    """Whether a search result is the paper under review: its title, or a snippet that is the paper's own text."""
    own, theirs = set(words(title)), set(words(result["title"]))
    if len(theirs) >= 3 and len(own & theirs) >= 0.8 * min(len(own), len(theirs)):
        return True
    snippet = re.sub(r"[^a-z0-9]", "", result["content"].lower())
    runs = [snippet[i:i + 25] for i in range(0, len(snippet) - 25, 25)]  # short runs: a scan is transcribed with slips
    return sum(run in squeezed_paper for run in runs) >= 3


def year_of(url: str) -> int | None:
    """The year a work appeared, when its address says so: an arXiv or ACL Anthology id, or a /2018/ in the path."""
    arxiv = re.search(r"arxiv\.org/[a-z]+/(\d{2})(0[1-9]|1[0-2])\.\d{4,5}", url)
    if arxiv:
        return 2000 + int(arxiv.group(1))
    acl = re.search(r"aclanthology\.org/(?:[A-Z](\d{2})-\d{4}|(20\d{2})\.)", url)
    if acl:
        return int(acl.group(2)) if acl.group(2) else (1900 if int(acl.group(1)) > 60 else 2000) + int(acl.group(1))
    path = re.search(r"/((?:19|20)\d{2})/", url)
    return int(path.group(1)) if path else None


def related_work(title: str, summary: str, paper: str, year: int | None = None) -> dict | None:
    """Return {"queries", "related": [{title, url, relation, note, cited, year}], "assessment", "paper_year"}, or
    None without a Tavily key. `year` is the paper's own, to tell later work from work it could have cited."""
    if not os.getenv("TAVILY_API_KEY"):
        return None
    from tavily import TavilyClient

    queries = chat_json("ultra", [{"role": "user", "content": QUERIES_PROMPT.format(
        n=MAX_QUERIES, title=title, summary=summary)}], key="queries", max_tokens=600, purpose="related")["queries"]
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()][:MAX_QUERIES]
    tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    found = {}
    for query in queries:
        print(f"  tavily: {query}", flush=True)
        results = recall("search", {"query": query, "max_results": RESULTS_PER_QUERY}, lambda: [
            {"title": r["title"], "url": r["url"], "content": r["content"][:800]}
            for r in tavily.search(query, max_results=RESULTS_PER_QUERY)["results"]])
        for r in results:
            found.setdefault(r["url"], r)
    # the paper itself turns up in a search for its own subject: leave it out
    squeezed_paper = re.sub(r"[^a-z0-9]", "", paper.lower())
    candidates = [r for r in found.values()
                  if not same_paper(r, title, squeezed_paper)
                  and LITERATURE.search(r["url"]) and not NOT_LITERATURE.search(r["url"])]
    if not candidates:
        return {"queries": queries, "related": [], "assessment": "The search returned no papers.", "paper_year": year}
    reply = chat_json("ultra", [{"role": "user", "content": ASSESS_PROMPT.format(
        title=title, summary=summary, results=json.dumps(candidates, indent=1, ensure_ascii=False))}],
        key="related", max_tokens=2500, purpose="related")
    related, seen = [], set()
    for entry in reply.get("related") or []:
        source = found.get(str(entry.get("url", "")).strip()) if isinstance(entry, dict) else None
        name = re.sub(r"[^a-z0-9]", "", source["title"].lower())[:40] if source else ""
        if source and "this paper" in str(entry.get("relation", "")).lower():
            continue
        if source and name not in seen:  # only works the search really returned, each once
            seen.add(name)
            related.append({"title": source["title"], "url": source["url"],
                            "relation": str(entry.get("relation") or "related")[:40],
                            "note": str(entry.get("note") or "")[:300], "cited": cited(source["title"], paper),
                            "year": year_of(source["url"])})
    return {"queries": queries, "related": related[:8], "assessment": str(reply.get("assessment") or ""),
            "paper_year": year}
