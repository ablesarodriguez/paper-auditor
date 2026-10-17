"""The web page of the auditor: give it a paper, follow the audit, read the report.

    python app.py        then open http://127.0.0.1:7860

A small FastAPI server: it serves the page in web/ and a JSON API the page calls. Audits run
one at a time, in a subprocess, exactly as `python -m auditor` would run them.

With DEMO_MODE=1 (for a public demo) it protects the budget: reports already made are shown
at once and cost nothing, and new papers get the review only, a few a day, until a reserve of
the spending cap is reached.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pymupdf
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from auditor.ingest import ARXIV_ID

ROOT = Path(__file__).parent
WEB = ROOT / "web"
load_dotenv(ROOT / ".env")
for _k in ("TAVILY_API_KEY", "NEBIUS_API_KEY"):
    if _k in os.environ:
        os.environ[_k] = os.environ[_k].strip()

DEMO = os.getenv("DEMO_MODE", "0") == "1"
NEW_PER_DAY = int(os.getenv("DEMO_NEW_PER_DAY", "6"))         # new papers a day, all visitors together
NEW_PER_SESSION = int(os.getenv("DEMO_NEW_PER_SESSION", "2"))  # new papers per visitor
RESERVE_USD = float(os.getenv("DEMO_RESERVE_USD", "1.0"))      # never spend the last dollars of the cap
MAX_PAGES = int(os.getenv("DEMO_MAX_PAGES", "25"))              # a PDF is transcribed page by page: cost grows with it
USAGE = ROOT / ".demo_usage.json"
REPO = "https://github.com/ablesarodriguez/paper-auditor"
MODEL_CALL = re.compile(r"(\w+): (\d+) in / (\d+) out = \$([\d.]+)")  # as auditor.llm logs each call
MODEL_NAMES = {"ultra": "Nemotron 3 Ultra", "super": "Nemotron 3 Super", "nano": "Nemotron 3 Nano",
               "vision": "MiniCPM-V"}
NAME = re.compile(r"[\w.\-]{1,80}")  # a run's name as it appears in a URL

# Shown first: one example of each thing the auditor does well, said for someone who has not read the
# report (each sentence restates the report's own first key finding, in plain words).
FEATURED = [
    ("1706.03762", "Numbers that disagree",
     "The abstract gives 41.8 BLEU for English–French; the results section says 41.0. Found by code, "
     "confirmed by a second model."),
    ("2504.00560", "Results re-run",
     "All eight results re-computed by code written from the paper's equations. Two hold only for a mass "
     "the paper never states."),
    ("1412.6980", "A referee's concern",
     "The convergence theorem assumes a decaying learning rate and momentum; the algorithm as written "
     "uses constants."),
]

_usage_lock = threading.Lock()
_audit_lock = threading.Lock()   # one audit at a time: they share the budget and the machine
_sessions: dict[str, int] = {}   # new papers audited per visitor
_jobs: dict[str, dict] = {}


# ---------------------------------------------------------------- reports

def spent() -> float:
    try:
        return json.loads((ROOT / ".spend.json").read_text())["usd"]
    except (OSError, ValueError, KeyError):
        return 0.0


def folder_of(name: str) -> Path | None:
    """Where a report is: the published examples first, then what this machine has audited."""
    if not NAME.fullmatch(name):
        return None
    return next((f for f in (ROOT / "examples" / name, ROOT / "runs" / name) if (f / "report.md").exists()), None)


SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "via", "with"}


def headline(title: str) -> str:
    """The title on one line; one printed in capitals (as some journals do) in title case."""
    words = title.split()
    if sum(c.isupper() for c in title) <= 0.8 * sum(c.isalpha() for c in title):
        return " ".join(words)
    return " ".join(w.lower() if i and w.lower() in SMALL_WORDS else w.capitalize()
                    for i, w in enumerate(words))


def summary(folder: Path) -> dict | None:
    try:
        audit = json.loads((folder / "audit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    reading = audit.get("review") or {}
    checks = reading.get("consistency") or []
    return {"name": folder.name, "title": headline(str(audit.get("title") or folder.name)),
            "kind": "Full audit" if audit.get("claims") else "Review",
            "year": reading.get("year"),
            "concerns": len(reading.get("concerns") or []),
            "checks": len(checks), "mismatches": sum(not c["consistent"] for c in checks),
            "claims": len(audit.get("claims") or []),
            "reproduced": sum(c.get("verdict") in ("verified", "verified_under_assumption")
                              for c in audit.get("claims") or [])}


def all_reports() -> list[dict]:
    seen, out = set(), []
    for report in sorted((ROOT / "examples").glob("*/report.md")) + sorted((ROOT / "runs").glob("*/report.md")):
        if report.parent.name in seen or report.parent.name.startswith("_"):
            continue
        info = summary(report.parent)
        if info:
            seen.add(report.parent.name)
            out.append(info)
    return out


def stored(run: Path, review_only: bool) -> bool:
    """Whether the run folder already holds the report asked for."""
    try:
        audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (run / "report.md").exists() and (review_only or bool(audit.get("claims")))


def admit(session_count: int) -> str:
    """Why a new audit cannot start now in the demo, or '' if it can. Counts it when admitted."""
    cap = float(os.getenv("SPEND_CAP_USD", "35"))
    if spent() >= cap - RESERVE_USD:
        return "The demo's budget for new papers is used up. The example reports are still available."
    if session_count >= NEW_PER_SESSION:
        return f"You have audited {NEW_PER_SESSION} new papers, the most this demo allows per visitor."
    today = datetime.date.today().isoformat()
    with _usage_lock:
        try:
            usage = json.loads(USAGE.read_text())
        except (OSError, ValueError):
            usage = {}
        if usage.get(today, 0) >= NEW_PER_DAY:
            return f"Today's {NEW_PER_DAY} new papers have been audited. Try again tomorrow, or read a report."
        USAGE.write_text(json.dumps({today: usage.get(today, 0) + 1}))
    return ""


# ---------------------------------------------------------------- audits

TOKEN_PATTERNS = [
    re.compile(r"tvly-[A-Za-z0-9_\-]+"),
    re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]+)", re.IGNORECASE),
]
TRACEBACK_INDICATORS = (
    "Traceback (most recent call last)",
    'File "<',
    'File "/',
    'File "C:\\',
    "requests.exceptions",
    "urllib3.exceptions",
    "openai.",
    "tavily.",
    "InvalidHeader",
    "HTTPError",
    "ConnectionError",
    "TimeoutError",
)


def redact_secrets(text: str) -> str:
    """Scrub known API keys and token patterns from log output."""
    for key, val in os.environ.items():
        if any(term in key.upper() for term in ("KEY", "SECRET", "TOKEN", "AUTH", "PASS")) and len(val) >= 4:
            text = text.replace(val, "[REDACTED]")
    for pattern in TOKEN_PATTERNS:
        text = pattern.sub(lambda m: "Bearer [REDACTED]" if m.group(0).lower().startswith("bearer") else "[REDACTED]", text)
    return text


def is_traceback_line(line: str) -> bool:
    """Check if a line looks like an internal stack trace or exception dump."""
    stripped = line.strip()
    return any(indicator in stripped for indicator in TRACEBACK_INDICATORS)


def readable(line: str) -> str:
    """A line of the auditor's log as the page shows it: a model call says which model, through what, at what cost."""
    call = MODEL_CALL.search(line)
    if call:
        role, tokens_in, tokens_out, usd = call.groups()
        return (f"{MODEL_NAMES.get(role, role)} via Nebius Token Factory · {int(tokens_in):,} tokens in, "
                f"{int(tokens_out):,} out · ${float(usd):.3f}")
    return line.rstrip()


