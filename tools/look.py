"""Open the web page in a headless browser and take screenshots, to see what a visitor sees.

    python tools/look.py [--demo] [--report 1706.03762] [--width 1280] [--out screenshots]

Starts app.py on a free port, opens the front page, then a report with its folded sections
expanded, and saves full-page pictures, cut into pieces that can be read at full size.
Needs `pip install playwright` and `python -m playwright install chromium` (development only).
"""

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PIECE = 1100  # pixels: the height of each piece of a long screenshot


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pieces(path: Path) -> None:
    whole = Image.open(path)
    for i, top in enumerate(range(0, whole.height, PIECE)):
        whole.crop((0, top, whole.width, min(whole.height, top + PIECE))).save(
            path.with_name(f"{path.stem}_{i + 1:02d}.png"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="run the page in demo mode")
    parser.add_argument("--report", default="1706.03762", help="the report to open")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--out", default=str(ROOT / "screenshots"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("page_*.png"):
        old.unlink()

    port = free_port()
    env = {**os.environ, "DEMO_MODE": "1" if args.demo else "0", "GRADIO_SERVER_PORT": str(port)}
    server = subprocess.Popen([sys.executable, str(ROOT / "app.py")], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": args.width, "height": 900}, locale="en-US")
            for _ in range(60):  # the server takes a few seconds to start
                try:
                    page.goto(url, timeout=2000)
                    break
                except Exception:  # noqa: BLE001 - not up yet
                    time.sleep(1)
            page.wait_for_selector(".featured article", timeout=30000)
            time.sleep(1)  # web fonts
            page.screenshot(path=str(out / "page_front.png"), full_page=True)
            page.goto(f"{url}/report/{args.report}")
            page.wait_for_selector(".findings, .doc h2", timeout=30000)
            time.sleep(1)
            for summary in page.locator("summary").all():
                summary.click()
            page.screenshot(path=str(out / "page_report.png"), full_page=True)
            browser.close()
    finally:
        server.terminate()
    for name in ("page_front.png", "page_report.png"):
        pieces(out / name)
    print("\n".join(str(p) for p in sorted(out.glob("page_*_*.png"))))


if __name__ == "__main__":
    main()
