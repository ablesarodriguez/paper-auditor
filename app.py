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

REPO = "https://github.com/ablesarodriguez/paper-auditor"

HERO = f"""
<div class="hero">
  <div class="hero-kicker">Nebius × NVIDIA Global AI Hackathon</div>
  <h1>Paper Reproducibility Auditor</h1>
  <p class="hero-lead">An AI referee for scientific papers. Give it an arXiv id or a PDF: it checks that the
  numbers agree, challenges its own criticism, and re-runs the results that can be recomputed.</p>
  <div class="pills">
    <span>✓ Checks the numbers</span><span>✓ Every criticism quotes the paper</span>
    <span>✓ Re-runs the results</span>
  </div>
  <div class="hero-tech">NVIDIA Nemotron 3 · MiniCPM-V · Tavily · on Nebius Token Factory ·
  <a href="{REPO}" target="_blank">Code on GitHub (MIT)</a></div>
</div>
"""

DEMO_NOTE = (f"<div class='note'><b>Public demo.</b> The example reports open at once and cost nothing. A new "
             f"paper gets the review (about a minute); the full re-computation is shown on the examples. New "
             f"papers are limited to {NEW_PER_DAY} a day and PDFs to {MAX_PAGES} pages, so the demo keeps "
             f"running for everyone.</div>")

HOW = """
### Models propose, code checks

| Step | What happens | Done by |
| --- | --- | --- |
| Read | The LaTeX source from arXiv, or the PDF transcribed page by page; figures described from their images | MiniCPM-V |
| Review | Summary, strengths, concerns, reproducibility checklist, questions. Every concern must quote the paper | Nemotron 3 Ultra |
| Challenge | Each concern is argued against; it stays only if no passage answers it and a second model agrees | Ultra, then Super |
| Check the numbers | Averages and totals in tables, percentages and their counts, the abstract's numbers against the body | Code |
| Related work | Web search for the closest papers, and whether the paper cites them | Tavily + Ultra |
| Re-run the results | Scripts written from the paper's equations, run, and compared with its tables | Nemotron 3 Super / Ultra |
| Verdicts | Tolerances, sensitivity to missing details, confidence: fixed rules, never a model's opinion | Code |

Every model call goes, in real time, to **Nebius Token Factory**.

### Does it work?

Errors were planted in copies of eleven real papers: 133 planted, **132 caught**. On the unmodified papers
the only two flags are real problems of those papers (an abstract result printed differently in the body, and
abstract figures read only off a plot). The full evaluation and its limits are in the repository.
"""


def finding_html(text: str) -> str:
    """A key finding (markdown with **bold**) as safe HTML for a card."""
    import html as markup
    safe = markup.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe).replace("`", "")


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


# Shown first: one example of each thing the auditor does well, said for someone who has not read the
# report (each sentence restates the report's own first key finding, in plain words).
FEATURED = [
    ("1706.03762", "Attention Is All You Need", "Numbers that disagree",
     "The abstract gives 41.8 BLEU for English–French; the results section says 41.0. Found by code, "
     "confirmed by a second model."),
    ("2504.00560", "A variational symplectic scheme based on Lobatto's quadrature", "Results re-run",
     "All 8 results re-computed by code written from the paper's equations. Two hold only for a mass the "
     "paper never states."),
    ("1412.6980", "Adam: A Method for Stochastic Optimization", "A referee's concern",
     "The convergence theorem assumes a decaying learning rate and momentum; the algorithm as written uses "
     "constants."),
]


def featured() -> list[tuple[str, str, str, Path]]:
    """(title, tag, sentence, folder) of the featured examples that are available."""
    shown = []
    for name, title, tag, sentence in FEATURED:
        folder = next((f for f in (ROOT / "examples" / name, ROOT / "runs" / name) if (f / "audit.json").exists()), None)
        if folder:
            shown.append((title, tag, sentence, folder))
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


THEME = gr.themes.Soft(primary_hue="orange", secondary_hue="slate", neutral_hue="slate",
                       font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
                       font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "monospace"]).set(
    body_background_fill="#f1f5f9", block_radius="14px", button_large_radius="10px")

CSS = """
.gradio-container { max-width: 1180px !important; margin: 0 auto !important; }
.hero { background: radial-gradient(circle at 15% 20%, #1e3a8a 0%, #0f172a 55%); color: #fff; border-radius: 18px;
        padding: 40px 44px 34px; border-left: 8px solid #f97316; }
.hero h1 { color: #fff; font-size: 2.6rem; font-weight: 800; margin: 6px 0 10px; letter-spacing: -0.02em; }
.hero-kicker { color: #fdba74; font-size: .85rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }
.hero-lead { color: #e2e8f0; font-size: 1.15rem; max-width: 820px; line-height: 1.6; margin: 0 0 18px; }
.pills { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
.pills span { background: rgba(249,115,22,.15); color: #fed7aa; border: 1px solid rgba(249,115,22,.5);
              padding: 6px 14px; border-radius: 999px; font-weight: 600; font-size: .92rem; }
.hero-tech { color: #94a3b8; font-size: .9rem; } .hero-tech a { color: #fdba74; }
.note { background: #fff7ed; border: 1px solid #fed7aa; color: #7c2d12; padding: 12px 16px; border-radius: 12px; }
.card { background: #fff !important; border: 1px solid #e2e8f0 !important; border-radius: 16px !important;
        padding: 22px !important; box-shadow: 0 1px 3px rgba(15,23,42,.06); border-top: 5px solid #f97316 !important;
        justify-content: space-between; }
.card button { margin-top: auto; }
.card .tag { color: #f97316; font-size: .78rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
.card h3 { margin: 6px 0 10px; font-size: 1.15rem; line-height: 1.35; color: #0f172a; }
.card p { color: #334155; font-size: .95rem; line-height: 1.55; }
.report-box { background: #fff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 8px 34px 26px;
              box-shadow: 0 1px 3px rgba(15,23,42,.06); }
.report-box h1 { font-size: 1.9rem; border-bottom: 3px solid #f97316; padding-bottom: 10px; }
.report-box h2 { margin-top: 1.8em; color: #0f172a; }
.report-box table { font-size: .9rem; border-collapse: collapse; width: 100%; }
.report-box th { background: #f1f5f9; }
.report-box tr:nth-child(even) td { background: #f8fafc; }
.report-box td, .report-box th { word-break: normal; overflow-wrap: normal; padding: 8px 10px; }
.report-box blockquote { border-left: 4px solid #f97316; background: #fff7ed; padding: 8px 14px; color: #431407; }
.report-box details { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 8px 12px; margin: 10px 0; }
.report-box summary { cursor: pointer; font-weight: 600; color: #c2410c; }
.empty-report { color: #64748b; text-align: center; padding: 40px 0; }
footer { display: none !important; }
"""

