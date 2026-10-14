"""Audit the reproducibility of a computational paper.

    python -m auditor 2504.00560
    python -m auditor papers/paper.pdf --data images/ measurements.csv

Each stage saves its output under runs/<paper>/ and is skipped on re-runs
unless --fresh is given.
"""

import argparse
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import executor, llm, memo, verify
from . import implement as implement_module
from .data import collect, describe
from .analyze import analyze
from .analyze import words
from .coverage import account
from .executor import Run
from .implement import NEEDS_DATA_MARK, implement, second_opinion, with_reference
from .figures import appendix as figures_appendix
from .figures import describe as describe_figures
from .ingest import ARXIV_ID, fetch, ingest, pdf_tables
from .related import related_work
from .llm import say
from .plan import extract_claims
from .report import write_report
from .review import optional, review

PARALLEL_CLAIMS = 12
# verdicts no further attempt can change
SETTLED = (verify.NOT_VERIFIABLE, verify.MALFORMED, verify.NEEDS_DATA, verify.SUBSTITUTE_OK,
           verify.SUBSTITUTE_FAIL, verify.METHOD_ONLY)


def cached(path: Path, compute):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    value = compute()
    path.write_text(json.dumps(value, indent=1), encoding="utf-8")
    return value


CLAIM_FIELDS = ("id", "statement", "summary", "table_row", "exact", "exact_expression", "needs_data", "location", "kind", "expected", "expected_value", "tolerance",
                "given_details", "missing_details", "deferred_to")


def evaluate(claim: dict, analysis: dict, run: Run, script: Path, paper: str, result: dict) -> tuple[list, bool]:
    """Compare a run with the paper and vary the assumptions. Returns (variants, reproduced)."""
    say(f"obtained {verify.fmt_short(run.obtained)} -> "
        f"{'match' if verify.matches(claim, run.obtained) else 'no match'}")
    variants = verify.sensitivity(claim, analysis["assumptions"], run, script)
    if any(v["matches"] for v in variants) or verify.matches(claim, run.obtained):
        return variants, True
    if claim["kind"] == "numeric":
        # The expected values may have been copied from the wrong place. If the paper
        # prints the computed numbers one after another, those are the ones it reports.
        for obtained in [run.obtained] + [v["obtained"] for v in variants if v["obtained"] is not None]:
            located = verify.locate_in_paper(obtained, paper)
            if located:
                say(f"computed values found printed in the paper: {located['quote'][-120:]}")
                result |= {"expected_value_as_extracted": claim["expected_value"],
                           "located_in_paper": located["quote"], "expected_value": located["values"]}
                claim["expected_value"] = located["values"]
                for v in variants:
                    v["matches"] = verify.matches(claim, v["obtained"]) if v["obtained"] is not None else None
                return variants, True
    return variants, False


def conclude(result: dict, claim: dict, run: Run, script: Path, variants: list, reproduced: bool) -> dict:
    result |= {"obtained": run.obtained, "detail": run.detail, "script": script.name, "reproduced": reproduced,
               "matches_paper": verify.matches(claim, run.obtained), "sensitivity": variants}
    result["verdict"], result["decisive_assumptions"] = verify.verdict(claim, run, variants)
    return result


def first_pass(claim: dict, analysis: dict, paper: str, workdir: Path) -> dict:
    """Implement one claim on its own and compare it with the paper."""
    result = {**claim, "approach": analysis["approach"], "assumptions": analysis["assumptions"]}
    baseline, failures = implement(claim, analysis, paper, workdir)
    result["failed_attempts"] = failures
    if not baseline.ok:
        error = baseline.error.strip().splitlines()[-1]
        if NEEDS_DATA_MARK in error:  # the script itself reported that it cannot run without the paper's data
            return {**result, "verdict": verify.NEEDS_DATA, "reproduced": False,
                    "needs_data": error.split(NEEDS_DATA_MARK, 1)[1].strip(" :.") or "data the paper does not contain"}
        return {**result, "verdict": verify.NOT_IMPLEMENTED, "reproduced": False, "error": error}
    script = workdir / "script.py"
    variants, reproduced = evaluate(claim, analysis, baseline, script, paper, result)
    return conclude(result, claim, baseline, script, variants, reproduced)


