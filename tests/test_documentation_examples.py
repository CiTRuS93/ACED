"""Keep first-use output in the guides synchronized with the offline fixtures."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("example", ["resume_workflow", "persist_approval", "synthetic_experiment"])
def test_documented_example_output(example: str) -> None:
    guide = ROOT / "docs" / "examples" / f"{example.replace('_', '-')}.md"
    expected = re.findall(
        r"^Expected output:\n\n```text\n(.*?)^```$", guide.read_text(encoding="utf-8"), re.M | re.S
    )
    assert len(expected) == 1, f"{guide.name} must contain one expected-output block"
    # Use this checkout, including in the approval example's child processes.
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples" / f"{example}.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == expected[0], f"Output differs from {guide.relative_to(ROOT)}"
