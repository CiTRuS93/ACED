"""Codex CLI runner with durable local receipts for development use.

The host owns isolation, credentials, quotas, and external-effect reconciliation.
The CLI sandbox is an additional control, not a host isolation boundary. Keep
``state_directory`` outside the agent workspace and inaccessible to agent tools.
A tiny detached recorder survives a coordinator restart; it is not a replacement
for host process supervision. Unknown launches are never automatically repeated.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aced._cli import CliRunner
from aced._cli import _read as _read
from aced._cli import _validate_schema as _validate_schema
from aced._cli import _write as _write
from aced.agents import AgentTask


def _native_schema(schema: Mapping[str, Any]) -> bool:
    """Whether this supported schema fits the provider's closed structured format.

    Open task deliverables remain valid local schemas, but cannot be supplied to
    Codex's strict output flag. They still receive independent result validation.
    """
    kind = schema.get("type")
    kinds = (kind,) if isinstance(kind, str) else kind
    if not isinstance(kinds, (list, tuple)) or not kinds:
        return False
    if any(
        item not in {"object", "array", "string", "number", "integer", "boolean", "null"}
        for item in kinds
    ):
        return False
    if len(kinds) > 1 and (len(kinds) != 2 or "null" not in kinds):
        return False
    if "object" in kinds:
        properties = schema.get("properties")
        required = schema.get("required")
        if (
            not isinstance(properties, Mapping)
            or schema.get("additionalProperties") is not False
            or not isinstance(required, (list, tuple))
            or set(required) != set(properties)
        ):
            return False
        if any(
            not isinstance(child, Mapping) or not _native_schema(child)
            for child in properties.values()
        ):
            return False
    if "array" in kinds:
        items = schema.get("items")
        if not isinstance(items, Mapping) or not _native_schema(items):
            return False
    return True


class CodexCliRunner(CliRunner):
    """Run ``codex exec`` through an explicit host-prepared environment.

    ``env`` is passed to the child without merging the service's environment and
    is never written to a receipt. Authentication normally uses a host-selected
    CODEX_HOME. Monetary usage is unknown (``None``); host accounting must enforce
    spending. ``tool_profiles`` maps profile names to explicit CLI sandboxes.
    Profiles configure sandbox access only; tools/credentials are host-owned.
    """

    adapter = "codex"
    default_executable = ("codex",)

    def _validate_profiles(self) -> None:
        if any(
            value not in {"read-only", "workspace-write"} for value in self.tool_profiles.values()
        ):
            raise ValueError("tool profiles must specify read-only or workspace-write")

    def _profile(self, task: AgentTask) -> str:
        sandbox = self.tool_profiles.get(task.tool_profile)
        if sandbox is None:
            if task.tool_profile != "default":
                raise ValueError("unconfigured tool profile")
            sandbox = (
                "workspace-write"
                if task.step == "implement" and task.scope != "correction"
                else "read-only"
            )
        return sandbox

    def _command(
        self, task: AgentTask, workspace: Path, schema: Path, output: Path, profile: str
    ) -> list[str]:
        native_schema = (
            ["--output-schema", str(schema)]
            if task.output_schema.get("type") == "object" and _native_schema(task.output_schema)
            else []
        )
        return [
            *self.launcher_prefix,
            *self.executable,
            "exec",
            "--json",
            "--color",
            "never",
            "--sandbox",
            profile,
            *native_schema,
            "--output-last-message",
            str(output),
            "--cd",
            str(workspace),
            "-",
        ]