def build_on(result: dict, analysis: dict, paper: str, workdir: Path, reference: dict) -> dict:
    """Try a claim again starting from the script that reproduced a sibling claim."""
    result = dict(result)
    claim = {k: result[k] for k in CLAIM_FIELDS if k in result}
    run = with_reference(claim, analysis, paper, workdir, reference)
    if run.ok:
        script = workdir / "script_ref.py"
        variants, reproduced = evaluate(claim, analysis, run, script, paper, result)
        if reproduced:
            say(f"reproduced starting from the script of {reference['id']}")
            result.pop("error", None)
            return conclude({**result, "built_on": reference["id"]}, claim, run, script, variants, True)
    return result


def substitute_pass(claim: dict, approach: str, paper: str, workdir: Path) -> dict:
    """Audit a claim whose data is missing: build the method and run it on substitute inputs."""
    analysis = {"approach": approach, "assumptions": []}
    result = {**claim, "approach": approach, "assumptions": [], "sensitivity": [], "reproduced": False,
              "matches_paper": False}
    run, failures = implement(claim, analysis, paper, workdir)
    result["failed_attempts"] = failures
    if not run.ok:
        error = run.error.strip().splitlines()[-1]
        if NEEDS_DATA_MARK in error:
            return {**result, "verdict": verify.NEEDS_DATA}
        return {**result, "verdict": verify.NOT_IMPLEMENTED, "error": error}
    say(f"on substitute data -> {run.obtained}")
    result |= {"obtained": run.obtained, "detail": run.detail, "script": "script.py"}
    if not claim.get("without_data"):
        # nothing of the claim is testable: all the run shows is that the method can be implemented
        if run.obtained is True:
            return {**result, "verdict": verify.METHOD_ONLY}
        return {**result, "verdict": verify.NOT_IMPLEMENTED, "error": "the method did not run from start to finish"}
    return {**result, "verdict": verify.SUBSTITUTE_OK if run.obtained is True else verify.SUBSTITUTE_FAIL}


def rescue(result: dict, analysis: dict, paper: str, workdir: Path, reference: dict | None) -> dict:
    """Second chance for a claim the first pass did not reproduce.

    First from a script that reproduced a sibling claim, when there is one: it
    is cheap and it settles the setup. Then, if a result exists and still
    disagrees, by having a second model check the script against the paper.
    """
    if reference:
        result = build_on(result, analysis, paper, workdir, reference)
        if result["reproduced"]:
            return result
    result = dict(result)
    claim = {k: result[k] for k in CLAIM_FIELDS if k in result}
    if result["verdict"] == verify.NOT_IMPLEMENTED:
        return result
    # No tried value reproduces the paper. That may be the agent's bug, not the
    # paper's: have the script checked against the paper.
    baseline = Run(obtained=result["obtained"], detail=result["detail"])
    opinion, corrected = second_opinion(claim, analysis, paper, workdir, baseline)
    result["second_opinion"] = {**opinion, "first_obtained": baseline.obtained}
    say(f"second opinion: {opinion['verdict']}")
    if corrected:
        # A correction replaces the first script only if it reproduces the paper.
        # Otherwise there are two implementations that disagree and no reason to
        # prefer the second: the first result stands and both are reported.
        result["second_opinion"]["corrected_obtained"] = corrected.obtained
        script = workdir / "script_v2.py"
        variants, reproduced = evaluate(claim, analysis, corrected, script, paper, result)
        if reproduced:
            return conclude(result, claim, corrected, script, variants, True)
        result["second_opinion"]["verdict"] = "fix_did_not_help"
    return result