# after a report opens, bring it into view
TO_REPORT = "() => { setTimeout(() => document.getElementById('report')?.scrollIntoView({behavior: 'smooth'}), 400); }"

with gr.Blocks(title="Paper Reproducibility Auditor") as page:
    gr.HTML(HERO)
    if DEMO:
        gr.HTML(DEMO_NOTE)
    session_count = gr.State(0)
    featured_buttons = []
    with gr.Tabs():
        with gr.Tab("Examples"):
            gr.Markdown("### What it found\nReports made earlier on well-known papers. They open at once; nothing is run.")
            with gr.Row(equal_height=True):
                for title, tag, sentence, folder in featured():
                    with gr.Column(elem_classes="card"):
                        gr.HTML(f"<div class='tag'>{tag}</div><h3>{title}</h3><p>{finding_html(sentence)}</p>")
                        featured_buttons.append((gr.Button("Open report", variant="primary", size="md"), folder))
            with gr.Row():
                choice = gr.Dropdown(choices=list(examples()), value=None, label="All example reports", scale=4)
                open_example = gr.Button("Open this report", scale=1)
        with gr.Tab("Audit a paper"):
            with gr.Row():
                with gr.Column(scale=3):
                    arxiv_id = gr.Textbox(label="arXiv id", placeholder="e.g. 1706.03762",
                                          info="The better input: the LaTeX source keeps equations and tables exact.")
                    pdf = gr.File(label="or a PDF", file_types=[".pdf"], type="filepath", height=140)
                    review_only = gr.Checkbox(label="Review only", value=DEMO, interactive=not DEMO,
                                              info="The referee's reading (concerns, number checks, checklist, related "
                                                   "work, figures) without re-computing results. About a minute.")
                    with gr.Accordion("Options", open=False, visible=not DEMO):
                        max_claims = gr.Slider(4, 30, value=20, step=1, label="Most claims to re-compute",
                                               info="More claims take longer and cost more.")
                        data = gr.File(label="The paper's data (optional): test images, tables, measurements",
                                       file_count="multiple", type="filepath")
                        gr.Markdown("Without the data, results that depend on it cannot be checked: the method is "
                                    "rebuilt and run on substitute data. Keep the file names the paper uses.")
                    start = gr.Button("Audit this paper", variant="primary", size="lg")
                with gr.Column(scale=2):
                    gr.Markdown("#### What you get\n"
                                "- **Key findings** first: what disagrees, what is unsupported, what was reproduced\n"
                                "- **Number checks** done by code, never by a model\n"
                                "- **Concerns**, each quoting the paper, and those withdrawn after a challenge\n"
                                "- **Reproducibility checklist** and questions for the authors\n"
                                "- **Related work** found on the web, cited or not\n"
                                "- For computational papers: the **scripts** that re-ran the results")
        with gr.Tab("How it works"):
            gr.Markdown(HOW)
    progress = gr.Textbox(label="Progress", lines=3, max_lines=12, autoscroll=True,
                          placeholder="Open an example or audit a paper: what happens shows up here.")
    with gr.Column(elem_id="report", elem_classes="report-box"):
        report = gr.Markdown("<div class='empty-report'>The report will appear here.</div>")
        with gr.Accordion("Download the report and the full audit data", open=False):
            files = gr.File(show_label=False, file_count="multiple", height=90)
    open_example.click(show, inputs=[choice], outputs=[progress, report, files], js=TO_REPORT)
    for button, folder in featured_buttons:
        button.click(lambda folder=folder: open_folder(folder), outputs=[progress, report, files], js=TO_REPORT)
    start.click(audit, inputs=[pdf, arxiv_id, max_claims, data, review_only, session_count],
                outputs=[progress, report, files, session_count], js=TO_REPORT)

if __name__ == "__main__":
    # One audit at a time: they share the budget and the machine.
    # PORT is how hosting services (Render) say where to listen
    port = int(os.getenv("PORT") or os.getenv("GRADIO_SERVER_PORT", "7860"))
    page.queue(default_concurrency_limit=1).launch(server_name=os.getenv("HOST", "127.0.0.1"), server_port=port,
                                                   theme=THEME, css=CSS)
