"""Shared durable CLI execution machinery for development adapters.

The host owns isolation, credentials, quotas, and external-effect reconciliation.
The CLI sandbox is an additional control, not a host isolation boundary. Keep
``state_directory`` outside the agent workspace and inaccessible to agent tools.
A tiny detached recorder survives a coordinator restart; it is not a replacement
for host process supervision. Unknown launches are never automatically repeated.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aced._json import canonical_hash, canonical_text, parse_text
from aced.agents import AgentResult, AgentStatus, AgentTask, ExecutionRef

_MAX_METADATA = 4 * 1024 * 1024


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write(path: Path, value: Any) -> None:
    """Atomically publish a private JSON record and flush the containing directory."""
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(canonical_text(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path: Path, limit: int = _MAX_METADATA) -> Any:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        import stat

        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("job record must be a regular file")
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("job output exceeded its size limit")
    return parse_text(value)


def _validate_schema(schema: Mapping[str, Any], value: Any) -> None:
    """Validate the deliberately small JSON Schema subset used by task contracts.

    The CLI also receives the schema. This independent validation fails closed
    for unsupported keywords; callers cannot mistake partial validation for a
    full JSON Schema implementation.
    """
    allowed = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "description",
        "title",
        "$schema",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
    }
    if set(schema) - allowed:
        raise ValueError("unsupported output schema keyword")
    kind = schema.get("type")
    matches = {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, (list, tuple)),
        "string": isinstance(value, str),
        "number": isinstance(value, (float, int)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    kinds = kind if isinstance(kind, (list, tuple)) else [kind]
    if kind is not None and not any(
        isinstance(item, str) and matches.get(item, False) for item in kinds
    ):
        raise ValueError(f"output does not match schema type {kind!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("output does not match schema enum")
    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        if set(schema.get("required", ())) - set(value):
            raise ValueError("output is missing required properties")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError("output contains unexpected properties")
        for key, child in properties.items():
            if key in value:
                _validate_schema(child, value[key])
    if isinstance(value, (list, tuple)):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get(
            "maxItems", len(value)
        ):
            raise ValueError("output array has an invalid length")
        if "items" in schema:
            for child_value in value:
                _validate_schema(schema["items"], child_value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise ValueError("output number is outside schema bounds")


class CliRunner:
    """Persist CLI intent and recover original jobs without automatic redispatch."""

    adapter = "codex"
    default_executable: tuple[str, ...] = ("codex",)

    def __init__(
        self,
        state_directory: Path,
        *,
        executable: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        launcher_prefix: Sequence[str] = (),
        tool_profiles: Mapping[str, str] | None = None,
        max_output_bytes: int = 1_048_576,
        output_directory: Path | None = None,
    ) -> None:
        if executable is None:
            executable = self.default_executable
        if not executable or isinstance(executable, str) or any(not item for item in executable):
            raise ValueError("executable must be a nonempty argument sequence")
        if isinstance(launcher_prefix, str):
            raise ValueError("launcher_prefix must be an argument sequence")
        if max_output_bytes < 256:
            raise ValueError("max_output_bytes must be at least 256")
        self.state_directory = state_directory.resolve()
        self.executable = tuple(executable)
        self.env = dict(env or {})
        self.launcher_prefix = tuple(launcher_prefix)
        self.tool_profiles = dict(tool_profiles or {})
        self._validate_profiles()
        self.max_output_bytes = max_output_bytes
        self.output_directory = output_directory.resolve() if output_directory else None
        if self.output_directory and self.output_directory.is_relative_to(self.state_directory):
            raise ValueError("agent output must be separate from protected runner records")
        self._children: dict[str, subprocess.Popen[bytes]] = {}

    def _validate_profiles(self) -> None:
        """Adapters validate the host's explicit tool profile configuration."""

    def _profile(self, task: AgentTask) -> str:
        profile = self.tool_profiles.get(task.tool_profile)
        if profile is None:
            if task.tool_profile != "default":
                raise ValueError("unconfigured tool profile")
            return "default"
        return profile

    def _command(
        self, task: AgentTask, workspace: Path, schema: Path, output: Path, profile: str
    ) -> list[str]:
        raise NotImplementedError

    def _prompt(self, task: AgentTask) -> dict[str, Any]:
        return {
            "task_id": task.id,
            "instructions": task.instructions,
            "context": task.context,
            "output_schema": task.output_schema,
            "response_instructions": (
                "Return exactly one JSON object matching output_schema as the final response, "
                "with no Markdown fences or surrounding prose."
            ),
            "deadline": task.deadline,
            "max_cost": task.max_cost,
            "tool_profile": task.tool_profile,
        }

    def _validate_adapter(self, manifest: Mapping[str, Any]) -> None:
        # Existing Codex jobs predate the adapter discriminator.
        if not isinstance(manifest, Mapping):
            raise ValueError("invalid CLI launch intent")
        if manifest.get("adapter", "codex") != self.adapter:
            raise ValueError("task identity was reused with a different CLI adapter")

    async def start(self, task: AgentTask) -> ExecutionRef:
        return self._start(task)

    def _start(self, task: AgentTask) -> ExecutionRef:
        workspace = task.workspace.resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("workspace must be a directory")
        if self.state_directory.is_relative_to(workspace):
            raise ValueError("runner state must be outside the agent workspace")
        profile = self._profile(task)
        reference = ExecutionRef(task.id, task.id)
        self.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        _sync_directory(self.state_directory.parent)
        directory = self._directory(reference)
        try:
            directory.mkdir(mode=0o700)
            _sync_directory(self.state_directory)
        except FileExistsError:
            manifest = _read(directory / "intent.json")
            self._validate_adapter(manifest)
            if manifest["fingerprint"] != task.fingerprint:
                raise ValueError("task identity was reused with changed input") from None
            return reference
        output = directory / "output.json"
        schema = directory / "schema.json"
        if self.output_directory is not None:
            output_folder = self.output_directory / directory.name
            output_folder.mkdir(parents=True, mode=0o700, exist_ok=True)
            if output_folder.is_symlink():
                raise ValueError("agent output directory cannot be a symbolic link")
            output = output_folder / "output.json"
            schema = output_folder / "schema.json"
            _write(schema, task.output_schema)
        command = self._command(task, workspace, schema, output, profile)
        manifest = {
            "adapter": self.adapter,
            "task_id": task.id,
            "fingerprint": task.fingerprint,
            "task": task.payload(),
            "command": command,
            "workspace": str(workspace),
            "max_output_bytes": self.max_output_bytes,
            "output_path": str(output),
        }
        _write(directory / "intent.json", manifest)
        _write(directory / "schema.json", task.output_schema)
        # Prompt via stdin, never a shell command or command-line argument.
        _write(directory / "prompt.json", self._prompt(task))
        if task.deadline <= datetime.now(UTC):
            _write(directory / "result.json", {"status": "failed", "reason": "deadline expired"})
            return reference
        try:
            child = subprocess.Popen(
                [sys.executable, "-m", "aced._cli_job", str(directory)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self.env,
                start_new_session=True,
            )
        except OSError:
            _write(directory / "result.json", {"status": "failed", "reason": "job launch failed"})
        else:
            self._children[reference.job_id] = child
        return reference

    def _directory(self, reference: ExecutionRef) -> Path:
        if not reference.task_id or reference.job_id != reference.task_id:
            raise ValueError("invalid execution reference")
        directory = self.state_directory / canonical_hash({"task_id": reference.task_id})
        if directory.is_symlink():
            raise ValueError("job directory cannot be a symbolic link")
        return directory

    async def observe(self, reference: ExecutionRef) -> AgentResult:
        return self._observe(reference)

    def _observe(self, reference: ExecutionRef) -> AgentResult:
        directory = self._directory(reference)
        child = self._children.get(reference.job_id)
        if child is not None and child.poll() is not None:
            del self._children[reference.job_id]
        if not directory.exists():
            return AgentResult(AgentStatus.ABSENT, execution=reference, reason="no launch intent")
        try:
            manifest = _read(directory / "intent.json")
            self._validate_adapter(manifest)
            if manifest["task_id"] != reference.task_id:
                raise ValueError("task identity mismatch")
            result_path = directory / "result.json"
            if result_path.exists():
                receipt = _read(result_path)
                status = AgentStatus(receipt["status"])
                output: Mapping[str, Any] = {}
                if status == AgentStatus.COMPLETED:
                    value = _read(directory / "output.json", self.max_output_bytes)
                    if not isinstance(value, dict):
                        raise ValueError("agent output must be an object")
                    _validate_schema(manifest["task"]["output_schema"], value)
                    output = value
                return AgentResult(status, output, reference, str(receipt.get("reason", "")))
            lock_path = directory / "worker.lock"
            if lock_path.exists():
                descriptor = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "r+") as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return AgentResult(AgentStatus.PENDING, execution=reference)
            return AgentResult(
                AgentStatus.UNKNOWN,
                execution=reference,
                reason="launch intent lacks a live recorder or receipt; reconcile externally",
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return AgentResult(
                AgentStatus.UNKNOWN,
                execution=reference,
                reason=f"cannot validate agent execution: {type(exc).__name__}",
            )

    async def cancel(self, reference: ExecutionRef) -> AgentResult:
        result = await self.observe(reference)
        if result.status in {
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.CANCELLED,
            AgentStatus.ABSENT,
        }:
            return result
        directory = self._directory(reference)
        try:
            self._validate_adapter(_read(directory / "intent.json"))
        except (OSError, ValueError, KeyError, TypeError):
            return result
        # A request marker is consumed by the original recorder, not a PID kill.
        # If the recorder was lost the outcome stays UNKNOWN and needs host recovery.
        try:
            descriptor = os.open(
                directory / "cancel", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
            _sync_directory(directory)
        return AgentResult(
            result.status,
            execution=reference,
            reason="cancellation requested; local termination and external effects are unconfirmed",
        )
