"""Stage 1 - Ingest: paper to text, keeping the equations intact.

In order of fidelity:
- "arxiv-latex": the LaTeX source of an arXiv paper. Equations are exact.
- "pdf-text+vision": a PDF with a text layer. The text layer alone flattens
  fractions and exponents (7/15 h^2 becomes "715 h2"), so a vision model
  rewrites each region from its image, with the text layer as the reference
  for exact wording and digits.
- "pdf-scan": a scanned PDF. The vision model transcribes each region from
  the image alone.

Pages are cut into overlapping horizontal tiles because the vision model
downsamples every image to a fixed budget: a full page leaves dense tables
below its resolution.
"""

import base64
import gzip
import io
import re
import tarfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import openai
import pymupdf

from .llm import NO_THINKING, complete
from .memo import recall

ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}(v\d+)?")
MIN_CHARS_PER_PAGE = 200
# Measured on a scanned two-column page: with 3 strips a "+" in an equation was read
# as "-" every time; with 4 or 6 strips it was read correctly every time.
TILES_PER_PAGE = 5
VISION_TIMEOUT_S = 120
TILE_OVERLAP = 0.03  # of the page height, so that no line is cut in every tile
TILE_DPI = 200
PARALLEL_CALLS = 6
STRIP_MAX_TOKENS = 2500  # a fifth of a dense page is about 900 tokens

# Kept short on purpose: longer instructions push the vision model into a long
# reasoning preamble that uses up its whole output.
TRANSCRIBE_PROMPT = ("Transcribe all the text in this image exactly, every column. Write equations in LaTeX. "
                     "Write tables as plain text rows, copying every number and minus sign. "
                     "Output only the transcription.")

TEXT_LAYER_HINT = ("\n\nFor reference, this is the raw text extracted from the same region. Its words and digits "
                   "are exact, but fractions, exponents and subscripts are flattened:\n\n{text}")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "paper-reproducibility-auditor"})
    return urllib.request.urlopen(request, timeout=60).read()


def arxiv_latex(arxiv_id: str) -> str | None:
    """Return the LaTeX source of an arXiv paper as one string, or None if it has none."""
    try:
        data = fetch(f"https://arxiv.org/e-print/{arxiv_id}")
    except urllib.error.URLError:
        return None
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:  # read in memory, nothing is extracted to disk
            files = {m.name: tar.extractfile(m).read().decode("utf-8", "replace")
                     for m in tar if m.isfile() and m.name.endswith(".tex")}
    except tarfile.ReadError:
        try:  # a single-file submission is a bare gzipped .tex
            files = {"main.tex": gzip.decompress(data).decode("utf-8", "replace")}
        except OSError:
            return None  # PDF-only submission

    mains = [text for text in files.values() if "\\documentclass" in text]
    if not mains:
        return None

    def inline(match: re.Match) -> str:
        name = match.group(1).strip()
        return files.get(name) or files.get(name + ".tex") or ""

    text = re.sub(r"(?<!\\)%.*", "", max(mains, key=len))
    for _ in range(5):  # nested \input
        text = re.sub(r"\\(?:input|include)\{([^}]+)\}", inline, text)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"(?<!\\)%.*", "", text))


def printed(latex: str) -> str:
    """The part of a LaTeX source that is printed: what follows \\end{document} is leftovers of earlier drafts."""
    end = latex.find("\\end{document}")
    return latex if end < 0 else latex[:end + len("\\end{document}")]


TABULAR = re.compile(r"\\begin\{(tabular\*?|tabularx|longtable)\}(.*?)\\end\{\1\}", re.DOTALL)
RULES = re.compile(r"\\(?:toprule|midrule|bottomrule|hline)\b|\\cmidrule(?:\([^)]*\))?\{[^}]*\}|\\cline\{[^}]*\}")
WRAPPERS = re.compile(r"\\(?:text|textbf|textit|mathrm|num|mbox)\{([^{}]*)\}|\\multicolumn\{[^{}]*\}\{[^{}]*\}\{([^{}]*)\}")


