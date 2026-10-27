"""Private detached CLI receipt recorder, shared by built-in CLI runners.

This records the original child outcome after the coordinator exits. It does not
supervise descendant tool processes or provide host isolation. Host-owned tools
remain responsible for action identity, cancellation, and external recovery.
"""

from __future__ import annotations

import fcntl
import os
import selectors
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, cast

from aced._cli import _read, _write
from aced._json import parse_text


def _capture(directory: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    output_path = Path(manifest.get("output_path", directory / "output.json"))
    deadline = datetime.fromisoformat(manifest["task"]["deadline"].replace("Z", "+00:00"))
    if datetime.now(UTC) >= deadline or (directory / "cancel").exists():
        return {"status": "cancelled", "reason": "cancelled or expired before CLI launch"}
    with (directory / "prompt.json").open("rb") as prompt:
        process = subprocess.Popen(
            manifest["command"],
            cwd=manifest["workspace"],
            stdin=prompt,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    assert process.stdout is not None and process.stderr is not None
    limit = manifest["max_output_bytes"]
    reason = ""
    termination_at: float | None = None
    finished_at: float | None = None
    total = 0
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ, "events")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        with (
            (directory / "events.jsonl").open("wb") as events,
            (directory / "stderr.log").open("wb") as stderr,
        ):
            outputs = {"events": events, "stderr": stderr}
            while process.poll() is None or selector.get_map():
                if not reason:
                    if (directory / "cancel").exists():
                        reason = "local CLI cancellation confirmed; external effects require review"
                    elif datetime.now(UTC) >= deadline:
                        reason = "task deadline exceeded; external effects require review"
                    elif total > limit or (
                        output_path.exists() and output_path.stat().st_size > limit
                    ):
                        reason = "CLI output exceeded its size limit"
                if reason and process.poll() is None:
                    if termination_at is None:
                        process.terminate()
                        termination_at = time.monotonic()
                    elif time.monotonic() - termination_at > 1:
                        process.kill()
                for key, _ in selector.select(timeout=0.05):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        cast(BinaryIO, key.fileobj).close()
                    else:
                        remaining = max(0, limit - total)
                        outputs[key.data].write(chunk[:remaining])
                        total += len(chunk)
                if process.poll() is not None:
                    if finished_at is None:
                        finished_at = time.monotonic()
                    elif time.monotonic() - finished_at > 1:
                        # A tool child can retain stdout. Its lifetime belongs to
                        # the host; don't hold the recorder open indefinitely.
                        for key in list(selector.get_map().values()):
                            selector.unregister(key.fileobj)
                            cast(BinaryIO, key.fileobj).close()
            exit_code = process.wait()
    if not reason and (
        total > limit or (output_path.exists() and output_path.stat().st_size > limit)
    ):
        reason = "CLI output exceeded its size limit"
    status = "completed" if exit_code == 0 and not reason else "failed"
    adapter = manifest.get("adapter", "codex")
    metadata: dict[str, Any] = {}
    if status == "completed" and adapter != "codex":
        from aced._cli_output import decode_output

        output, metadata = decode_output(adapter, (directory / "events.jsonl").read_bytes())
        _write(directory / "output.json", output)
    elif status == "completed" and output_path != directory / "output.json":
        # The CLI can write only its output surface. The recorder alone publishes
        # protected output and execution receipts after the original process exits.
        descriptor = os.open(output_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            output_descriptor = os.open(
                output_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
            )
            with os.fdopen(output_descriptor, "rb") as stream:
                import stat

                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("agent output must be a regular file")
                payload = stream.read(limit + 1)
            if len(payload) > limit:
                raise ValueError("agent output exceeded its size limit")
            _write(directory / "output.json", parse_text(payload))
        finally:
            os.close(descriptor)
    if reason.startswith("local CLI cancellation"):
        status = "cancelled"
    receipt: dict[str, Any] = {
        "status": status,
        "exit_code": exit_code,
        "reason": reason or ("" if exit_code == 0 else "CLI exited unsuccessfully"),
    }
    if adapter != "codex":
        receipt.update(metadata)
        return receipt
    for line in (directory / "events.jsonl").read_bytes().splitlines():
        try:
            event = parse_text(line)
            if isinstance(event, dict) and event.get("type") == "thread.started":
                receipt["session_id"] = event.get("thread_id")
            if isinstance(event, dict) and event.get("type") == "turn.completed":
                receipt["token_usage"] = event.get("usage")
        except (ValueError, UnicodeDecodeError):
            # Diagnostics are not trusted evidence, and truncated JSONL is valid
            # when the recorder has enforced its output limit.
            continue
    return receipt


def record(directory: Path) -> None:
    """One recorder owns one launch; a stale manifest never authorizes relaunch."""
    descriptor = os.open(directory / "worker.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if (directory / "started.json").exists() or (directory / "result.json").exists():
            return
        _write(directory / "started.json", {"started_at": datetime.now(UTC)})
        try:
            receipt = _capture(directory, _read(directory / "intent.json"))
        except (OSError, ValueError, KeyError, TypeError):
            receipt = {"status": "unknown", "reason": "recorder could not establish CLI outcome"}
        _write(directory / "result.json", receipt)


if __name__ == "__main__":
    record(Path(sys.argv[1]))