def run_audit(job: dict, command: list[str]) -> None:
    if _audit_lock.locked():
        job["log"].append("Waiting for the audit before this one to finish…")
    with _audit_lock:
        job["started"] = time.time()
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )

        stderr_lines = []

        def capture_stderr():
            for err_line in process.stderr:
                stderr_lines.append(err_line)

        err_thread = threading.Thread(target=capture_stderr, daemon=True)
        err_thread.start()

        for line in process.stdout:
            clean = line.strip()
            if clean and not is_traceback_line(clean):
                sanitized = redact_secrets(readable(clean))
                job["log"].append(sanitized)

        process.wait()
        err_thread.join(timeout=2)

        if stderr_lines:
            # Stderr is printed only to server console (Render dashboard logs), never exposed to web UI
            sys.stderr.write(f"[Audit {job['name']} stderr]:\n" + redact_secrets("".join(stderr_lines)) + "\n")
            sys.stderr.flush()

    run = ROOT / "runs" / job["name"]
    job["ok"] = process.returncode == 0 and (run / "report.md").exists()
    if job["ok"]:
        stats = json.loads((run / "stats.json").read_text(encoding="utf-8"))
        job["log"].append(f"Done in {stats['seconds']} s. Model calls cost ${sum(stats['cost_usd'].values()):.2f}.")
    else:
        job["error"] = "The audit did not finish. An error occurred while processing the paper."
    job["done"] = True


