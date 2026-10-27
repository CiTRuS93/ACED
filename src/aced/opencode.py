"""OpenCode CLI adapter for the documented ``run --format json`` event protocol."""

from pathlib import Path

from aced._cli import CliRunner
from aced.agents import AgentTask


class OpenCodeCliRunner(CliRunner):
    """Run a fresh OpenCode task using its built-in ``build`` or ``plan`` agent.

    The default selects ``build`` for implementation (except corrections) and
    ``plan`` otherwise. These are native agent policies, not filesystem sandboxes.
    Host configuration must enforce tool permissions, provider access and quotas.
    """

    adapter = "opencode"
    default_executable = ("opencode",)

    def _validate_profiles(self) -> None:
        if any(agent not in {"build", "plan"} for agent in self.tool_profiles.values()):
            raise ValueError("OpenCode tool profiles must specify build or plan")

    def _profile(self, task: AgentTask) -> str:
        profile = super()._profile(task)
        if profile != "default":
            return profile
        return "build" if task.step == "implement" and task.scope != "correction" else "plan"

    def _command(
        self, task: AgentTask, workspace: Path, schema: Path, output: Path, profile: str
    ) -> list[str]:
        return [
            *self.launcher_prefix,
            *self.executable,
            "run",
            "--format",
            "json",
            "--agent",
            profile,
        ]
