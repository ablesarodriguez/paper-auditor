"""Stage 2 - Plan: extract the verifiable claims of a paper (Nemotron Ultra)."""

import ast
import math
import operator
import re

from .ingest import table_rows
from .llm import chat_json

DEFAULT_TOLERANCE = {"type": "relative", "value": 0.05}

PROMPT = """You are auditing the reproducibility of a computational paper.
Read the paper below and list the claims that can be checked by re-running the
computation on a laptop CPU in under a minute each.

A claim is a RESULT of the paper: something its method or analysis produces.
Never list a restatement of the setup (initial conditions, parameter values,
how output is formatted) or an arithmetic identity: checking those says nothing
about reproducibility. What defines the method is setup too: the nodes and
weights of a quadrature, the coefficients of a scheme, the form of its
equations. List each result once, however many times the paper mentions it.

List every claim of the paper that can be checked this way, up to {max_claims}.
Go through the abstract, every results section, every table, every figure
caption and the conclusions, and leave none out. Order them by this priority,
so that the same paper always yields the same list:
1. rows of the tables that report the outcome of a computation. They are the
   strongest claims: several numbers, to many digits. One claim per row.
   - If the row carries a tag such as [T1.R3], set "table_row" to that tag
     ("T1.R3") and do NOT type the row's numbers anywhere: leave
     expected_value null and describe in the statement only what the row is
     (which quantity, which experiment). The numbers and their column
     headings are filled in from the table itself. Read the table's caption to
     tell which experiment it belongs to; never describe a row with the
     settings of another table.
   - If rows carry no tags, copy the numbers of one row into expected_value,
     at most 4, leaving out the index column (iteration number, mesh size),
     and say in the statement which row and which step sizes they are.
2. the results the paper presents as its main findings (abstract, conclusions):
   stability thresholds, critical parameter values, conserved quantities,
   qualitative behaviours such as non-periodicity or sensitivity to initial
   conditions. One property per claim: never join two with "and".
   Whenever such a result is an exact value, state it as one, because a number
   recomputed to many digits is far stronger evidence than a yes/no check:
   set "exact_expression" to plain arithmetic for the value the paper asserts
   ("1" for "the map has determinant 1", "sqrt(42 - 6*sqrt(29))" for a
   threshold given by that formula, "470/19", "0" for a quantity said to
   vanish), and say in the statement which quantity must equal it. Use only
   numbers, + - * / **, sqrt, exp, log, sin, cos and pi;
3. other numbers derived in the text. Take all the numbers of a claim from one
   place: never combine values from two captions or two sentences.
Within a level, follow the order in which they appear in the paper.

For each claim, say whether it can be recomputed from the paper alone. Many
results are computed FROM data the paper only cites or describes: test images,
a dataset, measurements, a trained model, a corpus. Such a claim cannot be
repeated without that data, and running it on random or invented inputs proves
nothing. Set "needs_data" to a short description of the data it needs ("the
three test images A1, B2, C3 from dataset [3]") whenever the result depends on
inputs that are neither written in the paper in full nor among the files the
user supplied (listed below); set it to null when everything needed (equations,
parameters, initial conditions, or the supplied files) is at hand. When a claim
uses supplied files, name them in the statement. A claim about timings or
speed is "hardware" whatever data it needs.

For a claim that needs data which is not available, also set "without_data": a
property or trend the claim implies that does not depend on the particular
inputs, phrased so that a script can test it on substitute data with a yes or
a no ("the parallel variant gives a higher entropy than the sequential one on
the same image", "decoding returns the encoded image to within one grey level
in single precision"). Set it to null if nothing of the claim survives without
the original data.

DATA SUPPLIED BY THE USER WITH THE PAPER:
{data}

Classify each claim:
- "numeric": the paper reports a number, or a short list of numbers such as a
  table row, that a script can recompute. Prefer this kind whenever the paper
  gives numbers: the comparison is then done outside the script.
- "qualitative": the paper reports a behaviour (e.g. "the solution is non-periodic",
  "energy error stays bounded") that a script can test with an explicit criterion.
- "hardware": timings, speedups, throughput, memory. These cannot be audited.

Reply with a JSON object and nothing else. It must parse with a strict JSON
parser: plain numbers (0.001, not 10^-3), no LaTeX, and no double quotes inside strings.
{{"title": "paper title",
 "claims": [{{
   "id": "C1",
   "statement": "the claim, in one sentence",
   "location": "section / equation / table / figure",
   "table_row": "T1.R3" when the claim is a tagged table row, otherwise null,
   "exact_expression": arithmetic for an exact value the paper asserts, otherwise null,
   "kind": "numeric" | "qualitative" | "hardware",
   "needs_data": null, or the external data this result was computed from and that is not available,
   "without_data": null, or what can be tested on substitute data (only when needs_data is set),
   "expected": "the value or behaviour the paper reports, in words",
   "expected_value": number, or [numbers] in the order given in "expected", or null,
   "tolerance": {{"type": "relative" | "absolute", "value": number}} or null,
   "given_details": {{"name": "value the paper states (parameters, initial conditions, step sizes, method)"}},
   "missing_details": ["anything needed to reproduce the claim that the paper does not state"],
   "deferred_to": ["exact title of each cited work the paper defers to for a missing detail"]
 }}]}}

For numeric claims set expected_value and choose a tolerance justified by the
precision the paper reports: a value printed to 3 significant digits deserves a
relative tolerance near 0.01, one read off a figure a looser one. Copy
expected_value with exactly the digits the paper prints, and never set a
tolerance tighter than the last printed digit. When the paper gives an exact
expression next to a rough equivalent ("sqrt(42 - 6 sqrt(29)), approximately
pi"), expected_value is the value of the exact expression. Values at
round-off level (around 1e-14 or below) differ between machines and libraries:
state such a claim as qualitative ("stays below 1e-12"), never as numeric. An
empirical convergence order is numeric, with an absolute tolerance of a few tenths.

Be strict about missing_details. Search the whole paper, including figure and
table captions, before calling a detail missing; put everything the paper does
state into given_details. deferred_to is almost always empty. Fill it only when
the paper explicitly says that the setup or the exact solution of one of its
own experiments is given in another work ("the exact solution is established
in [7]") and a missing detail of this claim depends on it; then copy that
work's exact title from the bibliography. A reference cited as background or
for comparison is not a deferral.

PAPER:
{paper}
"""


