"""Claude Code CLI adapter; host configuration owns tool access and credentials."""

from pathlib import Path

from aced._cli import CliRunner
from aced._json import canonical_text
from aced.agents import AgentTask


class ClaudeCliRunner(CliRunner):
    """Invoke ``claude --print`` with schema-constrained JSON output.

    Named tool profiles select ``dontAsk``, ``plan`` or ``acceptEdits`` permission
    modes. The default is ``dontAsk``: tools requiring approval are denied unless
    the host has already allowed them. These modes do not provide host isolation.
    """

    adapter = "claude"
    default_executable = ("claude",)

    def _validate_profiles(self) -> None:
        if any(
            mode not in {"dontAsk", "plan", "acceptEdits"} for mode in self.tool_profiles.values()
        ):
            raise ValueError("Claude tool profiles must specify dontAsk, plan or acceptEdits")

    def _profile(self, task: AgentTask) -> str:
        profile = super()._profile(task)
        return "dontAsk" if profile == "default" else profile

    def _command(
        self, task: AgentTask, workspace: Path, schema: Path, output: Path, profile: str
    ) -> list[str]:
        return [
            *self.launcher_prefix,
            *self.executable,
            "--print",
            "--output-format",
            "json",
            "--permission-mode",
            profile,
            "--json-schema",
            canonical_text(task.output_schema),
        ]
