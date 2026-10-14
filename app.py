"""Local web page for the auditor: give it a paper, watch the audit, read the report.

    python app.py        then open http://127.0.0.1:7860

With DEMO_MODE=1 (for a public demo) the page protects the budget: reports already
made are shown at once and cost nothing, and new papers get the review only, a few
a day, until a reserve of the spending cap is reached.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import gradio as gr
import pymupdf
from dotenv import load_dotenv

from auditor.ingest import ARXIV_ID

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

DEMO = os.getenv("DEMO_MODE", "0") == "1"
NEW_PER_DAY = int(os.getenv("DEMO_NEW_PER_DAY", "6"))         # new papers a day, all visitors together
NEW_PER_SESSION = int(os.getenv("DEMO_NEW_PER_SESSION", "2"))  # new papers per visitor
RESERVE_USD = float(os.getenv("DEMO_RESERVE_USD", "1.0"))      # never spend the last dollars of the cap
MAX_PAGES = int(os.getenv("DEMO_MAX_PAGES", "25"))              # a PDF is transcribed page by page: cost grows with it
USAGE = ROOT / ".demo_usage.json"
MODEL_CALL = re.compile(r"(\w+): (\d+) in / (\d+) out = \$([\d.]+)")  # as auditor.llm logs each call
MODEL_NAMES = {"ultra": "Nemotron 3 Ultra", "super": "Nemotron 3 Super", "nano": "Nemotron 3 Nano",
               "vision": "MiniCPM-V"}
_usage_lock = threading.Lock()

INTRO = """# Paper Reproducibility Auditor

Give it a scientific paper. It reads it as a referee does (are the numbers consistent, what is
unsound or missing, can it be reproduced, how it stands against related work) and then re-implements
and runs the results that can be recomputed, comparing them with what the paper reports. Every
conclusion says how far it can be trusted.