MAX_NUMBERS = 12  # per claim


def well_formed(claim: dict) -> None:
    """Put a claim's expected value in the one shape the comparison understands.

    The model returns tables as nested rows, mixes words into number lists
    ("exact"), or labels a table of numbers as qualitative. Left as they are,
    such claims cannot be matched by any script, however correct.
    """
    def numbers(value) -> list:
        if isinstance(value, (list, tuple)):
            return [n for v in value for n in numbers(v)]
        return [value] if isinstance(value, (int, float)) and not isinstance(value, bool) else []

    value = claim.get("expected_value")
    flat = numbers(value)
    if isinstance(value, list):
        if len(flat) > MAX_NUMBERS:
            flat = flat[:MAX_NUMBERS]
            claim["expected"] = f"{claim.get('expected', '')} (only the first {MAX_NUMBERS} values, row by row, are compared)"
        claim["expected_value"] = flat if len(flat) > 1 else flat[0] if flat else None
        if len(flat) > 1:
            claim["kind"] = "numeric"  # a list of numbers is compared as numbers, whatever it was labelled
    elif not flat:
        claim["expected_value"] = None
    # A numeric claim without a number can only be checked as a behaviour.
    if claim["kind"] == "numeric" and claim["expected_value"] is None:
        claim["kind"] = "qualitative"


PLAIN_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
EXACT_TOLERANCE = {"type": "relative", "value": 1e-6}
FUNCTIONS = {"sqrt": math.sqrt, "exp": math.exp, "log": math.log, "sin": math.sin, "cos": math.cos,
             "tan": math.tan, "abs": abs}
CONSTANTS = {"pi": math.pi, "e": math.e}
OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
             ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def evaluate(expression: str) -> float | None:
    """Value of an arithmetic expression such as "sqrt(42 - 6*sqrt(29))", or None if it is not one."""
    def value(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name) and node.id in CONSTANTS:
            return CONSTANTS[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](value(node.left), value(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](value(node.operand))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS
                and len(node.args) == 1 and not node.keywords):
            return FUNCTIONS[node.func.id](value(node.args[0]))
        raise ValueError("not plain arithmetic")

    try:
        result = float(value(ast.parse(str(expression).replace("^", "**"), mode="eval").body))
        return result if math.isfinite(result) else None
    except (ValueError, SyntaxError, TypeError, ZeroDivisionError, OverflowError):
        return None


def from_expression(claim: dict) -> None:
    """Turn a claim about an exact value into a number to recompute to many digits.

    "The map has determinant 1" or "the threshold is sqrt(42 - 6 sqrt(29))" are
    the paper's strongest statements, and as true/false checks they are its
    weakest evidence. Given the exact expression, the expected value is computed
    here to full precision and the script has to arrive at it by another route.
    """
    if claim.get("table_row") or not claim.get("exact_expression"):
        claim.pop("exact_expression", None)
        return
    exact = evaluate(claim["exact_expression"])
    if exact is None:
        claim.pop("exact_expression", None)
        return
    claim |= {"kind": "numeric", "expected_value": exact, "exact": True, "tolerance": dict(EXACT_TOLERANCE)}