app = FastAPI(title="Paper Auditor", docs_url=None, redoc_url=None)


def session(request: Request, response: Response) -> str:
    sid = request.cookies.get("sid") or uuid.uuid4().hex
    response.set_cookie("sid", sid, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return sid


@app.get("/api/config")
def config() -> dict:
    return {"demo": DEMO, "per_day": NEW_PER_DAY, "max_pages": MAX_PAGES, "repo": REPO}


@app.get("/api/reports")
def reports() -> dict:
    listing = all_reports()
    by_name = {r["name"]: r for r in listing}
    featured = [{**by_name[name], "tag": tag, "sentence": sentence} for name, tag, sentence in FEATURED
                if name in by_name]
    return {"featured": featured, "all": listing}


@app.get("/api/reports/{name}")
def report(name: str) -> dict:
    folder = folder_of(name)
    if not folder:
        raise HTTPException(404, "No report by that name.")
    return {**(summary(folder) or {"name": name, "title": name}),
            "markdown": (folder / "report.md").read_text(encoding="utf-8")}


@app.get("/api/reports/{name}/files/{file}")
def report_file(name: str, file: str):
    folder = folder_of(name)
    if not folder or file not in ("report.md", "audit.json"):
        raise HTTPException(404)
    return FileResponse(folder / file, filename=f"{name}-{file}")


@app.post("/api/audit")
def start_audit(request: Request, response: Response, arxiv_id: str = Form(""), review_only: bool = Form(True),
                max_claims: int = Form(20), pdf: UploadFile | None = File(None)) -> dict:
    sid = session(request, response)
    arxiv_id = arxiv_id.strip()
    if arxiv_id and not ARXIV_ID.fullmatch(arxiv_id):
        raise HTTPException(400, f"“{arxiv_id}” is not an arXiv identifier. One looks like 1706.03762.")
    if not arxiv_id and not (pdf and pdf.filename):
        raise HTTPException(400, "Type an arXiv identifier or choose a PDF.")
    if arxiv_id:
        source, name = arxiv_id, arxiv_id
    else:
        stem = re.sub(r"[^\w.\-]", "_", Path(pdf.filename).stem)[:60] or "paper"
        papers = ROOT / "papers"
        papers.mkdir(exist_ok=True)
        target = papers / f"{stem}.pdf"
        with target.open("wb") as out:
            shutil.copyfileobj(pdf.file, out)
        if DEMO:
            with pymupdf.open(target) as document:
                if document.page_count > MAX_PAGES:
                    raise HTTPException(400, f"This PDF has {document.page_count} pages; the demo takes up to {MAX_PAGES}.")
        source, name = str(target), stem
    if DEMO:
        review_only = True  # the re-computation is the expensive part: it is shown on the examples
        before = next((f for f in (ROOT / "runs" / name, ROOT / "examples" / name) if stored(f, True)), None)
        if before:  # audited before: an audit of the same paper gives the same report
            return {"report": name}
        refusal = admit(_sessions.get(sid, 0))
        if refusal:
            raise HTTPException(429, refusal)
        _sessions[sid] = _sessions.get(sid, 0) + 1
    command = [sys.executable, "-u", "-X", "utf8", "-m", "auditor", source,
               "--max-claims", str(max(1, min(int(max_claims), 30)))]
    if review_only:
        command.append("--review-only")
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = job = {"id": job_id, "name": name, "source": arxiv_id or Path(source).name, "log": [],
                           "done": False, "ok": False, "error": "", "created": time.time(), "started": None}
    threading.Thread(target=run_audit, args=(job, command), daemon=True).start()
    return {"job": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, since: int = 0) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No such audit (the server may have restarted).")
    elapsed = time.time() - (job["started"] or job["created"])
    return {"name": job["name"], "source": job["source"], "log": job["log"][since:], "total": len(job["log"]),
            "done": job["done"], "ok": job["ok"], "error": job["error"], "elapsed": round(elapsed)}


@app.exception_handler(HTTPException)
def http_error(request: Request, error: HTTPException):
    return JSONResponse({"error": error.detail}, status_code=error.status_code)


# ---------------------------------------------------------------- pages

@app.get("/")
def home():
    return FileResponse(WEB / "index.html")


@app.get("/report/{name}")
def report_page(name: str):
    return FileResponse(WEB / "report.html")


@app.get("/audit/{job_id}")
def audit_page(job_id: str):
    return FileResponse(WEB / "audit.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")


if __name__ == "__main__":
    # PORT is how hosting services (Render) say where to listen
    port = int(os.getenv("PORT") or os.getenv("GRADIO_SERVER_PORT", "7860"))
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=port, log_level="warning")