An arXiv id is the better input when the paper has one: the LaTeX source keeps equations and
tables exact. A PDF is transcribed page by page first, which takes longer and can misread a digit.
"""

DEMO_NOTE = f"""**Public demo.** The example reports below open at once. A new paper gets the review (about a
minute); the full re-computation is shown on the examples. New papers are limited to {NEW_PER_DAY} a day
and PDFs to {MAX_PAGES} pages, to keep the demo running for everyone."""


def spent() -> float:
    try:
        return json.loads((ROOT / ".spend.json").read_text())["usd"]
    except (OSError, ValueError, KeyError):
        return 0.0


def examples() -> dict[str, Path]:
    """The papers that already have a report: {label: folder}. The published examples (examples/, part
    of the repository, so a fresh server has them) and whatever this machine has audited (runs/)."""
    found = {}
    for report in sorted((ROOT / "examples").glob("*/report.md")) + sorted((ROOT / "runs").glob("*/report.md")):
        run = report.parent
        try:
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        kind = "full audit" if audit.get("claims") else "review"
        title = " ".join(str(audit.get("title") or run.name).split())[:90]
        found.setdefault(f"{title} ({run.name}, {kind})", run)
    return found


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
        return f"This session has audited {NEW_PER_SESSION} new papers, the most allowed. Open an example instead."
    today = datetime.date.today().isoformat()
    with _usage_lock:
        try:
            usage = json.loads(USAGE.read_text())
        except (OSError, ValueError):
            usage = {}
        if usage.get(today, 0) >= NEW_PER_DAY:
            return f"Today's {NEW_PER_DAY} new papers have been audited. Try again tomorrow, or open an example."
        USAGE.write_text(json.dumps({today: usage.get(today, 0) + 1}))
    return ""


def show(choice):
    """Open a stored report: no model call, nothing spent."""
    return open_folder(examples().get(choice or ""))


def open_folder(run: Path | None):
    if not run or not (run / "report.md").exists():
        return "Choose a report.", "", None
    return f"Stored report of {run.name}.", (run / "report.md").read_text(encoding="utf-8"), \
        [str(run / "report.md"), str(run / "audit.json")]


# Shown first: one example of each thing the auditor does well, with what it found.
FEATURED = [("1706.03762", "Attention Is All You Need"),
            ("2504.00560", "A variational symplectic scheme based on Lobatto's quadrature"),
            ("1412.6980", "Adam: A Method for Stochastic Optimization")]


def featured() -> list[tuple[str, str, Path]]:
    """(title, headline finding, folder) of the featured examples that are available."""
    from auditor.report import key_findings
    shown = []
    for name, title in FEATURED:
        folder = next((f for f in (ROOT / "examples" / name, ROOT / "runs" / name) if (f / "audit.json").exists()), None)
        if not folder:
            continue
        audit = json.loads((folder / "audit.json").read_text(encoding="utf-8"))
        points = [line[2:] for line in key_findings(audit) if line.startswith("- ")]
        shown.append((title, points[0] if points else "", folder))
    return shown


def audit(pdf, arxiv_id, max_claims, data=None, review_only=False, session_count=0):
    """Run the audit as a subprocess, yielding (progress log, report, files to download, session count)."""
    arxiv_id = (arxiv_id or "").strip()
    if arxiv_id and not ARXIV_ID.fullmatch(arxiv_id):
        yield f"'{arxiv_id}' is not an arXiv id. It looks like 2504.00560.", "", None, session_count
        return
    if not arxiv_id and not pdf:
        yield "Upload a PDF or type an arXiv id.", "", None, session_count
        return
    if arxiv_id:
        source, run = arxiv_id, ROOT / "runs" / arxiv_id
    else:
        if DEMO:
            with pymupdf.open(pdf) as document:
                if document.page_count > MAX_PAGES:
                    yield (f"This PDF has {document.page_count} pages; the demo takes up to {MAX_PAGES}.", "", None,
                           session_count)
                    return
        papers = ROOT / "papers"
        papers.mkdir(exist_ok=True)
        target = papers / Path(pdf).name
        if Path(pdf).resolve() != target.resolve():
            shutil.copy(pdf, target)
        source, run = str(target), ROOT / "runs" / target.stem

    if DEMO:
        review_only = True  # the re-computation is the expensive part: it is shown on the examples
    before = next((folder for folder in (run, ROOT / "examples" / run.name) if stored(folder, review_only)), None)
    if DEMO and before:
        # Asked before: the report is the one already made (an audit of the same paper gives the same report).
        yield ("This paper was audited before: here is its report.", (before / "report.md").read_text(encoding="utf-8"),
               [str(before / "report.md"), str(before / "audit.json")], session_count)
        return
    if DEMO:
        refusal = admit(session_count)
        if refusal:
            yield refusal, "", None, session_count
            return
        session_count += 1
        if data:
            data = None  # uploaded files would run the generated scripts on them: not in the public demo

    command = [sys.executable, "-u", "-X", "utf8", "-m", "auditor", source, "--max-claims", str(int(max_claims))]
    if review_only:
        command.append("--review-only")
    if data:
        # Uploads arrive under temporary names: give each file back the name it had, which is
        # how the paper and the scripts will refer to it.
        staging = ROOT / "data" / "_upload" / run.name
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for file in data:
            shutil.copy(file, staging / Path(getattr(file, "orig_name", None) or file).name)
        command += ["--data", str(staging)]
    process = subprocess.Popen(
        command,
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    log = []
    for line in process.stdout:
        call = MODEL_CALL.search(line)
        if call:  # one line per model call, said in words: which model, through what, how much
            role, tokens_in, tokens_out, usd = call.groups()
            line = (f"  {MODEL_NAMES.get(role, role)} via Nebius Token Factory: {int(tokens_in):,} tokens in, "
                    f"{int(tokens_out):,} out (${float(usd):.3f})")
        log.append(line.rstrip())
        yield "\n".join(log[-400:]), "", None, session_count
    process.wait()
    report = run / "report.md"
    if process.returncode or not report.exists():
        yield ("\n".join(log[-400:]) + "\n\nThe audit did not finish. The lines above show where it stopped.", "", None,
               session_count)
        return
    stats = json.loads((run / "stats.json").read_text(encoding="utf-8"))
    log.append(f"\nDone in {stats['seconds']} s. Model calls of this run cost ${sum(stats['cost_usd'].values()):.2f}.")
    yield "\n".join(log[-400:]), report.read_text(encoding="utf-8"), [str(report), str(run / "audit.json")], session_count


# Report tables: a number or a short label is never split across lines ("41." over "0").
CSS = ".prose table td, .prose table th { word-break: normal; overflow-wrap: normal; }"

with gr.Blocks(title="Paper Reproducibility Auditor", css=CSS) as page:
    gr.Markdown(INTRO)
    if DEMO:
        gr.Markdown(DEMO_NOTE)
    session_count = gr.State(0)
    highlights = featured()
    if highlights:
        gr.Markdown("### What it found\nReports made earlier. They open at once; nothing is run.")
    featured_buttons = []
    for title, finding, folder in highlights:
        with gr.Row(equal_height=True):
            gr.Markdown(f"**{title}**  \n{finding}")
            featured_buttons.append((gr.Button("Open report", scale=0, min_width=140), folder))
    with gr.Row():
        choice = gr.Dropdown(choices=list(examples()), label="All example reports")
        open_example = gr.Button("Open this report")
    with gr.Row():
        pdf = gr.File(label="Paper (PDF)", file_types=[".pdf"], type="filepath")
        with gr.Column():
            arxiv_id = gr.Textbox(label="or an arXiv id", placeholder="2504.00560")
            max_claims = gr.Slider(4, 30, value=20, step=1, label="Most claims to audit",
                                   info="Every claim found is audited, up to this many. More claims take longer and cost more.")
            review_only = gr.Checkbox(label="Review only", value=DEMO, interactive=not DEMO,
                                      info="Read the paper as a referee (concerns, checklist, related work, figures) "
                                           "without re-computing its results. About a minute.")
            start = gr.Button("Audit this paper", variant="primary")
    data = gr.File(label="Data the paper's results were computed from (optional): test images, tables, measurements",
                   file_count="multiple", type="filepath", visible=not DEMO)
    if not DEMO:
        gr.Markdown("Without the data, results that depend on it cannot be checked: the method is still rebuilt from "
                    "the paper and run on substitute data, which tests how it behaves, not the numbers the paper "
                    "reports. Keep the file names the paper uses.")
    progress = gr.Textbox(label="Progress", lines=4, max_lines=14, autoscroll=True)
    report = gr.Markdown(label="Audit report")
    files = gr.File(label="Download the report and the full audit data", file_count="multiple")
    open_example.click(show, inputs=[choice], outputs=[progress, report, files])
    for button, folder in featured_buttons:
        button.click(lambda folder=folder: open_folder(folder), outputs=[progress, report, files])
    start.click(audit, inputs=[pdf, arxiv_id, max_claims, data, review_only, session_count],
                outputs=[progress, report, files, session_count])

if __name__ == "__main__":
    # One audit at a time: they share the budget and the machine.
    # PORT is how hosting services (Render) say where to listen
    port = int(os.getenv("PORT") or os.getenv("GRADIO_SERVER_PORT", "7860"))
    page.queue(default_concurrency_limit=1).launch(server_name=os.getenv("HOST", "127.0.0.1"), server_port=port)
