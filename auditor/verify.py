"""Stage 5 - Verify: compare results with the paper and measure sensitivity
to each assumption. Deterministic: no model takes part in a verdict."""

import math
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from .executor import Run, run_script
from .llm import say

VERIFIED = "verified"
VERIFIED_IF = "verified_under_assumption"  # the paper's numbers come out for one value of a missing detail
NOT_VERIFIED = "not_verified"
NOT_VERIFIABLE = "not_verifiable"          # hardware-dependent
BLOCKED = "blocked_by_missing_detail"      # the result depends on a missing detail and cannot be settled
NEEDS_DATA = "needs_data"                  # rests on data the paper does not contain (images, datasets)
# Without the paper's data its numbers cannot be checked, but the method can still be built
# from the text and run on substitute inputs:
SUBSTITUTE_OK = "holds_on_substitute_data"      # the behaviour the claim implies shows up there
SUBSTITUTE_FAIL = "fails_on_substitute_data"    # it does not
METHOD_ONLY = "method_implemented"              # nothing of the claim is testable, but the method runs
NOT_IMPLEMENTED = "implementation_failed"  # the agent produced no working script
MALFORMED = "claim_malformed"              # the claim itself was extracted wrongly


def as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def fmt_short(value) -> str:
    """A result for the progress log: numbers to 4 significant digits."""
    if isinstance(value, list):
        return "[" + ", ".join(fmt_short(v) for v in value) + "]"
    return f"{value:.4g}" if isinstance(value, float) else str(value)


def close(claim: dict, got, reference) -> bool:
    """Whether two numeric results agree within the claim's tolerance."""
    reference, got, tol = as_list(reference), as_list(got), claim["tolerance"]
    if len(reference) != len(got) or any(isinstance(g, bool) for g in got):
        return False
    return all(abs(g - r) <= (tol["value"] * abs(r) if tol["type"] == "relative" and r else tol["value"])
               for g, r in zip(got, reference))


ROUND_OFF = 1e-12  # below this, a reported value is floating-point noise
MIN_RELATIVE_TOLERANCE = 1e-4


def printed_resolution(value: float) -> float:
    """How far a recomputed value may sit from a printed one because of the printing alone.

    Two units of the last decimal the paper printed: papers truncate as often as
    they round (28.959 printed as 28.9), and a faithful recomputation on another
    machine moves the last digit by one. Half a unit for a value printed as an integer.
    """
    exponent = Decimal(repr(value)).as_tuple().exponent
    return 2.000001 * 10.0 ** exponent if exponent < 0 else 0.5 * 10.0 ** exponent


def agrees(claim: dict, got: float, expected: float) -> bool:
    if claim.get("exact"):
        return close(claim, got, expected)  # nothing was printed or rounded: only the stated tolerance applies
    if 0 < abs(expected) < ROUND_OFF:
        # Round-off noise differs between machines and libraries: only its level is reproducible.
        return abs(got) < 100 * ROUND_OFF
    # Whatever tolerance the plan chose, agreement to four significant digits is a match:
    # two correct implementations differ beyond that in a tiny error term.
    return (close(claim, got, expected) or abs(got - expected) <= printed_resolution(expected)
            or abs(got - expected) <= MIN_RELATIVE_TOLERANCE * abs(expected))


def matches(claim: dict, obtained) -> bool:
    if claim["kind"] == "qualitative":
        return obtained is True
    expected, got = as_list(claim["expected_value"]), as_list(obtained)
    if len(expected) != len(got) or any(isinstance(g, bool) for g in got):
        return False
    return all(agrees(claim, g, e) for g, e in zip(got, expected))


NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])")
MIN_DIGITS = 4       # a printed number needs this many significant digits to identify a result
MAX_ROW_SPAN = 600   # characters: the numbers of one table row sit close together


