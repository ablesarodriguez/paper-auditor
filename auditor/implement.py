"""Stage 4 - Implement: write the script for one claim, run it, and repair it
from the error until it produces a result (Nemotron Super, with Nano for triage
and Ultra taking over the repair after two failures).

A script that runs must then pass two integrity checks before its output
counts: a literal scan for result values copied from the paper, and a review
for fabricated or shortcut computations by the Nemotron model that did not
write it. Both can only reject a result.

When the result does not match the paper, Nemotron Ultra gives a second
opinion: it checks the script against the paper and either confirms it is
faithful (the mismatch stands) or corrects it.
"""

import ast
import json
import re
from pathlib import Path

from .executor import Run, run_script
from .llm import chat, chat_json, extract_code, say

NEEDS_DATA_MARK = "needs the paper's data"  # what a script raises when it cannot run without external data
MAX_ATTEMPTS = 3      # two by Super, one by Ultra
MAX_FIX_ATTEMPTS = 1  # a second opinion gets one shot: its repairs rarely paid for themselves
# Super writes the code. Ultra as the author doubled the cost of an audit without
# better verdicts, so it only takes over the repair once Super has failed twice.
CODER = "super"
ESCALATE_AFTER = 2
# A script is under 3000 tokens; the rest is headroom for reasoning. When the
# reasoning runs away the reply hits this limit and is asked again without it,
# so the limit is what a runaway costs: keep it low.
CODE_MAX_TOKENS = 6000
REVIEW_MAX_TOKENS = 800  # reviews run without reasoning: a verdict and one sentence
OPINION_MAX_TOKENS = 4500  # a verdict, a reason and, at most, one corrected script

SCRIPT_RULES = """The script must start with:

    import json, sys
    PARAMS = json.load(open(sys.argv[1]))

PARAMS holds ONLY the keys listed below, the details the paper does not state.
Everything the paper does state (constants, initial conditions, step sizes) is
not in PARAMS: write those values in the script as constants.

Read each of these keys from PARAMS. The script will be run once with the
defaults and again with each alternative, to measure how much the result depends
on the assumption. So every parameter must enter the simulation itself, exactly
where the physics or the numerical method uses it, and the script must support
the default and every alternative. It is fine if the result turns out not to
depend on a parameter. Raise ValueError for an unsupported value.
{params}

RULES:
- Only the standard library, numpy, scipy, mpmath, sympy and PIL (pillow, to read images).
  No network, no file output, no plots.
{data_rule}
- Finish in under 60 seconds on one CPU core.
- Run the actual computation. Every number in the result must come out of the
  simulation this script performs. Never copy values the paper reports as results
  (table entries, errors, measured orders) into the script, and never add
  made-up terms. A reviewer will reject a script that does.
- Use the initial conditions, amplitudes, time span and step sizes the paper gives
  for this experiment. When the paper gives the exact solution it compares with,
  read the initial state off it.
- Measure with a margin above round-off. To estimate a convergence order, use
  step sizes whose errors stay well above 1e-11, and fit only those. To test that
  something equals an exact value through a finite difference or an iterative
  solve, allow for that method's own error (around 1e-6), not machine precision.
- Run everything at module level or call your main function: the script is executed, not imported.
- End by calling report(obtained, detail). The function report is already defined
  when the script runs: do not import or define it. "detail" is one sentence with
  the key numbers. numpy values are accepted as they are.
  {obtained_rule}"""

NO_DATA_RULE = """- Never substitute random or invented data for data the paper used (images, datasets,
  measurements). If the claim cannot be computed without such data, say so:
  raise RuntimeError("needs the paper's data: <what is missing>")."""

SUPPLIED_DATA_RULE = """- The data used in the paper was supplied with it. The files are in the folder named by
  DATA_DIR, a string that is already defined when the script runs:
{listing}
  Read them with os.path.join(DATA_DIR, "<file name>"), and use them wherever the paper's
  experiment used that data. Never replace them with invented data. If the claim needs
  data that is not among these files: raise RuntimeError("needs the paper's data: <what is missing>")."""

