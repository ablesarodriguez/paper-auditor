"""Record of every non-deterministic step, so that an audit is a function of the paper.

The shared inference endpoints are not deterministic: the same request at
temperature 0 with a fixed seed returns different text from one call to the
next (measured: 9 identical requests gave 8 or 9 distinct replies, for every
Nemotron model, with and without reasoning). Web search results and generated
scripts that use randomness vary too.

So each such step is computed once and stored under the hash of its exact
input. Every later step builds its input from the paper and from earlier
results, so the whole chain is pinned: the same paper yields the same report,
byte for byte, for as long as the store is kept. Deleting the store makes the
next audit of a paper start from nothing, and it may then come out differently.
"""

import hashlib
import json
import os
import threading
from pathlib import Path

STORE = Path(os.getenv("AUDITOR_STORE", "store"))

# Which audit of the current paper is being produced. Model replies are recorded
# per attempt, so that a paper can be audited afresh without losing the earlier
# audits: attempt 2 asks the models everything again, attempt 1 stays as it was.
attempt = 1


def paper_key(source: str) -> str:
    """Identify a paper by what it is, not by what its file is called."""
    path = Path(source)
    return hashlib.sha256(path.read_bytes()).hexdigest()[:20] if path.is_file() else f"arxiv-{source}"


def select_attempt(source: str, redo: bool = False, choose: int | None = None) -> int:
    """Set and return the attempt in force for a paper.

    Without options it is the one last used, so repeated audits agree. `redo`
    moves to a new attempt; `choose` goes back to a given one.
    """
    global attempt
    record = STORE / "papers" / f"{paper_key(source)}.json"
    state = json.loads(record.read_text(encoding="utf-8")) if record.exists() else {"current": 1, "latest": 1}
    if redo:
        state["current"] = state["latest"] = state["latest"] + 1
    elif choose is not None:
        if not 1 <= choose <= state["latest"]:
            raise SystemExit(f"This paper has attempts 1 to {state['latest']}")
        state["current"] = choose
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({**state, "source": Path(source).name}), encoding="utf-8")
    attempt = state["current"]
    return attempt

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def recall(kind: str, request, compute):
    """Return the stored result of `request`, computing and storing it the first time.

    `request` and the result must be JSON-serialisable. Two threads asking for
    the same thing at once get the same answer: the second waits for the first.
    """
    key = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    path = STORE / kind / key[:2] / f"{key}.json"
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["result"]
        result = compute()
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        partial.write_text(json.dumps({"result": result}, ensure_ascii=False), encoding="utf-8")
        partial.replace(path)  # never leave a half-written record behind
        return result
