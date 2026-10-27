"""Cursor Agent CLI adapter using a host-prepared permission configuration."""

from pathlib import Path

from aced._cli import CliRunner
from aced.agents import AgentTask


class CursorCliRunner(CliRunner):
    """Invoke the Cursor ``agent`` executable in print mode.

    Profiles select ``agent``, ``ask`` or ``plan``. The default is ``agent``;
    no force, workspace trust or MCP approval bypass is added. Configure permitted
    tools in the host's protected Cursor settings before launching a task.
    """

    adapter = "cursor"
    default_executable = ("agent",)

    def _validate_profiles(self) -> None:
        if any(mode not in {"agent", "ask", "plan"} for mode in self.tool_profiles.values()):
            raise ValueError("Cursor tool profiles must specify agent, ask or plan")

    def _profile(self, task: AgentTask) -> str:
        profile = super()._profile(task)
        return "agent" if profile == "default" else profile

    def _command(
        self, task: AgentTask, workspace: Path, schema: Path, output: Path, profile: str
    ) -> list[str]:
        command = [
            *self.launcher_prefix,
            *self.executable,
            "--print",
            "--output-format",
            "stream-json",
            "--workspace",
            str(workspace),
        ]
        if profile != "agent":
            command.extend(("--mode", profile))
        return command