SUBSTITUTE_RULE = """- The data this result was computed from is not available ({needs}), so the paper's
  numbers cannot be reproduced here: do not try to match them. Implement the method exactly
  as the paper describes it, and run it on substitute inputs that the script generates:
  realistic for the method (for images, structured content such as gradients, edges, shapes
  and mild noise, never pure white noise), small enough to finish in time, with a fixed
  random seed. Say in "detail" what substitute data was used and what was measured."""

# Set by the audit when the user supplied data with the paper: the listing shown to the models.
data_listing = ""

CODE_PROMPT = """Write a self-contained Python script that reproduces one claim
from the paper below, using exactly the method and parameters the paper describes.

CLAIM:
{claim}

IMPLEMENTATION APPROACH:
{approach}

PARAMETERS. The paper does not state these, so they are passed in at run time.
{rules}

Reply with the full script in one ```python block.

PAPER:
{paper}
"""

OBTAINED_RULE = {
    "numeric": '"obtained" is the number (or the list of numbers, in the same order as expected_value) to '
               'compare against the paper, in the same units. Do not compare it with the paper yourself.',
    "qualitative": '"obtained" is true if the behaviour the paper claims is observed and false otherwise, '
                   'decided by an explicit numerical criterion that you state in "detail".',
}

REVIEW_PROMPT = """The script below is supposed to reproduce a claim from a paper
by actually running the computation. Your only job is to catch a script that
fakes its result.

You do not have the paper, so you cannot tell whether its equations, formulas,
coefficients or choice of method are the right ones: do not judge that, and
never reject a script because you would have used another formula or method.
Whether the result is correct is checked elsewhere, against the paper. If you
are unsure, answer that it is genuine.

It is NOT genuine only if it clearly does one of these:
- uses values the paper reports as results (table entries, errors, measured
  orders, final states) to produce its output, instead of computing them;
- adds made-up terms, offsets or "sensitivity" coefficients;
- runs on random or invented input data standing in for data the paper used
  (test images, a dataset, measurements) and presents the outcome as the paper's.
  This does not apply when the claim is marked "substitute": true: there the
  paper's data is unavailable and generating substitute inputs is what was asked;
- reads a parameter and then ignores it, or makes it affect the result artificially;
- returns the claimed value or "true" without any computation that could have
  come out otherwise, for instance by typing in or evaluating the very formula
  whose value is the claim.

Setup values the paper states (constants, initial conditions, step sizes) are fine,
and so is using the exact analytic solution to measure an error. The function
report() is supplied by the environment that runs the script: calling it without
defining it is correct.

Reply with a JSON object and nothing else: {{"genuine": true | false, "reason": "one sentence"}}

CLAIM:
{claim}

PARAMETERS THE SCRIPT RECEIVES:
{params}

SCRIPT:
{script}
"""

SECOND_OPINION_PROMPT = """An agent implemented a claim from the paper below, and its
result does not match what the paper reports. Before that counts against the
paper, check the script against the paper line by line: equations and
coefficients, signs, initial conditions, how the scheme is started, and exactly
what is measured (which norm, over which time span, how the reported quantity
is defined).

Do not tune anything to force agreement. Fix only what contradicts the paper.

The very first line of your reply must be one of these two, with nothing before
it (no analysis, no preamble; do the checking silently):
VERDICT: FAITHFUL
VERDICT: FIXED
Then one line "REASON: ..." that either says why the script is faithful, or names
the errors you found, in at most three sentences. If FIXED, follow with the full corrected script in one
```python block. The corrected script follows the same rules:

{rules}

CLAIM:
{claim}

RESULT OF THE SCRIPT: {obtained}  ({detail})

SCRIPT:
{script}

PAPER:
{paper}
"""

TRIAGE_PROMPT = """A generated Python script failed. Classify the failure with one
word from: syntax, dependency, runtime, numerical, timeout, output-format.
Reply with the word only.

{error}"""

