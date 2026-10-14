"""Open the web page in a headless browser and take screenshots, to see what a visitor sees.

    python tools/look.py [--demo] [--example "Attention"] [--out screenshots]

Starts app.py on a free port, opens it, takes a picture of the page, opens the
chosen example report, expands its folded sections and takes pictures of it.
Needs `pip install playwright` and `python -m playwright install chromium`
(development only: the app does not need them).
"""

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PIECE = 1100  # pixels: the height of each piece of the long screenshot


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="run the page in demo mode")
    parser.add_argument("--example", default="", help="part of the label of a report in the list (default: the "
                                                      "first featured report)")
    parser.add_argument("--out", default=str(ROOT / "screenshots"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    port = free_port()
    env = {**os.environ, "DEMO_MODE": "1" if args.demo else "0", "GRADIO_SERVER_PORT": str(port),
           "PYTHONIOENCODING": "utf-8"}
    server = subprocess.Popen([sys.executable, str(ROOT / "app.py")], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            for _ in range(60):  # the app takes a few seconds to start
                try:
                    page.goto(url, timeout=2000)
                    break
                except Exception:  # noqa: BLE001 - not up yet
                    time.sleep(1)
            page.wait_for_selector("text=Open this report", timeout=30000)
            page.screenshot(path=str(out / "1_page.png"), full_page=True)

            # open an example report: one of the featured ones by default, or one chosen from the list
            if args.example:
                page.get_by_label("All example reports").click()
                page.get_by_role("option", name=args.example).first.click()
                page.get_by_role("button", name="Open this report").click()
            else:
                page.get_by_role("button", name="Open report").first.click()
            page.wait_for_selector("text=Summary of the paper", timeout=30000)
            time.sleep(1)
            page.screenshot(path=str(out / "2_report.png"), full_page=True)

            # expand every folded section and look again
            for summary in page.locator("summary").all():
                summary.click()
            time.sleep(0.5)
            page.screenshot(path=str(out / "3_report_expanded.png"), full_page=True)
            browser.close()
        # the expanded page in pieces a reader can follow at full size
        from PIL import Image
        whole = Image.open(out / "3_report_expanded.png")
        for old in out.glob("4_part*.png"):
            old.unlink()
        for i, top in enumerate(range(0, whole.height, PIECE)):
            whole.crop((0, top, whole.width, min(whole.height, top + PIECE))).save(out / f"4_part{i + 1:02d}.png")
    finally:
        server.terminate()
    print("\n".join(str(p) for p in sorted(out.glob("*.png"))))


if __name__ == "__main__":
    main()
