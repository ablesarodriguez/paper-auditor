"""Runs one generated script. Invoked as: python runner.py script.py params.json

Generated scripts compute the right thing and then fail to hand it over: a
numpy bool that json cannot write, a result left in a variable, a main() that
is never called. This wrapper takes those failures out of the models' hands:

- json.dumps accepts numpy scalars and arrays;
- the script may call report(obtained, detail) instead of formatting a line;
- DATA_DIR names the folder with the data supplied with the paper;
- if nothing was reported, a module-level `obtained` (and `detail`) is used,
  after calling main() when the script defines one and never ran it.
"""

import builtins
import json
import os
import re
import sys

_plain_default = json.JSONEncoder.default


def _default(self, value):
    for convert in ("tolist", "item"):  # numpy arrays and scalars, without importing numpy here
        if hasattr(value, convert):
            return getattr(value, convert)()
    return _plain_default(self, value)


json.JSONEncoder.default = _default

_reported = False
_print = builtins.print


def report(obtained, detail=""):
    """Hand the result of the script to the auditor."""
    global _reported
    _reported = True
    _print("RESULT: " + json.dumps({"obtained": obtained, "detail": str(detail)}), flush=True)


def _watching_print(*args, **kwargs):
    global _reported
    if args and isinstance(args[0], str) and args[0].startswith("RESULT:"):
        _reported = True
    _print(*args, **kwargs)


builtins.report = report
builtins.print = _watching_print
# Where the data supplied with the paper lives ("" when there is none).
builtins.DATA_DIR = os.environ.get("AUDIT_DATA_DIR", "")

script, params = sys.argv[1], sys.argv[2]
sys.argv = [script, params]
with open(script, encoding="utf-8") as f:
    source = f.read()
# Scripts sometimes define their own empty report() "because the environment provides
# it", which hides the real one and throws the result away. Move theirs out of the way.
source = re.sub(r"(?m)^def report\(", "def _script_own_report(", source)
scope = {"__name__": "__main__", "__file__": script}
exec(compile(source, script, "exec"), scope)
if not _reported and "obtained" not in scope and callable(scope.get("main")):
    returned = scope["main"]()  # defined but never called
    if not _reported and returned is not None:
        scope = {**scope, "obtained": returned}
if not _reported and "obtained" in scope:
    report(scope["obtained"], scope.get("detail", ""))
