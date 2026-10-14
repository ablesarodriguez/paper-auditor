"""Runs a generated script with a set of parameters.

The script contract: read a JSON parameter file from sys.argv[1] and print a
final line `RESULT: {"obtained": <number|[numbers]|bool>, "detail": "..."}`.

This backend is a local subprocess. It runs in a temporary folder outside the
project and sees no environment variable beyond what Python needs, so neither
the API keys nor the .env file are within reach of a relative path; it is not
a sandbox (the network and absolute paths are open). It is the only module
that changes when execution moves to Token Factory Sandboxes.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .memo import recall

TIMEOUT_S = 75  # scripts are asked to finish within 60 s
DATA_TIME_FACTOR = 4  # real inputs (full-size images) take longer than the toy cases a paper's equations give
# Set by the audit when the user supplied data with the paper.
data_dir, data_fingerprint = "", ""
# Scripts run through a wrapper that makes handing over the result forgiving (see runner.py).
RUNNER = Path(__file__).with_name("runner.py").resolve()
RUNNER_VERSION = 3 # part of the record key: a new wrapper can change what a script returns
# Scripts are CPU-bound: never run more of them at once than there are cores.
_cpu_slots = threading.BoundedSemaphore(max(2, (os.cpu_count() or 4) - 1))


@dataclass
class Run:
    obtained: float | list[float] | bool | None = None
    detail: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.obtained is not None


def flatten(values: list) -> list:
    """[[1, 2], [3, 4]] -> [1, 2, 3, 4]. Booleans inside a list become 0/1 mistakes later, so they stay."""
    flat = []
    for v in values:
        flat.extend(flatten(v) if isinstance(v, (list, tuple)) else [v])
    return flat


def run_script(script: Path, params: dict) -> Run:
    """Run a script with a set of parameters.

    The outcome is recorded per (script text, parameters): a script that uses
    unseeded randomness, or that finishes close to the time limit, would
    otherwise give a different result on another day.
    """
    source = script.read_text(encoding="utf-8")
    request = {"script": source, "params": params, "runner": RUNNER_VERSION}
    if data_fingerprint:
        request["data"] = data_fingerprint  # the same script on other data is another computation
    return Run(**recall("run", request, lambda: asdict(execute(script, params))))


# What a generated script may see of the environment: enough for Python and its libraries to run,
# nothing else. The API keys live in the environment of the auditor, and a script written by a model
# from an untrusted paper has no business reading them.
SCRIPT_ENVIRONMENT = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
                      "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "NUMBER_OF_PROCESSORS",
                      "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL", "OMP_NUM_THREADS", "MPLBACKEND")


def script_environment() -> dict[str, str]:
    env = {name: os.environ[name] for name in SCRIPT_ENVIRONMENT if name in os.environ}
    return {**env, "AUDIT_DATA_DIR": data_dir, "PYTHONIOENCODING": "utf-8", "MPLBACKEND": "Agg"}


def execute(script: Path, params: dict) -> Run:
    # Each run happens in a fresh folder outside the project, so a script cannot reach the project's
    # files (.env among them) by a relative path. It sees its own copy and its parameters, nothing else.
    with tempfile.TemporaryDirectory(prefix="audit_run_") as folder:
        work = Path(folder)
        shutil.copy(script, work / script.name)
        params_file = work / f"params_{uuid.uuid4().hex[:8]}.json"
        params_file.write_text(json.dumps(params))
        try:
            with _cpu_slots:
                proc = subprocess.run([sys.executable, "-I", "-X", "utf8", str(RUNNER), script.name, params_file.name],
                                      cwd=work, capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=TIMEOUT_S * (DATA_TIME_FACTOR if data_dir else 1),
                                      env=script_environment())
        except subprocess.TimeoutExpired:
            return Run(error=f"Timed out after {TIMEOUT_S} s")
    if proc.returncode:
        # The parameter file and the folder have random names: keep them out of what the models are shown.
        error = proc.stderr[-3000:].replace(params_file.name, "params.json").replace(str(work), ".")
        return Run(error=error or f"Exit code {proc.returncode}")

    line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith("RESULT:")), None)
    if line is None:
        return Run(error="The script reported no result. End it with report(obtained, detail).\n" + proc.stdout[-1500:])
    try:
        result = json.loads(line.removeprefix("RESULT:"))
        obtained = result["obtained"]
    except (ValueError, KeyError, TypeError):
        return Run(error=f"Malformed RESULT line: {line}")
    if isinstance(obtained, list):  # a table computed row by row: compare it as one flat list
        obtained = flatten(obtained)
    values = obtained if isinstance(obtained, list) and obtained else [obtained]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        return Run(error=f"'obtained' must be a finite number, a list of them, or a boolean, got: {obtained!r}")
    return Run(obtained=obtained, detail=str(result.get("detail", "")))