HINTS = {
    "integrity": "Implement the numerical method and run it; take nothing from the paper's reported results.",
    "dependency": "Only numpy, scipy, mpmath, sympy and the standard library are installed.",
    "parameters": "PARAMS contains only the keys listed in the task. Every value the paper states "
                  "(constants, initial conditions, step sizes) must be a constant in the script.",
    "timeout": "The script is too slow: vectorise it or reduce the work while keeping the paper's parameters.",
    "numerical": "Check the equations, signs, units and the integration scheme against the paper.",
    "output-format": "End the script with report(obtained, detail), at module level or inside a main() "
                     "that the script calls. report is predefined: do not import it.",
}


def triage(error: str) -> str:
    """Name the kind of failure, so that the repair request can carry the right hint."""
    # The common ones are recognisable from the message; only the rest need a model.
    for marker, category in (("No module named", "dependency"), ("Timed out", "timeout"),
                             ("reported no result", "output-format"), ("SyntaxError", "syntax"),
                             ("IndentationError", "syntax"), ("KeyError", "parameters"),
                             ("parameter", "parameters")):
        if marker in error:
            return category
    word = chat("nano", [{"role": "user", "content": TRIAGE_PROMPT.format(error=error[-1500:])}],
                purpose="triage").strip().lower()
    return word if word in ("syntax", "dependency", "runtime", "numerical", "timeout", "output-format") else "runtime"


def copied_results(script: str, paper: str, claim: dict) -> list[str]:
    """Numeric literals of the script, with 5 or more significant digits, that the
    paper also prints and that are not part of the setup it states for the claim."""
    setup = json.dumps(claim["given_details"])
    # a value printed beside the result for comparison is not where the result comes from
    feeding = literals_feeding_report(script)
    written = feeding if feeding is not None else re.findall(r"(?<![\w.])\d+\.\d+", script)
    return sorted(lit for lit in set(written) if re.fullmatch(r"\d+\.\d+", lit)
                  and len(lit.replace(".", "").strip("0")) >= 5 and lit in paper and lit not in setup)


def evaluates_the_formula(script: str, claim: dict) -> bool:
    """Whether a script for an exact-value claim just computes the paper's own formula.

    Recomputing sqrt(42 - 6*sqrt(29)) proves that Python can do arithmetic. The
    constants of the formula (42, 29) have no business in a script that finds
    the threshold from the scheme, so their presence gives the shortcut away.
    Only numbers of two or more digits are considered: 1, 2 and 6 are everywhere.
    """
    constants = {c.lstrip("0") for c in re.findall(r"\d+(?:\.\d+)?", str(claim.get("exact_expression", "")))
                 if len(c.replace(".", "").lstrip("0")) >= 2}
    if not constants:
        return False
    # Only the numbers the reported value is computed from count: a script may print the paper's
    # value beside its own to compare them, and that is not where its result comes from.
    feeding = literals_feeding_report(script)
    found = feeding if feeding is not None else re.findall(r"(?<![\w.])\d+(?:\.\d+)?", script)
    literals = {lit.lstrip("0").rstrip("0").rstrip(".") if "." in lit else lit.lstrip("0") for lit in found}
    return constants <= literals


def literals_feeding_report(script: str) -> list[str] | None:
    """The numeric literals the value passed to report() depends on, following assignments and the
    functions it calls; None if that cannot be worked out (no report call, or the script does not parse)."""
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return None
    reported = [node.args[0] for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "report" and node.args]
    if not reported:
        return None
    sources: dict[str, list[ast.AST]] = {}  # name -> what it is computed from
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            sources.setdefault(node.name, []).append(node)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and node.value is not None:
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        sources.setdefault(name.id, []).append(node.value)
        elif isinstance(node, (ast.For, ast.comprehension)):
            for name in ast.walk(node.target):
                if isinstance(name, ast.Name):
                    sources.setdefault(name.id, []).append(node.iter)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            sources.setdefault(node.func.value.id, []).append(node)  # values.append(x): x flows into values
    literals, seen, pending = [], set(), list(reported)
    while pending:
        for sub in ast.walk(pending.pop()):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, (int, float)) and not isinstance(sub.value, bool):
                literals.append(ast.get_source_segment(script, sub) or repr(abs(sub.value)))  # as written
            elif isinstance(sub, ast.Name) and sub.id not in seen:
                seen.add(sub.id)
                pending += sources.get(sub.id, [])
    return literals