def from_table(claim: dict, rows: dict[str, dict]) -> None:
    """Fill a claim that points at a table row with that row's numbers, read by code.

    Left to copy a row by hand, the model takes digits from the neighbouring
    table, or attaches the row to the other table's column headings. Here it
    only names the row; the values and the columns they belong to come from
    the table itself.
    """
    tag = str(claim.get("table_row", "")).strip("[] ")
    row = rows.get(tag)
    if row and row["cells"] == row["header"]:
        # It pointed at the heading row. Take the row of that table whose label the statement talks about.
        said = set(re.findall(r"[a-z]{3,}", claim["statement"].lower()))
        table = tag.split(".")[0]
        candidates = {t: r for t, r in rows.items() if t.startswith(table + ".") and r["cells"] != r["header"]}
        tag = max(candidates, key=lambda t: len(said & set(re.findall(r"[a-z]{3,}", candidates[t]["cells"][0].lower()))),
                  default=None)
        row = candidates.get(tag)
        if row and not said & set(re.findall(r"[a-z]{3,}", row["cells"][0].lower())):
            row = None
    if not row:
        claim.pop("table_row", None)
        return
    claim["table_row"] = tag
    cells, header = row["cells"], row["header"]
    columns = [(header[i] if i < len(header) else f"column {i + 1}", cell) for i, cell in enumerate(cells)][1:]
    # A column of convergence orders is derived from the others: it is not a value to reproduce.
    values = [(name, float(cell)) for name, cell in columns
              if PLAIN_NUMBER.fullmatch(cell) and not re.search(r"(?i)\border\b", name)]
    if not values:
        claim.pop("table_row", None)
        return
    claim["kind"] = "numeric"
    claim["expected_value"] = [v for _, v in values] if len(values) > 1 else values[0][1]
    reading = "; ".join(f"{name} -> {cell}" for name, cell in columns)
    claim["expected"] = f"table row {claim['table_row']}, \"{cells[0]}\" ({header[0]}: {reading})"
    # The statement is rebuilt from the paper as well: the model points at the right row and
    # then describes its neighbour, and a script computes what the description says.
    claim["statement_as_extracted"] = claim["statement"]
    claim["statement"] = (
        f"In the table captioned \"{row['caption'][:400]}\", the row \"{cells[0]}\" reads, by {header[0]}: "
        + "; ".join(f"{name} -> {v:g}" for name, v in values) + "."
        + (f" The paper introduces this table as follows: \"{row['cited']}\"" if row["cited"] else ""))
    claim["location"] = f"table {row['label'] or tag.split('.')[0]}, row \"{cells[0]}\""
    # a short form for the report: the full statement carries a paragraph of context for the implementer
    claim["summary"] = (f"Table {row['label'] or tag.split('.')[0]}, row \"{cells[0]}\": "
                        + ", ".join(f"{v:g}" for _, v in values) + f" (by {header[0]}: "
                        + ", ".join(name for name, _ in values) + ")")


def distinct(claims: list[dict]) -> list[dict]:
    """Drop a claim that asks for the same thing as an earlier one: the same table row,
    or the same exact value. Asked for every claim, the model lists a result once for
    each place the paper mentions it, and each copy would count as a separate success."""
    kept, seen = [], set()
    for claim in claims:
        if claim.get("table_row"):
            key = ("row", claim["table_row"])
        elif claim.get("exact"):
            key = ("exact", round(claim["expected_value"], 10))
        else:
            key = ("claim", claim["id"])
        if key not in seen:
            seen.add(key)
            kept.append(claim)
    return kept


def extract_claims(paper: str, max_claims: int, data: str = "") -> dict:
    plan = chat_json("ultra", [{"role": "user", "content": PROMPT.format(
        max_claims=max_claims, paper=paper, data=data or "(none)")}],
        key="claims", purpose="plan", thinking=True, max_tokens=16000)
    plan.setdefault("title", "Untitled paper")
    plan["claims"] = plan["claims"][:max_claims]
    rows = table_rows(paper)
    for claim in plan["claims"]:
        from_table(claim, rows)
        from_expression(claim)
        well_formed(claim)
        if claim["kind"] == "numeric" and not claim.get("tolerance"):
            claim["tolerance"] = dict(DEFAULT_TOLERANCE)
        claim.setdefault("given_details", {})
        claim.setdefault("missing_details", [])
        needs = claim.get("needs_data")
        claim["needs_data"] = needs.strip() if isinstance(needs, str) and needs.strip().lower() not in ("", "null", "none") else None
        without = claim.get("without_data")
        claim["without_data"] = (without.strip() if claim["needs_data"] and isinstance(without, str)
                                 and without.strip().lower() not in ("", "null", "none") else None)
        claim["deferred_to"] = [t for t in claim.get("deferred_to") or [] if isinstance(t, str) and t.strip()]
    plan["claims"] = distinct(plan["claims"])
    return plan