def locate_in_paper(obtained, paper: str) -> dict | None:
    """Find the computed numbers printed in the paper, one after another.

    Claim extraction sometimes copies the expected values from the wrong table.
    When a script's numbers disagree with them, this looks for the script's own
    numbers in the text: several multi-digit values printed in a row, in the same
    order, cannot be there by chance. Returns {"values", "quote"} or None.
    """
    wanted = as_list(obtained)
    if any(isinstance(w, bool) for w in wanted):
        return None
    tokens = []
    for m in NUMBER.finditer(paper):
        try:
            tokens.append((m.start(), m.end(), float(m.group(0)), len(re.sub(r"[eE].*|\D", "", m.group(0)).lstrip("0"))))
        except ValueError:
            pass
    def unit(text: str) -> float:  # one unit of the last digit of a number as printed
        mantissa, _, exponent = text.lower().partition("e")
        decimals = len(mantissa.partition(".")[2])
        return 10.0 ** (int(exponent or 0) - decimals)

    enough = STRONG_DIGITS if len(wanted) > 1 else MIN_DIGITS + 1  # printed digits that identify the result
    # Tables are often printed at another scale (Lorenz prints ten times each value).
    def same(w: float, t: tuple, scale: float) -> bool:
        # A recomputed value can differ from the printed one in its last digit (truncation, round-off).
        return abs(w * scale - t[2]) <= max(1.000001 * unit(paper[t[0]:t[1]]), 2e-4 * abs(t[2]))

    for scale in (1, 10, 100, 1000, 0.1, 0.01, 0.001):
        for start in range(len(tokens)):
            # Follow the printed numbers from here, allowing one number to be skipped between
            # matches: tables carry an index column (iteration, mesh size) the script does not return.
            row, at, skipped = [], start, 0
            for w in wanted:
                if at < len(tokens) and same(w, tokens[at], scale):
                    row.append(tokens[at]); at += 1
                elif row and at + 1 < len(tokens) and same(w, tokens[at + 1], scale):
                    row.append(tokens[at + 1]); at += 2; skipped += 1
                else:
                    break
            if len(row) < len(wanted):
                continue
            # What identifies the result is how many digits really agree, not how many the paper
            # printed: a computed 0 "matches" every 0 and 1 in the text within one unit.
            agreeing = 0
            for w, t in zip(wanted, row):
                if t[2]:
                    error = abs(w * scale - t[2]) / abs(t[2])
                    agreeing += t[3] if error == 0 else max(0, min(t[3], int(-math.log10(error))))
            if agreeing < enough + (4 if skipped else 0):
                continue
            if row[-1][1] - row[0][0] > MAX_ROW_SPAN * max(1, len(wanted) // 4):
                continue
            values = [t[2] / scale for t in row]
            return {"values": values if isinstance(obtained, list) else values[0], "scale": scale,
                    "quote": " ".join(paper[max(0, row[0][0] - 60):row[-1][1]].split())[:400]}
    return None


STRONG_DIGITS = 6  # agreeing significant digits, summed over a claim's numbers, that chance cannot explain


def printed_digits(value: float) -> int:
    """Significant digits of a number as the paper prints it: 8.95248e-06 -> 6, 38.5 -> 3, 6 -> 1."""
    return len(re.sub(r"\D", "", repr(value).split("e")[0]).strip("0"))


EXACT_DIGITS = 12  # the most a double-precision recomputation of an exact value can be credited with


def agreeing_digits(got, expected, exact: bool = False) -> int:
    """How many significant digits of the paper's numbers the computation recovers, in total.

    A printed number can only be matched to the digits the paper printed. An
    exact value the paper asserts (a determinant of 1, a threshold given by a
    formula) is matched to as many digits as the computation gets right.
    """
    total = 0
    for g, e in zip(as_list(got), as_list(expected)):
        if isinstance(g, bool):
            continue
        if exact:
            error = abs(g - e) / abs(e) if e else abs(g)
            total += EXACT_DIGITS if error == 0 else max(0, min(EXACT_DIGITS, int(-math.log10(error))))
        elif e:
            error = abs(g - e) / abs(e)
            total += printed_digits(e) if error == 0 else max(0, min(printed_digits(e), int(-math.log10(error))))
    return total


def not_printed(expected, paper: str) -> list:
    """The expected numbers, of three or more digits, that the paper's text does not contain."""
    printed = {re.sub(r"[eE].*|\D", "", m.group(0)).strip("0") for m in NUMBER.finditer(paper)}
    missing = []
    for e in as_list(expected):
        digits = re.sub(r"\D", "", repr(e).split("e")[0]).strip("0")
        if len(digits) >= 3 and not any(digits in p for p in printed):
            missing.append(e)
    return missing


SAME_PLACE = 700  # characters: a table row or a caption, with room for markup


def scattered(expected, paper: str) -> bool:
    """Whether a claim's expected numbers come from different places in the paper.

    The numbers of a real claim sit together: one table row, one caption, one
    sentence. A claim stitched together from two captions or two tables is a
    misreading, and nothing computed can match it. Only numbers the paper
    prints as such, with three digits or more, are considered.
    """
    places = []
    for e in as_list(expected):
        if isinstance(e, bool) or not isinstance(e, (int, float)):
            continue
        digits = re.sub(r"\D", "", repr(e).split("e")[0]).strip("0")
        if len(digits) < 3:
            continue
        found = [m.start() for m in NUMBER.finditer(paper)
                 if digits in re.sub(r"[eE].*|\D", "", m.group(0)).strip("0")]
        if found:
            places.append(found)
    if len(places) < 2:
        return False
    # Is there one spot from which every number is within reach?
    return not any(all(any(abs(p - anchor) <= SAME_PLACE for p in other) for other in places[1:])
                   for anchor in places[0])


def assess(result: dict, paper: str, ingest_method: str) -> dict:
    """Say how far a claim's verdict can be trusted, and why not when it cannot.

    Returns {"confidence": "high" | "caveats" | None, "warnings": [...]}. Every
    rule here is mechanical: a verdict is "high" only when the paper's own
    printed numbers are recovered to many digits, under no assumption.
    """
    verdict_, warnings = result["verdict"], []
    if verdict_ == NOT_VERIFIABLE:
        return {"confidence": None, "warnings": []}
    if verdict_ in (SUBSTITUTE_OK, SUBSTITUTE_FAIL, METHOD_ONLY):
        unchecked = (f"The value the paper reports was not checked: it was computed from data that is not "
                     f"available ({result.get('needs_data')}). The method was built from the paper's description "
                     "and run on substitute data generated by the script.")
        outcome = {
            SUBSTITUTE_OK: "The behaviour the claim implies holds there. That supports the method as described; "
                           "it says nothing about the reported value.",
            SUBSTITUTE_FAIL: "The behaviour the claim implies does not hold there. The cause may be the substitute "
                             "data or the agent's implementation rather than the paper.",
            METHOD_ONLY: "It ran from start to finish, so the description is complete enough to implement. "
                         "Nothing else of this claim can be tested without the original data.",
        }[verdict_]
        return {"confidence": "caveats", "warnings": [unchecked, outcome]}
    if verdict_ == NEEDS_DATA:
        return {"confidence": None, "warnings": [
            f"This result was computed from data that is not in the paper: {result.get('needs_data')}. "
            "Without that data the computation cannot be repeated, and it was not attempted: a script "
            "run on made-up inputs would say nothing about the paper."]}
    if verdict_ == MALFORMED:
        return {"confidence": None, "warnings": [
            "The values this claim expects come from different places in the paper (two captions, two "
            "tables): it was extracted wrongly and was not audited. This says nothing about the paper."]}
    if verdict_ == NOT_IMPLEMENTED:
        return {"confidence": None, "warnings": [
            f"The agent could not produce a working script after {len(result['failed_attempts'])} attempts. "
            "This says nothing about the paper."]}

    numeric = result["kind"] == "numeric"
    variants = result.get("sensitivity", [])
    matching = result["obtained"] if result.get("matches_paper") else next(
        (v["obtained"] for v in variants if v["matches"]), None)
    # What a second model said about a script that was later replaced is history, not a caveat.
    opinion = {} if result.get("built_on") else result.get("second_opinion") or {}

    if not numeric:
        warnings.append("Qualitative claim: the pass/fail criterion was chosen by the agent's script, "
                        "not taken from the paper, so this is weaker evidence than a recomputed number.")
    elif matching is not None:
        digits = agreeing_digits(matching, result["expected_value"], exact=bool(result.get("exact")))
        result["agreeing_digits"] = digits
        expected = result["expected_value"] if isinstance(result["expected_value"], list) else [result["expected_value"]]
        if all(isinstance(v, (int, float)) and abs(v) < ROUND_OFF for v in expected):
            warnings.append("The paper's values are at the level of floating-point round-off: only that level "
                            "can be reproduced, not the digits, so the match shows the quantity is conserved to "
                            "machine precision and no more.")
        elif digits < STRONG_DIGITS:
            warnings.append(f"Weak numeric evidence: the agreement covers only {digits} significant digit(s) "
                            "in total, which a wrong computation could also produce.")
    if numeric and not result.get("exact"):  # an exact value is computed from the paper's formula, not printed
        absent = not_printed(result["expected_value"], paper)
        if absent:
            warnings.append(f"The expected value(s) {absent} do not appear in the paper's text as such: they were "
                            "derived or rescaled by the model that extracted the claim, and may be wrong.")

    if verdict_ == VERIFIED_IF:
        warnings.append("The paper's numbers come out only for a particular value of "
                        f"{', '.join(result['decisive_assumptions'])}, which the paper does not state.")
    if verdict_ == BLOCKED:
        warnings.append("The result depends on a detail the paper does not state "
                        f"({'; '.join(result['decisive_assumptions'])}) and no tried value reproduces the paper.")
    if verdict_ in (NOT_VERIFIED, BLOCKED):
        warnings.append("The computed result differs from the paper's. The error may be in the agent's "
                        "implementation rather than in the paper.")
        if ingest_method == "pdf-scan" and numeric:
            warnings.append("The paper is a scan: a digit misread in transcription could also cause this mismatch.")
    if opinion.get("verdict") == "faithful":
        warnings.append("A second model checked the script against the paper and found no error in it.")
    elif opinion.get("verdict") == "fix_did_not_help":
        warnings.append("A second implementation gave a different result that does not match the paper either: "
                        "the two implementations disagree.")
    elif opinion.get("verdict") == "unavailable":
        warnings.append("The script could not be checked by a second model.")
    elif opinion.get("verdict") == "fixed" and (not numeric or result.get("agreeing_digits", 0) < STRONG_DIGITS):
        warnings.append("The first implementation did not match; one corrected by a second model did.")

    if result.get("located_in_paper"):
        warnings.append("The expected values first extracted from the paper were wrong. The computed values were "
                        "found printed in the paper and taken as what it reports.")
    failed = sum(1 for v in variants if v["error"])
    if failed:
        warnings.append(f"{failed} of {len(variants)} sensitivity runs failed and are not counted.")
    return {"confidence": "caveats" if warnings or verdict_ != VERIFIED else "high", "warnings": warnings}


def relative_change(new, baseline) -> float | None:
    """Largest relative change of any component, signed."""
    new, baseline = as_list(new), as_list(baseline)
    if len(new) != len(baseline) or any(isinstance(v, bool) for v in new + baseline):
        return None
    return max(((n - b) / abs(b) for n, b in zip(new, baseline) if b), key=abs, default=None)


def sensitivity(claim: dict, assumptions: list[dict], baseline: Run, script: Path) -> list[dict]:
    """Re-run the script changing one assumption at a time."""
    defaults = {a["name"]: a["default"] for a in assumptions}
    cases = [(a["name"], value) for a in assumptions for value in a["alternatives"]]
    with ThreadPoolExecutor(max(1, len(cases))) as pool:  # the executor caps how many scripts run at once
        runs = list(pool.map(lambda case: run_script(script, {**defaults, case[0]: case[1]}), cases))
    variants = []
    for (name, value), run in zip(cases, runs):
        variants.append({
            "assumption": name, "value": value, "obtained": run.obtained, "detail": run.detail,
            "error": run.error.strip().splitlines()[-1] if run.error else "",
            "matches": matches(claim, run.obtained) if run.ok else None,
            "relative_change": relative_change(run.obtained, baseline.obtained) if run.ok else None,
            # Identical output can mean the result is robust, or that the script ignores the parameter.
            "identical_output": run.ok and (run.obtained, run.detail) == (baseline.obtained, baseline.detail),
        })
        say(f"{name}={value!r} -> {fmt_short(run.obtained) if run.ok else 'error'}")
    return variants


def verdict(claim: dict, baseline: Run, variants: list[dict]) -> tuple[str, list[str]]:
    """Return the verdict and the assumptions it hinges on.

    A numeric match within tolerance is strong evidence, so when the paper's
    numbers come out for some value of a missing detail and not for others, the
    claim is verified under that assumption. A true/false outcome that flips is
    not evidence either way: the claim is blocked. When nothing matches, the
    claim is blocked if the result moves with an assumption (the right value
    may simply not have been tried), or if the paper omits a detail that could
    not be turned into an assumption at all; then the missing details themselves
    are returned. It is not verified when nothing is missing, or when what is
    missing was varied and makes no difference.
    """
    numeric = claim["kind"] == "numeric"
    ran = [v for v in variants if v["matches"] is not None]
    baseline_matches = matches(claim, baseline.obtained)
    flipping = sorted({v["assumption"] for v in ran if v["matches"] != baseline_matches})
    if flipping:
        return (VERIFIED_IF if numeric else BLOCKED), flipping
    if baseline_matches:
        return VERIFIED, []
    moving = sorted({v["assumption"] for v in ran if not close(claim, v["obtained"], baseline.obtained)}) if numeric else []
    if moving:
        return BLOCKED, moving
    if not ran and claim["missing_details"]:
        return BLOCKED, claim["missing_details"]
    return NOT_VERIFIED, []
