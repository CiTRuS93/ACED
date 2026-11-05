"""Record the real offline manager UI and make a short, captioned GIF.

Run from a source checkout after building the frontend and installing the dev
extra, Playwright Chromium, and ffmpeg (with drawtext support):

    .venv/bin/python tests/manager/record_demo.py

Use --chromium /path/to/chromium to use an existing browser. Only the isolated,
in-memory browser fixture is started; no product, live agent, or saved run is used.
The GIF contains excerpts from a real browser video. Idle waits are omitted;
fixture state and UI responses are never mocked or rewritten for the recording.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
VIEWPORT = {"width": 1440, "height": 1000}


def focus_tabs(page: Page) -> None:
    page.get_by_role("tablist").evaluate(
        "element => window.scrollTo(0, element.getBoundingClientRect().top + scrollY - 24)"
    )


def main_metrics(page: Page) -> None:
    page.get_by_role("tab", name="Experiment", exact=True).click()
    page.get_by_label("Phase").select_option("main")
    # The fixture worker and browser polls remain real; refresh until the host
    # has published native fixture observations for the separately approved main.
    for _ in range(20):
        page.get_by_role("button", name="Refresh metrics").click()
        if page.get_by_role("heading", name="Activation (%)").count():
            break
        page.wait_for_timeout(500)
    expect(page.get_by_role("heading", name="Activation (%)")).to_be_visible()
    expect(page.locator(".recharts-surface").first).to_be_visible()
    focus_tabs(page)


def record(port: int, directory: Path, chromium: str | None) -> tuple[Path, list]:
    clips = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium)
        context = browser.new_context(
            viewport=VIEWPORT, record_video_dir=directory, record_video_size=VIEWPORT
        )
        page = context.new_page()
        started = time.monotonic()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{port}/#token=browser-fixture-token-at-least-32-characters")
        page.wait_for_load_state("networkidle")
        assert "token=" not in page.url
        page.get_by_role("button", name="Make the first successful action easier").click()
        page.get_by_role("tab", name="Approvals", exact=True).click()
        expect(page.get_by_role("button", name="Approve task")).to_be_visible()
        page.get_by_role("button", name="Approve task").scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        begin = time.monotonic() - started
        page.wait_for_timeout(1800)
        page.get_by_text("Review exact task and frozen inputs", exact=True).click()
        page.wait_for_timeout(1600)
        page.get_by_text("Review exact task and frozen inputs", exact=True).click()
        page.get_by_role("button", name="Approve task").click()
        page.wait_for_timeout(1800)
        clips.append(
            (begin, time.monotonic() - started, "1 / 4   Review and approve a frozen task")
        )
        page.screenshot(path=directory / "approval.png")

        deadline = time.monotonic() + 120
        saw_main = False
        while time.monotonic() < deadline:
            if page.get_by_role("button", name="Continue with new goal").count():
                break
            approve = page.get_by_role("button", name="Approve task")
            if approve.count() and approve.is_enabled():
                summary = page.locator(".approval h3").inner_text()
                approve.click()
                print(summary, flush=True)
                if "main_exposure" in summary and not saw_main:
                    main_metrics(page)
                    page.wait_for_timeout(800)
                    begin = time.monotonic() - started
                    page.screenshot(path=directory / "experiment.png")
                    page.wait_for_timeout(4500)
                    clips.append(
                        (
                            begin,
                            time.monotonic() - started,
                            "2 / 4   Observe the synthetic experiment",
                        )
                    )
                    saw_main = True
                    page.get_by_role("tab", name="Approvals", exact=True).click()
            page.wait_for_timeout(600)
        else:
            raise TimeoutError("Offline fixture did not finish within two minutes")
        assert saw_main, "Main experiment was not observed"

        main_metrics(page)
        expect(
            page.get_by_text("Synthetic readout: inconclusive; retain baseline.", exact=True)
        ).to_be_visible()
        page.wait_for_timeout(500)
        begin = time.monotonic() - started
        page.screenshot(path=directory / "readout.png")
        page.wait_for_timeout(4000)
        clips.append(
            (begin, time.monotonic() - started, "3 / 4   Read the inconclusive fixture result")
        )

        begin = time.monotonic() - started
        page.get_by_role("tab", name="Cycle history", exact=True).click()
        expect(
            page.get_by_text("Fixture learning with explicit uncertainty", exact=True)
        ).to_be_visible()
        focus_tabs(page)
        page.screenshot(path=directory / "learning.png")
        page.wait_for_timeout(5000)
        clips.append(
            (begin, time.monotonic() - started, "4 / 4   Retain learning for the next cycle")
        )
        assert not errors, errors
        video = page.video
        context.close()
        browser.close()
        assert video is not None
        return Path(video.path()), clips


def encode(video: Path, clips: list, output: Path) -> None:
    filters = []
    offset = 0.0
    for index, (start, end, _label) in enumerate(clips):
        filters.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]")
    inputs = "".join(f"[v{index}]" for index in range(len(clips)))
    caption = "ACED offline fixture  |  Synthetic data  |  Development preview"
    composed = (
        f"{inputs}concat=n={len(clips)}:v=1:a=0,fps=6,scale=1080:-2:flags=lanczos,"
        "pad=iw:ih+68:0:68:color=0x162641,"
        f"drawtext=font=DejaVu Sans:text='{caption}':fontcolor=white:fontsize=19:x=18:y=10"
    )
    for start, end, label in clips:
        duration = end - start
        composed += (
            f",drawtext=font=DejaVu Sans:text='{label}   |   Idle waits omitted'"
            f":fontcolor=0xb8d5ff:fontsize=16:x=18:y=39"
            f":enable='between(t,{offset:.3f},{offset + duration:.3f})'"
        )
        offset += duration
    filters.append(composed + ",split[a][b]")
    filters.append("[a]palettegen=stats_mode=diff:reserve_transparent=0[p]")
    filters.append("[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle[out]")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-loop",
            "0",
            str(output),
        ],
        check=True,
    )
    print(f"Saved {output} ({output.stat().st_size:,} bytes; {offset:.1f} seconds)")


def capture(args: argparse.Namespace, directory: Path) -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "tests/manager/browser_server.py"), str(port)], cwd=ROOT
    )
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Offline fixture server exited")
            try:
                with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise TimeoutError("Offline fixture server did not become ready")
        video, clips = record(port, directory, args.chromium)
        encode(video, clips, args.output)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", help="Optional installed Chromium executable")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/images/manager-offline-demo.gif"
    )
    parser.add_argument("--work-dir", type=Path, help="Retain raw video and review frames here")
    args = parser.parse_args()
    if shutil.which("ffmpeg") is None:
        parser.error("ffmpeg with the drawtext filter is required")
    if args.work_dir:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        capture(args, args.work_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="aced-offline-recording-") as temporary:
            capture(args, Path(temporary))


if __name__ == "__main__":
    main()
