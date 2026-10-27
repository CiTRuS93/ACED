"""Existing hosts and recorder jobs can continue through the package rename."""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

import aced
import cddai


def test_legacy_imports_share_runtime_types_and_modules():
    for name in aced.__all__:
        assert getattr(cddai, name) is getattr(aced, name)
    for module in (
        "agents",
        "models",
        "runtime",
        "store",
        "workflow",
        "transitions",
        "reference",
        "codex",
        "claude",
        "cursor",
        "opencode",
        "_json",
        "_cli",
        "_cli_job",
        "_codex_job",
        "_cli_output",
        "cli",
        "manager.app",
        "manager.contracts",
        "manager.demo",
    ):
        assert importlib.import_module(f"cddai.{module}") is importlib.import_module(
            f"aced.{module}"
        )
    assert (
        importlib.import_module("cddai.manager").create_manager_app
        is importlib.import_module("aced.manager").create_manager_app
    )


@pytest.mark.parametrize("module", ["cddai._cli_job", "cddai._codex_job"])
def test_legacy_recorder_entry_points_observe_existing_result(tmp_path: Path, module: str):
    # A recorder already launched by the old package must not dispatch again.
    result = tmp_path / "result.json"
    result.write_text('{"status":"completed"}')
    subprocess.run([sys.executable, "-m", module, str(tmp_path)], check=True, timeout=10)
    assert result.read_text() == '{"status":"completed"}'
    assert not (tmp_path / "started.json").exists()