def tidy_tables(latex: str) -> str:
    """Rewrite each LaTeX table with one row per line and cells separated by "|".

    Authors' sources spread a table over a hundred lines, one cell per line with
    runs of blank lines where rows were commented out. Read like that, a model
    loses track of which row and which table a number belongs to.
    """
    def skip_arguments(body: str) -> str:
        # drop the column specification: optional [pos], then one or two {...} groups
        i, groups = 0, 0
        while groups < 2:
            j = len(body) - len(body[i:].lstrip())
            if j < len(body) and body[j] == "[":
                i = body.index("]", j) + 1
                continue
            if j >= len(body) or body[j] != "{":
                break
            depth = 0
            for k in range(j, len(body)):
                depth += (body[k] == "{") - (body[k] == "}")
                if depth == 0:
                    i, groups = k + 1, groups + 1
                    break
            else:
                break
            if groups == 1 and not re.match(r"\s*\{", body[i:]):
                break
        return body[i:]

    def clean(cell: str) -> str:
        for _ in range(3):
            cell = WRAPPERS.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), cell)
        return " ".join(cell.split())

    tables = 0

    def render(match: re.Match) -> str:
        nonlocal tables
        tables += 1
        body = RULES.sub(" ", skip_arguments(match.group(2)))
        rows = []
        for row in re.split(r"\\\\(?:\[[^\]]*\])?", body):
            cells = [clean(c) for c in re.split(r"(?<!\\)&", row)]
            if any(cells):
                # Each row gets a tag, so that a claim can point at it instead of retyping its numbers.
                rows.append(f"[T{tables}.R{len(rows) + 1}] | " + " | ".join(cells) + " |")
        return "\\begin{tabular}\n" + "\n".join(rows) + "\n\\end{tabular}"

    return TABULAR.sub(render, latex)


TAGGED_ROW = re.compile(r"(?m)^\[(T\d+)\.R(\d+)\] \| (.*) \|$")


def braced(text: str, command: str) -> str:
    """The argument of the first \\command{...} in text, braces balanced, or ''."""
    start = text.find("\\" + command + "{")
    if start < 0:
        return ""
    depth, begin = 0, start + len(command) + 2
    for i in range(begin - 1, len(text)):
        depth += (text[i] == "{") - (text[i] == "}")
        if depth == 0:
            return " ".join(text[begin:i].split())
    return ""


def table_rows(paper: str) -> dict[str, dict]:
    """The tagged table rows of a paper, each with what identifies its table.

    {"T1.R2": {"cells": [...], "header": [...], "caption": "...", "cited": "..."}}
    "cited" is the paragraph of the paper that refers to the table: that is
    where authors say which experiment the table reports and how it was set up.
    """
    rows, tables = {}, {}
    for match in TAGGED_ROW.finditer(paper):
        table, number, cells = match.groups()
        cells = [c.strip() for c in cells.split(" | ")]
        if table not in tables:
            # the table environment around this tabular holds its caption and label
            begin = paper.rfind("\\begin{table", 0, match.start())
            end = paper.find("\\end{table", match.start())
            env = paper[begin if begin >= 0 else max(0, match.start() - 1500): end if end >= 0 else match.start() + 3000]
            label, cited = braced(env, "label"), ""
            at = paper.find("\\ref{" + label + "}") if label else -1
            if at >= 0:
                start = max(paper.rfind("\n\n", 0, at), at - 900)
                stop = paper.find("\n\n", at)
                cited = " ".join(paper[start: stop if 0 <= stop <= at + 700 else at + 700].split())
            tables[table] = {"header": cells, "caption": braced(env, "caption"), "label": label, "cited": cited}
        rows[f"{table}.R{number}"] = {"cells": cells, **tables[table]}
    return rows


def tiles(page: pymupdf.Page) -> list[pymupdf.Rect]:
    r, step, overlap = page.rect, page.rect.height / TILES_PER_PAGE, page.rect.height * TILE_OVERLAP
    return [pymupdf.Rect(r.x0, max(r.y0, r.y0 + i * step - overlap), r.x1, min(r.y1, r.y0 + (i + 1) * step + overlap))
            for i in range(TILES_PER_PAGE)]


def transcribe(png: bytes, text_layer: str) -> str:
    prompt = TRANSCRIBE_PROMPT + (TEXT_LAYER_HINT.format(text=text_layer) if text_layer else "")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
    ]}]
    # A truncated reply means the model looped or reasoned at length: sample once more.
    text = ""
    for seed in range(3):
        try:
            text, truncated = complete("vision", messages, max_tokens=STRIP_MAX_TOKENS, temperature=0.3, seed=seed,
                                       extra_body=NO_THINKING, timeout=VISION_TIMEOUT_S)
        except openai.APIError:  # a stalled or failed call: try again with another seed
            continue
        if not truncated:
            break
    text = re.sub(r"(?m)^(.+\n)\1{2,}", r"\1", text)  # keep one copy of a line repeated in a loop
    return flatten_tables(text)