def references(results: list[dict], out: Path) -> list[dict]:
    """Scripts that reproduced the paper's numbers to many digits: safe to build on."""
    found = []
    for r in results:
        if not r.get("reproduced") or r["kind"] != "numeric":
            continue
        matching = r["obtained"] if r["matches_paper"] else next(
            (v["obtained"] for v in r["sensitivity"] if v["matches"]), None)
        digits = verify.agreeing_digits(matching, r["expected_value"]) if matching is not None else 0
        if digits >= verify.STRONG_DIGITS:
            found.append({"id": r["id"], "statement": r["statement"], "digits": digits, "table_row": r.get("table_row"),
                          "script": (out / r["id"] / r["script"]).read_text(encoding="utf-8")})
    return found


def closest(result: dict, candidates: list[dict]) -> dict | None:
    """The reference most likely to share the claim's experiment: the one whose statement shares most words."""
    def shared(candidate: dict) -> int:
        return len(words(candidate["statement"]) & words(result["statement"]))

    if result.get("table_row"):
        # A row shares its experiment with the other rows of its table, and with nothing else:
        # rows of another table have the same wording and a different setup.
        table = result["table_row"].split(".")[0]
        candidates = [c for c in candidates if (c.get("table_row") or "").split(".")[0] == table]
        return max(candidates, key=lambda c: c["digits"], default=None)
    best = max(candidates, key=shared, default=None)
    return best if best and shared(best) >= 3 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paper", help="path to a PDF, or an arXiv id such as 2504.00560")
    parser.add_argument("--max-claims", type=int, default=20, help="upper bound; the plan lists every claim it finds")
    parser.add_argument("--data", nargs="*", default=[], metavar="PATH",
                        help="files or folders with the data the paper's results were computed from")
    parser.add_argument("--review-only", action="store_true",
                        help="read the paper as a referee and stop: no attempt to recompute its results")
    parser.add_argument("--fresh", action="store_true", help="rebuild the run folder (same audit, from the record)")
    parser.add_argument("--redo", action="store_true", help="audit the paper again from scratch, as a new attempt")
    parser.add_argument("--attempt", type=int, help="go back to an earlier attempt of this paper")
    args = parser.parse_args()

    out = Path("runs") / (args.paper if ARXIV_ID.fullmatch(args.paper) else Path(args.paper).stem)
    attempt = memo.select_attempt(args.paper, redo=args.redo, choose=args.attempt)

    # Data supplied with the paper lives outside the run folder, which is rebuilt at will.
    data_folder = Path("data") / out.name
    if args.data:
        collect(args.data, data_folder)
    data_listing, data_fingerprint = describe(data_folder)
    implement_module.data_listing = data_listing
    executor.data_dir, executor.data_fingerprint = (str(data_folder.resolve()), data_fingerprint) if data_listing else ("", "")

    marker = out / "attempt.json"
    built = json.loads(marker.read_text()) if marker.exists() else {}
    now = {"attempt": attempt, "data": data_fingerprint}
    if out.exists() and (args.fresh or built != now):  # the run folder belongs to another attempt, or to other data
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(now))
    print(f"attempt {attempt}" + (f", with {len(data_listing.splitlines())} data files" if data_listing else ""))
    llm.trace_dir = out / "trace"
    started = time.monotonic()

    def stage(name: str):
        print(f"{name}  (+{time.monotonic() - started:.0f} s)", flush=True)

    stage("1/6 ingest")
    ingested = cached(out / "paper.json", lambda: dict(zip(("text", "method"), ingest(args.paper))))
    paper = ingested["text"]
    say(f"{len(paper)} characters ({ingested['method']})")

    # Figures are read from the PDF, also for arXiv papers whose text comes from the LaTeX source.
    pdf = Path(args.paper) if not ARXIV_ID.fullmatch(args.paper) else Path("papers") / f"arxiv_{args.paper}.pdf"
    if not pdf.exists():
        pdf.parent.mkdir(exist_ok=True)
        pdf.write_bytes(fetch(f"https://arxiv.org/pdf/{args.paper}"))
    seen = cached(out / "figures.json", lambda: describe_figures(pdf, paper))
    say(f"{len(seen)} figures described from their images")
    written = paper  # the paper's own words: what a quote must be found in
    paper += figures_appendix(seen)

    stage("review")
    # a PDF's tables are read from its text layer by PyMuPDF, with no model: the review checks their sums
    tables = pdf_tables(pdf) if ingested["method"] != "arxiv-latex" and pdf.exists() else None
    reading = cached(out / "review.json", lambda: review(paper, written, tables))
    say(f"{len(reading['concerns'])} concerns tied to the text ({reading['dropped']} dropped as unfounded), "
        f"{len(reading['consistency'])} numerical cross-checks, "
        f"{sum(not c['consistent'] for c in reading['consistency'])} of them inconsistent")
    # an arXiv id carries the date; otherwise the year the paper prints
    dated = ARXIV_ID.fullmatch(args.paper) and args.paper[:4].isdigit() and "." in args.paper
    year = 2000 + int(args.paper[:2]) if dated else reading.get("year")
    earlier = cached(out / "related.json",
                     lambda: optional(None, related_work, reading["title"], reading["summary"], written, year))
    if earlier:
        say(f"{len(earlier['related'])} related works found, "
            f"{sum(r['cited'] is False for r in earlier['related'])} of them not cited by the paper")

    if args.review_only:
        audit = {"title": reading["title"], "ingest_method": ingested["method"], "claims": [], "review": reading,
                 "related": earlier, "figures": seen, "data": data_listing}
        (out / "audit.json").write_text(json.dumps(audit, indent=1), encoding="utf-8")
        (out / "report.md").write_text(write_report(audit, out), encoding="utf-8")
        stats = {"seconds": round(time.monotonic() - started), "cost_usd": dict(llm.session_cost), "calls": llm.calls}
        (out / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
        print(f"\n{out / 'report.md'}  ({stats['seconds']} s, this run: ${sum(llm.session_cost.values()):.3f}, "
              f"total spent: ${llm.spent():.3f})")
        return

    stage("2/6 plan")
    plan = cached(out / "plan.json", lambda: extract_claims(paper, args.max_claims, data_listing))
    for c in plan["claims"]:
        say(f"{c['id']} [{c['kind']}] {(c.get('summary') or c['statement'])[:200]}")

    coverage = cached(out / "coverage.json", lambda: account(paper, plan))

    stage("3/6 analyze")
    analysis = cached(out / "analysis.json", lambda: analyze(paper, plan))

    stage("4/6 implement + 5/6 verify")

    def process(claim: dict) -> dict:
        llm.tag_log(claim["id"])
        if claim["kind"] == "hardware":
            return {**claim, "verdict": verify.NOT_VERIFIABLE, "confidence": None, "warnings": [
                "Depends on the hardware it ran on (timing, speed-up, memory): it cannot be recomputed elsewhere."]}
        if claim.get("needs_data"):
            # The number cannot be checked, but the method can still be built from the paper and
            # run on substitute data, which tests what the claim implies beyond that number.
            say(f"needs data that is not available ({claim['needs_data'][:70]}): method built, run on substitute data")
            approach = analysis["claims"].get(claim["id"], {}).get("approach", "")
            claim = {**claim, "substitute": True, "paper_kind": claim["kind"], "kind": "qualitative"}
            return cached((out / claim["id"]).with_suffix(".json"),
                          lambda: substitute_pass(claim, approach, paper, out / claim["id"]))
        if claim["kind"] == "numeric" and verify.scattered(claim["expected_value"], paper):
            say("expected values come from different places in the paper: not audited")
            return {**claim, "verdict": verify.MALFORMED, "reproduced": False, "assumptions": []}
        workdir = out / claim["id"]
        claim_analysis = analysis["claims"][claim["id"]]
        # The analysis re-checked the paper: what it proved to be stated is no longer
        # missing, and a statement that misreported the paper is corrected.
        claim = {**claim, "given_details": {**claim["given_details"], **claim_analysis["stated"]},
                 "missing_details": claim_analysis["missing_details"]}
        if claim_analysis.get("statement"):
            claim |= {"statement": claim_analysis["statement"], "statement_as_extracted": claim["statement"]}
        return cached(workdir.with_suffix(".json"), lambda: first_pass(claim, claim_analysis, paper, workdir))

    def second_chance(result: dict) -> dict:
        llm.tag_log(result["id"])
        if result.get("reproduced") or result["verdict"] in SETTLED:
            return result
        workdir = out / result["id"]
        reference = closest(result, trusted)
        return cached(workdir.with_suffix(".rescue.json"),
                      lambda: rescue(result, analysis["claims"][result["id"]], paper, workdir, reference))

    # Claims are independent, so they are audited side by side. Those that fail get a
    # second chance, building on the scripts that reproduced the paper in the first pass.
    def third_chance(result: dict) -> dict:
        llm.tag_log(result["id"])
        reference = None if result.get("reproduced") or result["verdict"] in SETTLED else closest(result, trusted)
        if reference is None or any(r["id"] == reference["id"] for r in first_trusted):
            return result  # nothing new to build on since the second chance
        workdir = out / result["id"]
        return cached(workdir.with_suffix(".built.json"),
                      lambda: build_on(result, analysis["claims"][result["id"]], paper, workdir, reference))

    def guarded(step):
        """One claim the endpoint keeps failing on must not stop the audit of the others.

        A failed first pass is recorded as no result, with the reason; a failed later chance
        leaves the claim as it was. Running out of budget still stops everything.
        """
        def run(item: dict) -> dict:
            try:
                return step(item)
            except llm.SpendCapReached:
                raise
            except Exception as error:  # noqa: BLE001 - any failure of one claim is reported in its verdict
                say(f"{step.__name__} failed: {str(error)[:160]}")
                if step is not process:
                    return item
                return {**item, "verdict": verify.NOT_IMPLEMENTED, "reproduced": False, "assumptions": [],
                        "confidence": None, "warnings": [f"The audit of this claim failed: {str(error)[:200]}"]}
        return run

    with ThreadPoolExecutor(PARALLEL_CLAIMS) as pool:
        results = list(pool.map(guarded(process), plan["claims"]))
        trusted = first_trusted = references(results, out)
        results = list(pool.map(guarded(second_chance), results))
        # A rescue can produce the first script that reproduces an experiment: give the
        # claims that are still failing a chance to build on it.
        trusted = references(results, out)
        results = list(pool.map(guarded(third_chance), results))
    for result in results:
        if result["verdict"] != verify.NOT_VERIFIABLE:
            result |= verify.assess(result, paper, ingested["method"])
        print(f"  [{result['id']}] VERDICT {result['verdict']} ({result['confidence'] or 'no result'})", flush=True)

    stage("6/6 report")
    audit = {"title": plan["title"], "ingest_method": ingested["method"], "claims": results,
             "review": reading, "related": earlier, "figures": seen, "data": data_listing, "coverage": coverage, "searches": analysis["searches"],
             "sources": analysis["sources"]}
    (out / "audit.json").write_text(json.dumps(audit, indent=1), encoding="utf-8")
    (out / "report.md").write_text(write_report(audit, out), encoding="utf-8")
    # Time and cost depend on what was already recorded, so they are kept out of the audit itself.
    stats = {"seconds": round(time.monotonic() - started), "cost_usd": dict(llm.session_cost),
             "calls": llm.calls}
    (out / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(f"\n{out / 'report.md'}  ({stats['seconds']} s, this run: ${sum(llm.session_cost.values()):.3f}, "
          f"total spent: ${llm.spent():.3f})")


if __name__ == "__main__":
    main()