def integrity_problem(script: Path, claim: dict, params: dict, paper: str, author: str) -> str:
    """Return why the script's result cannot be trusted, or '' if it passes.

    The model review is done by the model that did not write the script.
    """
    source = script.read_text(encoding="utf-8")
    copied = copied_results(source, paper, claim)
    if copied:
        return f"the script contains values the paper reports: {', '.join(copied[:6])}"
    if claim.get("exact") and evaluates_the_formula(source, claim):
        return (f"the script evaluates the paper's own formula ({claim['exact_expression']}) instead of obtaining "
                "the value from the method. Remove the formula and its constants, and derive the value: build "
                "the scheme's matrices or equations and compute it from them, numerically if need be")
    reviewer = "super" if author == "ultra" else "ultra"
    review = chat_json(reviewer, [{"role": "user", "content": REVIEW_PROMPT.format(
        claim=json.dumps(claim, indent=1), params=json.dumps(params), script=source)}],
        key="genuine", max_tokens=REVIEW_MAX_TOKENS, purpose="review")
    return "" if review["genuine"] is True else str(review.get("reason", "rejected by the reviewer"))


def rules(claim: dict, assumptions: list[dict]) -> str:
    params = json.dumps([{k: a[k] for k in ("name", "missing_detail", "default", "alternatives")}
                         for a in assumptions], indent=1) if assumptions else "(none: PARAMS is an empty object)"
    if claim.get("substitute"):
        data_rule = SUBSTITUTE_RULE.format(needs=claim.get("needs_data"))
        rule = ('"obtained" is true if this holds on the substitute data and false if it does not: '
                f'{claim["without_data"]}' if claim.get("without_data") else
                '"obtained" is true once the method has run from start to finish on the substitute data '
                "as the paper describes it (for a codec: encode, decode and compare).")
        return SCRIPT_RULES.format(params=params, obtained_rule=rule, data_rule=data_rule)
    data_rule = SUPPLIED_DATA_RULE.format(listing=indent(data_listing)) if data_listing else NO_DATA_RULE
    rule = OBTAINED_RULE[claim["kind"]]
    if claim.get("exact"):
        rule += (" The paper asserts this value exactly. Do not evaluate the paper's closed-form expression "
                 "for it: obtain it from the method itself, numerically if need be (build the scheme's matrices "
                 "and take their determinant, locate a threshold by scanning and bisecting, integrate and "
                 "measure), so that the script would return something else if the paper were wrong.")
    if claim["kind"] == "numeric" and isinstance(claim["expected_value"], list):
        rule += (f' It must be a flat list of exactly {len(claim["expected_value"])} numbers, one for each '
                 "value the paper reports, in the paper's order.")
    return SCRIPT_RULES.format(params=params, obtained_rule=rule, data_rule=data_rule)


def indent(text: str) -> str:
    return "\n".join("  " + line for line in text.splitlines())


def develop(role: str, messages: list[dict], reply: str | None, attempts: int,
            claim: dict, params: dict, paper: str, script: Path) -> tuple[Run, list[str]]:
    """Run the script in `reply` (or ask `role` for one), repairing it until it
    produces a trustworthy result. Returns the run and each failure category."""
    failures = []
    for attempt in range(attempts):
        if attempt == ESCALATE_AFTER:
            role = "ultra"
        reply = reply or chat(role, messages, thinking=True, max_tokens=CODE_MAX_TOKENS, purpose="code")
        script.write_text(extract_code(reply), encoding="utf-8")
        run = run_script(script, params)
        if NEEDS_DATA_MARK in run.error:
            return run, failures  # nothing to repair: the claim rests on data the paper does not contain
        if run.ok:
            problem = integrity_problem(script, claim, params, paper, author=role)
            if not problem:
                return run, failures
            run, category = Run(error=f"Rejected by the integrity check: {problem}"), "integrity"
        else:
            category = triage(run.error)
        failures.append(category)
        say(f"attempt {attempt + 1} failed ({category})")
        messages = messages + [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": f"The script failed ({category}):\n{run.error}\n"
                                        f"{HINTS.get(category, '')}\nReply with the full corrected script."}]
        reply = None
    return run, failures