def flatten_tables(text: str) -> str:
    """The vision model writes tables as HTML whatever it is told: turn them into one row per line."""
    text = re.sub(r"\s*</t[dh]>\s*<t[dh][^>]*>\s*", " ", text)
    text = re.sub(r"\s*<table[^>]*>\s*", "\n", text)
    text = re.sub(r"\s*(?:<(?:thead|tbody|tr|td|th)[^>]*>|</(?:thead|tbody|td|th)>)\s*", "", text)
    text = re.sub(r"\s*</tr>\s*", "\n", text)
    return re.sub(r"\s*</table>\s*", "\n\n", text).replace("−", "-")


def pdf_to_text(pdf: Path) -> tuple[str, str]:
    doc = pymupdf.open(pdf)
    has_text = sum(len(page.get_text()) for page in doc) >= MIN_CHARS_PER_PAGE * len(doc)
    jobs = [(f"page {n}, part {i}/{TILES_PER_PAGE}", page.get_pixmap(dpi=TILE_DPI, clip=rect).tobytes("png"),
             page.get_text(clip=rect).strip() if has_text else "")
            for n, page in enumerate(doc, 1) for i, rect in enumerate(tiles(page), 1)]
    # A strip with no text layer of its own (a margin, a figure) has nothing to transcribe.
    if has_text:
        jobs = [job for job in jobs if job[2]]

    print(f"  transcribing {len(jobs)} page strips with the vision model")
    with ThreadPoolExecutor(PARALLEL_CALLS) as pool:
        texts = list(pool.map(lambda job: transcribe(job[1], job[2]), jobs))
    text = "\n\n".join(f"--- {label} ---\n{t}" for (label, _, _), t in zip(jobs, texts))
    return text, "pdf-text+vision" if has_text else "pdf-scan"


CAPTION_WORD = re.compile(r"^\s*(?:Table|TABLE|Tabla|TABLA|Taula|TAULA|Tableau|Tabelle)\s*[\dIVX]+", re.MULTILINE)


def pdf_tables(pdf: Path) -> dict[str, dict]:
    """The tables of a PDF with a text layer, read by PyMuPDF (no model), in the shape of table_rows():
    {"T1.R2": {"cells", "header", "caption", "label", "cited"}}. A scan has none.

    Figures drawn as vectors are sometimes taken for tables: only grids with at least two rows of two or
    more numbers are kept.
    """
    def number(cell) -> bool:
        return bool(re.fullmatch(r"[-−]?\d+(?:[.,]\d+)?%?", " ".join(str(cell or "").split())))

    rows, count = {}, 0
    with pymupdf.open(pdf) as doc:
        for page in doc:
            blocks = page.get_text("blocks")
            for table in page.find_tables().tables:
                grid = [[" ".join(str(c or "").split()) for c in row] for row in table.extract()]
                if sum(sum(number(c) for c in row) >= 2 for row in grid) < 2 or any(len(c) > 60 for row in grid for c in row):
                    continue
                count += 1
                top = table.bbox[1]
                # the caption is the nearest block starting with "Table n", above the table or just below it
                captions = [(abs(b[1] - top), b[4]) for b in blocks if CAPTION_WORD.match(b[4])]
                caption = " ".join(min(captions)[1].split()) if captions else ""
                for i, cells in enumerate(grid, 1):
                    rows[f"T{count}.R{i}"] = {"cells": cells, "header": grid[0], "caption": caption[:300],
                                              "label": "", "cited": ""}
    return rows


MIN_SOURCE = 3000  # characters: shorter than this, a LaTeX source is a wrapper, not a paper


def ingest(source: str) -> tuple[str, str]:
    """Return (text, method) for a PDF path or an arXiv id."""
    if not ARXIV_ID.fullmatch(source):
        return pdf_to_text(Path(source))
    latex = recall("arxiv", {"id": source}, lambda: arxiv_latex(source))  # a new arXiv version must not change an audit
    # Some submissions are a few lines of LaTeX wrapped around a PDF: that is not the paper's source.
    if latex and len(latex) >= MIN_SOURCE and "\\includepdf" not in latex:
        return tidy_tables(printed(latex)), "arxiv-latex"
    print("  no LaTeX source on arXiv, falling back to the PDF")
    pdf = Path("papers") / f"arxiv_{source}.pdf"
    pdf.parent.mkdir(exist_ok=True)
    pdf.write_bytes(fetch(f"https://arxiv.org/pdf/{source}"))
    return pdf_to_text(pdf)
