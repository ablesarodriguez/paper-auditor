"""Data the user supplies with a paper: the images, tables or measurements its results were computed from.

A paper's numbers are often "this method, applied to these inputs". The method
can be rebuilt from the text; the inputs cannot. When the user provides them,
the generated scripts read them from one folder, and the audit can compare real
numbers instead of stopping at "needs the paper's data".
"""

import hashlib
import shutil
from pathlib import Path

IMAGES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".pgm", ".ppm", ".webp"}
TEXT = {".csv", ".tsv", ".txt", ".json", ".dat"}


def collect(sources: list[str], target: Path) -> None:
    """Copy the given files, and the files of the given folders, into the audit's data folder."""
    target.mkdir(parents=True, exist_ok=True)
    for source in map(Path, sources):
        for file in ([source] if source.is_file() else sorted(p for p in source.rglob("*") if p.is_file())):
            if file.resolve() != (target / file.name).resolve():
                shutil.copy(file, target / file.name)


def describe(folder: Path) -> tuple[str, str]:
    """Return (a listing of the data for the models, a fingerprint of its content).

    The listing says what each file is, so that a script can be written to read
    it. The fingerprint goes into the record of every script run: the same
    script on other data is another computation.
    """
    files = sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
    if not files:
        return "", ""
    lines, digest = [], hashlib.sha256()
    for file in files:
        content = file.read_bytes()
        digest.update(file.name.encode() + hashlib.sha256(content).digest())
        what = f"{len(content)} bytes"
        suffix = file.suffix.lower()
        if suffix in IMAGES:
            try:
                from PIL import Image
                with Image.open(file) as image:
                    what = f"image, {image.width}x{image.height} pixels (width x height), mode {image.mode}"
            except Exception:  # not readable as an image: describe it by size only
                pass
        elif suffix in TEXT:
            head = content[:240].decode("utf-8", "replace").replace("\n", " / ")
            what = f"text, {len(content)} bytes, starts: {head}"
        elif suffix == ".npy":
            what = f"numpy array file, {len(content)} bytes"
        lines.append(f"- {file.name}: {what}")
    return "\n".join(lines), digest.hexdigest()[:16]