def implement(claim: dict, analysis: dict, paper: str, workdir: Path) -> tuple[Run, list[str]]:
    """Return the baseline run and the failure category of each failed attempt."""
    workdir.mkdir(parents=True, exist_ok=True)
    params = {a["name"]: a["default"] for a in analysis["assumptions"]}
    messages = [{"role": "user", "content": CODE_PROMPT.format(
        claim=json.dumps(claim, indent=1), approach=analysis["approach"],
        rules=rules(claim, analysis["assumptions"]), paper=paper)}]
    return develop(CODER, messages, None, MAX_ATTEMPTS, claim, params, paper, workdir / "script.py")


REFERENCE_NOTE = """

REFERENCE. The script below reproduced another result of this paper to
{digits} significant digits, so its setup is known to be right: the scheme, the
parameters, the initial conditions, the time span and how errors are measured.
The result it reproduced: {statement}
If your claim comes from the same experiment, start from this script and change
only what your claim needs (the quantity computed, the step sizes, the output).
If your claim is about a different experiment, ignore the script and implement
the claim from the paper.

```python
{script}
```
"""


def with_reference(claim: dict, analysis: dict, paper: str, workdir: Path, reference: dict) -> Run:
    """Write the script again, starting from one that reproduced a sibling claim.

    Claims are audited independently, and the model often gets the experiment
    right for one row of a table and wrong for the next (another amplitude,
    another time span). A script that matched the paper to many digits settles
    those choices for the claims that share its experiment.
    """
    params = {a["name"]: a["default"] for a in analysis["assumptions"]}
    # The first approach is left out on purpose: it is what led the claim astray, and the
    # model follows it over anything said later.
    approach = ("Adapt the reference script given below, which is known to reproduce this paper. "
                "Keep its scheme, parameters, initial conditions and time span.")
    prompt = CODE_PROMPT.format(claim=json.dumps(claim, indent=1), approach=approach,
                                rules=rules(claim, analysis["assumptions"]), paper=paper)
    cut = prompt.index("\nReply with the full script")
    prompt = prompt[:cut] + REFERENCE_NOTE.format(digits=reference["digits"], statement=reference["statement"],
                                                 script=reference["script"]) + prompt[cut:]
    run, _ = develop(CODER, [{"role": "user", "content": prompt}], None, 2, claim, params, paper,
                     workdir / "script_ref.py")
    return run


def second_opinion(claim: dict, analysis: dict, paper: str, workdir: Path, first: Run) -> tuple[dict, Run | None]:
    """Have Ultra check a mismatching script against the paper.

    Returns the opinion {"verdict": "faithful" | "fixed" | "fix_failed" | "unavailable", "reason"}
    and, when the script was corrected and runs, the new run (script_v2.py).
    """
    params = {a["name"]: a["default"] for a in analysis["assumptions"]}
    messages = [{"role": "user", "content": SECOND_OPINION_PROMPT.format(
        rules=rules(claim, analysis["assumptions"]), claim=json.dumps(claim, indent=1),
        obtained=json.dumps(first.obtained), detail=first.detail,
        script=(workdir / "script.py").read_text(encoding="utf-8"), paper=paper)}]
    # Without reasoning: with it, 8 of 10 of these calls spent their whole output thinking and
    # never reached a verdict, and every usable answer came from the retry without it.
    reply = chat("ultra", messages, max_tokens=OPINION_MAX_TOKENS, purpose="second opinion")
    reason =(re.search(r"REASON:\s*(.+)", reply) or [None, ""])[1].strip()
    if "VERDICT: FAITHFUL" in reply:
        return {"verdict": "faithful", "reason": reason}, None
    if "VERDICT: FIXED" not in reply or "```" not in reply:  # truncated or malformed reply: no opinion
        return {"verdict": "unavailable", "reason": "the reviewer gave no usable answer"}, None
    run, _ = develop("ultra", messages, reply, MAX_FIX_ATTEMPTS, claim, params, paper, workdir / "script_v2.py")
    if not run.ok:
        return {"verdict": "fix_failed", "reason": reason}, None
    return {"verdict": "fixed", "reason": reason}, run
