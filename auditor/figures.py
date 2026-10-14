"""Reading the figures of a paper.

A text-only reading of a paper skips its figures: an architecture diagram or a
plot of results reaches the models as a caption and nothing else. Here each
figure is cut out of the PDF and described by a vision model, and the
descriptions are appended to the paper's text for every later stage.

A description is a reading aid, not a measurement: the vision model names what
a figure shows and the labels it can read, and is not reliable on values read
off a curve. The text says so wherever a description is used.
"""

import base64
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import openai
import pymupdf

from .llm import NO_THINKING, SpendCapReached, complete

CAPTION_START = re.compile(r"^\s*(?:Fig\.?|Figure|Figura|FIG\.?|Abbildung)\s*(\d+)\s*[.:]", re.IGNORECASE)
CAPTION_LIKE = re.compile(r"^\s*(?:Fig\.?|Figure|Figura|Abbildung|Table|Tabla|Taula|Tableau|Tabelle)\s*\d+\s*[.:]", re.IGNORECASE)
MAX_FIGURES = 24
ABOVE = 0.6      # of the page height: how far above its caption a figure is looked for, at most
LABELS = 700     # characters of a figure's own text handed to the vision model
PARAGRAPH = 200  # characters: a block of text this long is running text, not a label inside a figure

# Short on purpose: a long instruction sends this vision model into a reasoning preamble.
PROMPT = ("This is a figure from a scientific paper. Describe it for a reader who cannot see it: what kind of figure it "
          "is, what its axes, blocks or panels show, the labels and values that can be read, and the main trend or "
          "structure. State only what is visible; do not guess numbers.")


def locate(pdf: Path, paper: str) -> dict[int, tuple[int, pymupdf.Rect | None]]:
    """Where each figure is: {number: (page index, region to cut out or None for the whole page)}."""
    doc = pymupdf.open(pdf)
    found = {}
    for index, page in enumerate(doc):
        width, height = page.rect.width, page.rect.height
        blocks = [b for b in page.get_text("blocks") if b[6] == 0]
        for x0, y0, x1, y1, text, *_ in blocks:
            match = CAPTION_START.match(text)
            if not match or int(match.group(1)) in found:
                continue
            # The figure spans the column its caption sits in, or the page if the caption straddles the middle.
            if x0 < width / 2 < x1:
                left, right = 0.04 * width, 0.96 * width
            elif x1 <= width / 2 + 5:
                left, right = 0.04 * width, 0.5 * width
            else:
                left, right = 0.5 * width, 0.96 * width
            # It starts below the nearest running text or caption above it: the labels inside a figure are
            # short, a paragraph is not.
            top = max(0, y0 - ABOVE * height)
            for bx0, _, bx1, by1, other, *_ in blocks:
                beside = min(bx1, right) - max(bx0, left) > 0.5 * (bx1 - bx0)
                paragraph = len(other.strip()) >= PARAGRAPH and bx1 - bx0 >= 0.3 * width
                if beside and by1 <= y0 - 20 and (paragraph or CAPTION_LIKE.match(other)):
                    top = max(top, by1)
            found[int(match.group(1))] = (index, pymupdf.Rect(left, top, right, min(height, y1 + 4)))
    if found:
        return found
    # A scan has no text layer: go by the page marks of the transcription and show the whole page.
    page_of = 0
    for line in paper.splitlines():
        mark = re.match(r"--- page (\d+)", line)
        if mark:
            page_of = int(mark.group(1)) - 1
        match = CAPTION_START.match(line.lstrip("*_#> "))
        if match and int(match.group(1)) not in found and 0 <= page_of < len(doc):
            found[int(match.group(1))] = (page_of, None)
    return found


def describe(pdf: Path, paper: str) -> dict[str, str]:
    """Return {"3": "description of figure 3", ...} for the figures found in the PDF."""
    doc = pymupdf.open(pdf)
    places = dict(sorted(locate(pdf, paper).items())[:MAX_FIGURES])

    def see(item) -> str:
        number, (index, region) = item
        page = doc[index]
        png = page.get_pixmap(dpi=150 if region is not None else 110, clip=region).tobytes("png")
        whole = "" if region is not None else f" Describe only Figure {number} on this page."
        # A figure drawn as vectors carries its labels as text: given to the model, they are not misread.
        labels = " ".join(page.get_text("text", clip=region).split())[:LABELS] if region is not None else ""
        if labels:
            whole += f" The text printed in it, as stored in the PDF, to spell labels correctly: {labels}"
        messages = [{"role": "user", "content": [
            {"type": "text", "text": PROMPT + whole},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]
        try:
            text, _ = complete("vision", messages, max_tokens=450, temperature=0.2, extra_body=NO_THINKING,
                               timeout=120, purpose="figure")
        except SpendCapReached:
            raise
        except (openai.APIError, RuntimeError):  # one figure the endpoint fails on is left undescribed
            return ""
        return " ".join(re.sub(r"</?think>", "", text).split())

    # pixmaps are rendered inside the threads, but pymupdf documents are not thread-safe: one at a time
    with ThreadPoolExecutor(1) as pool:
        texts = list(pool.map(see, places.items()))
    return {str(n): t for n, t in zip(places, texts) if t}


def appendix(descriptions: dict[str, str]) -> str:
    """The descriptions as a block of text to append to the paper."""
    if not descriptions:
        return ""
    lines = ["", "", "FIGURES AS SEEN IN THE PDF",
             "(Each figure was described from its image by a vision model. The descriptions say what a figure shows; "
             "values read off a plot are approximate and must not be treated as the paper's numbers.)"]
    lines += [f"Figure {n}, described from the image: {text}" for n, text in descriptions.items()]
    return "\n".join(lines)
