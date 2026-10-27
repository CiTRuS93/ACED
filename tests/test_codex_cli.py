"""Actual subprocess tests with a model-free CLI stand-in; no Codex credentials."""

import asyncio
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from aced._codex_job import record
from aced._json import canonical_hash, canonical_text, parse_text
from aced.agents import AgentStatus, AgentTask, ExecutionRef
from aced.codex import CodexCliRunner, _read, _validate_schema, _write


@pytest.fixture
def assignment(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return AgentTask(
        "task-1",
        "run-1",
        1,
        "implement",
        1,
        "codex",
        "Make a safe change",
        {"source": "abc", "learning": []},
        {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "arguments": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "arguments"],
            "additionalProperties": False,
        },
        workspace,
        datetime.now(UTC) + timedelta(seconds=10),
        0,
        "default",
    )


@pytest.fixture
def executable(tmp_path):
    script = tmp_path / "fake_cli.py"
    script.write_text("""
import os
import sys
import time
from pathlib import Path
from aced._json import canonical_text, parse_text
args = sys.argv[1:]
mode = os.environ.get("TEST_MODE", "ok")
prompt = parse_text(sys.stdin.read())
assert prompt["task_id"] == "task-1"
assert args[0] == "exec" and args[-1] == "-"
assert "--json" in args
assert ("--output-schema" in args) is not mode.startswith("freeform")
output = Path(args[args.index("--output-last-message") + 1])
if mode in {"slow", "timeout"}:
    time.sleep(2)
if mode == "huge":
    print("x" * 100000, flush=True)
if mode == "failure":
    sys.exit(3)
if mode == "missing":
    sys.exit(0)
if mode in {"invalid", "freeform_invalid"}:
    output.write_text("not JSON")
elif mode in {"wrong", "freeform_wrong"}:
    output.write_text(canonical_text({"summary": 42, "arguments": args}))
elif mode == "array":
    output.write_text("[]")
elif mode == "big_final":
    output.write_text("x" * 100000)
else:
    output.write_text(canonical_text({"summary": "done", "arguments": args}))
print(canonical_text({"type": "thread.started", "thread_id": "session-1"}))
print(canonical_text({"type": "turn.completed", "usage": {"input_tokens": 10}}))
print("diagnostic-not-json")
""")
    return (sys.executable, str(script))


def runner(tmp_path, executable, mode="ok", **kwargs):
    return CodexCliRunner(
        tmp_path / "state",
        executable=executable,
        env={"TEST_MODE": mode, "PRIVATE_VALUE": "never-persist-this"},
        **kwargs,
    )


async def finished(instance, reference):
    for _ in range(200):
        result = await instance.observe(reference)
        if result.status not in {AgentStatus.PENDING, AgentStatus.UNKNOWN}:
            return result
        if (
            result.status == AgentStatus.UNKNOWN
            and instance._directory(reference).joinpath("result.json").exists()
        ):
            # The receipt can be published after the observation but before this
            # check. Read that receipt instead of returning the stale observation.
            return await instance.observe(reference)
        await asyncio.sleep(0.02)
    pytest.fail("fake CLI did not finish")


async def test_cli_flags_identity_restart_and_no_secret_persistence(
    tmp_path, executable, assignment
):
    original = runner(tmp_path, executable)
    reference = await original.start(assignment)
    assert reference == ExecutionRef(assignment.id, assignment.id)
    restarted = runner(tmp_path, executable)
    assert await restarted.start(assignment) == reference
    result = await finished(restarted, reference)
    assert result.status == AgentStatus.COMPLETED
    assert result.output["summary"] == "done"
    args = result.output["arguments"]
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert result.usage is None
    directory = restarted._directory(reference)
    assert _read(directory / "intent.json")["adapter"] == "codex"
    prompt = _read(directory / "prompt.json")
    assert prompt["output_schema"] == parse_text(canonical_text(assignment.output_schema))
    assert "exactly one JSON object" in prompt["response_instructions"]
    receipt = _read(directory / "result.json")
    assert receipt["session_id"] == "session-1"
    assert receipt["token_usage"] == {"input_tokens": 10}
    for path in directory.iterdir():
        assert "never-persist-this" not in path.read_text()
    assert await original.observe(reference) == result
    assert await restarted.cancel(reference) == result
    with pytest.raises(ValueError, match="changed input"):
        await restarted.start(replace(assignment, instructions="changed"))


@pytest.mark.parametrize(
    ("mode", "status"),
    [
        ("freeform", AgentStatus.COMPLETED),
        ("freeform_invalid", AgentStatus.UNKNOWN),
        ("freeform_wrong", AgentStatus.UNKNOWN),
    ],
)
async def test_open_schema_uses_prompt_and_still_validates_final_json(
    tmp_path, executable, assignment, mode, status
):
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    }
    assignment = replace(assignment, output_schema=schema)
    instance = runner(tmp_path, executable, mode)
    reference = await instance.start(assignment)
    result = await finished(instance, reference)
    assert result.status is status
    prompt = _read(instance._directory(reference) / "prompt.json")
    assert prompt["output_schema"] == schema
    if status is AgentStatus.COMPLETED:
        assert result.output["summary"] == "done"
        assert "--output-schema" not in result.output["arguments"]


@pytest.mark.parametrize(
    ("child", "native"),
    [
        ({"type": "object"}, False),
        ({"type": "array"}, False),
        ({"type": ["object", "null"]}, False),
        (
            {
                "type": "object",
                "properties": {"optional": {"type": "string"}},
                "required": [],
                "additionalProperties": False,
            },
            False,
        ),
        (
            {
                "type": ["object", "null"],
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
                "additionalProperties": False,
            },
            True,
        ),
    ],
)
def test_native_schema_requires_closed_nested_shapes(tmp_path, assignment, child, native):
    schema = {
        "type": "object",
        "properties": {"checkpoint": child},
        "required": ["checkpoint"],
        "additionalProperties": False,
    }
    instance = CodexCliRunner(tmp_path / "state")
    command = instance._command(
        replace(assignment, output_schema=schema),
        assignment.workspace,
        tmp_path / "schema.json",
        tmp_path / "output.json",
        "read-only",
    )
    assert ("--output-schema" in command) is native


def test_runtime_result_envelope_uses_local_schema_validation(tmp_path, assignment):
    from aced.runtime import _OUTPUT_SCHEMA

    instance = CodexCliRunner(tmp_path / "state")
    command = instance._command(
        replace(assignment, output_schema=_OUTPUT_SCHEMA),
        assignment.workspace,
        tmp_path / "schema.json",
        tmp_path / "output.json",
        "read-only",
    )
    assert "--output-schema" not in command


async def test_legacy_codex_intent_still_observes_without_relaunch(
    tmp_path, executable, assignment
):
    instance = runner(tmp_path, executable)
    reference = await instance.start(assignment)
    result = await finished(instance, reference)
    directory = instance._directory(reference)
    manifest = _read(directory / "intent.json")
    del manifest["adapter"]
    _write(directory / "intent.json", manifest)
    restarted = runner(tmp_path, executable)
    assert await restarted.start(assignment) == reference
    assert await restarted.observe(reference) == result


async def test_other_adapter_intent_cannot_be_reused_or_cancelled(tmp_path, executable, assignment):
    instance = runner(tmp_path, executable)
    reference = ExecutionRef(assignment.id, assignment.id)
    directory = instance._directory(reference)
    directory.mkdir(parents=True)
    _write(
        directory / "intent.json",
        {
            "adapter": "claude",
            "task_id": assignment.id,
            "fingerprint": assignment.fingerprint,
        },
    )
    with pytest.raises(ValueError, match="different CLI adapter"):
        await instance.start(assignment)
    assert (await instance.observe(reference)).status == AgentStatus.UNKNOWN
    assert (await instance.cancel(reference)).status == AgentStatus.UNKNOWN
    assert not (directory / "cancel").exists()
    assert not (directory / "started.json").exists()


async def test_separate_agent_output_is_copied_into_protected_records(
    tmp_path, executable, assignment
):
    outputs = tmp_path / "agent-output"
    instance = runner(tmp_path, executable, output_directory=outputs)
    reference = await instance.start(assignment)
    result = await finished(instance, reference)
    assert result.status is AgentStatus.COMPLETED
    directory = instance._directory(reference)
    emitted = outputs / directory.name / "output.json"
    assert emitted.read_bytes() == (directory / "output.json").read_bytes()
    emitted.write_text('{"summary":"changed after completion"}')
    assert (await instance.observe(reference)).output["summary"] == "done"
    assert not any((outputs / directory.name).glob("result.json"))
    with pytest.raises(ValueError, match="separate"):
        runner(tmp_path, executable, output_directory=tmp_path / "state" / "output")


async def test_read_only_and_explicit_profiles(tmp_path, executable, assignment):
    instance = runner(tmp_path, executable, tool_profiles={"test": "workspace-write"})
    reference = await instance.start(replace(assignment, step="propose"))
    result = await finished(instance, reference)
    args = result.output["arguments"]
    assert args[args.index("--sandbox") + 1] == "read-only"
    custom = replace(assignment, id="task-2", step="verify", tool_profile="test")
    # Inspect persisted launch contract; this fake intentionally accepts task-1 only.
    reference2 = await instance.start(custom)
    manifest = _read(instance._directory(reference2) / "intent.json")
    command = manifest["command"]
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    await finished(instance, reference2)
    with pytest.raises(ValueError, match="unconfigured"):
        await instance.start(replace(assignment, tool_profile="unknown"))


async def test_cancel_uses_original_job_and_confirms_only_cli(tmp_path, executable, assignment):
    instance = runner(tmp_path, executable, "slow")
    reference = await instance.start(assignment)
    for _ in range(100):
        if (await instance.observe(reference)).status == AgentStatus.PENDING:
            break
        await asyncio.sleep(0.01)
    result = await instance.cancel(reference)
    assert "unconfirmed" in result.reason
    result = await finished(instance, reference)
    assert result.status == AgentStatus.CANCELLED
    assert await instance.cancel(reference) == result


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("failure", AgentStatus.FAILED),
        ("huge", AgentStatus.FAILED),
        ("invalid", AgentStatus.UNKNOWN),
        ("wrong", AgentStatus.UNKNOWN),
        ("array", AgentStatus.UNKNOWN),
        ("missing", AgentStatus.UNKNOWN),
        ("big_final", AgentStatus.FAILED),
    ],
)
async def test_unsuccessful_or_invalid_output_cannot_complete(
    tmp_path,
    executable,
    assignment,
    mode,
    expected,
):
    instance = runner(tmp_path, executable, mode, max_output_bytes=2048)
    reference = await instance.start(assignment)
    result = await finished(instance, reference)
    assert result.status == expected


async def test_deadline_and_expired_task_are_not_success(tmp_path, executable, assignment):
    instance = runner(tmp_path, executable, "timeout")
    reference = await instance.start(
        replace(assignment, deadline=datetime.now(UTC) + timedelta(seconds=0.2))
    )
    result = await finished(instance, reference)
    assert result.status in {AgentStatus.FAILED, AgentStatus.CANCELLED}
    assert "deadline" in result.reason or "expired" in result.reason
    expired = replace(assignment, id="expired", deadline=datetime.now(UTC) - timedelta(seconds=1))
    assert (await instance.observe(await instance.start(expired))).status == AgentStatus.FAILED


async def test_absent_intent_and_unknown_launch_never_redispatch(tmp_path, executable, assignment):
    instance = runner(tmp_path, executable)
    reference = ExecutionRef(assignment.id, assignment.id)
    assert (await instance.observe(reference)).status == AgentStatus.ABSENT
    assert (await instance.cancel(reference)).status == AgentStatus.ABSENT
    directory = instance._directory(reference)
    directory.mkdir(parents=True)
    _write(
        directory / "intent.json",
        {
            "task_id": assignment.id,
            "fingerprint": assignment.fingerprint,
        },
    )
    assert await instance.start(assignment) == reference
    assert (await instance.observe(reference)).status == AgentStatus.UNKNOWN
    assert (await instance.cancel(reference)).status == AgentStatus.UNKNOWN
    assert (await instance.cancel(reference)).status == AgentStatus.UNKNOWN
    assert (directory / "cancel").exists()
    assert not (directory / "started.json").exists()
    with pytest.raises(ValueError, match="reference"):
        await instance.observe(ExecutionRef("a", "../a"))


async def test_corrupt_receipt_and_path_protection(tmp_path, executable, assignment):
    instance = runner(tmp_path, executable)
    reference = ExecutionRef(assignment.id, assignment.id)
    directory = instance._directory(reference)
    directory.mkdir(parents=True)
    _write(directory / "intent.json", {"task_id": "different"})
    assert (await instance.observe(reference)).status == AgentStatus.UNKNOWN
    _write(directory / "intent.json", {"task_id": assignment.id})
    _write(directory / "result.json", {"status": "not-a-status"})
    assert (await instance.observe(reference)).status == AgentStatus.UNKNOWN
    with pytest.raises(ValueError, match="outside"):
        await CodexCliRunner(assignment.workspace / "state").start(assignment)
    file = tmp_path / "file"
    file.touch()
    with pytest.raises(ValueError, match="directory"):
        await instance.start(replace(assignment, workspace=file))
    linkref = ExecutionRef("link", "link")
    instance._directory(linkref).symlink_to(assignment.workspace, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        await instance.observe(linkref)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"executable": []},
        {"executable": "codex"},
        {"launcher_prefix": "shell"},
        {"max_output_bytes": 1},
        {"tool_profiles": {"unsafe": "danger-full-access"}},
    ],
)
def test_invalid_runner_configuration(tmp_path, kwargs):
    with pytest.raises(ValueError):
        CodexCliRunner(tmp_path, **kwargs)


def test_bounded_reads_and_no_symlinks(tmp_path):
    file = tmp_path / "data.json"
    _write(file, {"value": "long"})
    assert _read(file)["value"] == "long"
    with pytest.raises(ValueError, match="size"):
        _read(file, 2)
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(file)
    with pytest.raises(OSError):
        _read(symlink)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="regular"):
        _read(fifo)


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        ({"anyOf": []}, {}),
        ({"type": "string"}, 2),
        ({"enum": ["a"]}, "b"),
        ({"required": ["needed"]}, {}),
        ({"additionalProperties": False}, {"extra": True}),
        ({"properties": {"a": {"type": "integer"}}}, {"a": True}),
        ({"minItems": 2}, []),
        ({"maxItems": 1}, [1, 2]),
        ({"items": {"type": "boolean"}}, [1]),
        ({"minimum": 2}, 1),
        ({"maximum": 1}, 2),
    ],
)
def test_schema_validation_fails_closed(schema, value):
    with pytest.raises(ValueError):
        _validate_schema(schema, value)


def test_nested_schema_and_json_serialization():
    schema = {
        "type": "object",
        "properties": {
            "a": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
            }
        },
    }
    _validate_schema(schema, {"a": [1, 2]})
    assert canonical_hash(parse_text(canonical_text(schema))) == canonical_hash(schema)


async def test_subprocess_spawn_failure_is_recorded(tmp_path, executable, assignment, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("no process capacity")

    monkeypatch.setattr("aced._cli.subprocess.Popen", unavailable)
    instance = runner(tmp_path, executable)
    reference = await instance.start(assignment)
    assert (await instance.observe(reference)).status == AgentStatus.FAILED


def test_recorder_does_not_relaunch_recorded_attempt(tmp_path):
    directory = tmp_path / "job"
    directory.mkdir()
    _write(directory / "started.json", {})
    record(directory)
    assert not (directory / "result.json").exists()
    (directory / "started.json").unlink()
    record(directory)
    assert _read(directory / "result.json")["status"] == "unknown"


@pytest.mark.parametrize(
    ("mode", "status"),
    [
        ("ok", "completed"),
        ("failure", "failed"),
        ("huge", "failed"),
        ("big_final", "failed"),
        ("timeout", "failed"),
    ],
)
def test_recorder_captures_bounded_streams_and_terminal_outcome(
    tmp_path,
    executable,
    assignment,
    monkeypatch,
    mode,
    status,
):
    # Direct invocation instruments recorder coverage; the tests above separately
    # verify that detached jobs survive a fresh runner and report the same result.
    monkeypatch.setenv("TEST_MODE", mode)
    directory = tmp_path / "recording"
    directory.mkdir()
    deadline = datetime.now(UTC) + timedelta(seconds=0.15 if mode == "timeout" else 5)
    _write(directory / "prompt.json", {"task_id": assignment.id})
    _write(directory / "schema.json", assignment.output_schema)
    _write(
        directory / "intent.json",
        {
            "task": {"deadline": deadline},
            "workspace": str(assignment.workspace),
            "max_output_bytes": 2048,
            "command": [
                *executable,
                "exec",
                "--json",
                "--output-schema",
                str(directory / "schema.json"),
                "--output-last-message",
                str(directory / "output.json"),
                "-",
            ],
        },
    )
    record(directory)
    receipt = _read(directory / "result.json")
    assert receipt["status"] == status
    if mode == "ok":
        assert receipt["session_id"] == "session-1"
        assert receipt["token_usage"]["input_tokens"] == 10
    else:
        assert receipt["reason"]
    assert (directory / "events.jsonl").stat().st_size <= 2048


def test_recorder_honors_cancellation_before_launch_and_live_owner(tmp_path):
    import fcntl

    directory = tmp_path / "recording"
    directory.mkdir()
    _write(
        directory / "intent.json",
        {
            "task": {"deadline": datetime.now(UTC) + timedelta(seconds=10)},
        },
    )
    (directory / "cancel").touch()
    with (directory / "worker.lock").open("w") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        record(directory)
        assert not (directory / "started.json").exists()
    record(directory)
    assert _read(directory / "result.json")["status"] == "cancelled"


@pytest.mark.parametrize("ignore_termination", [False, True])
def test_recorder_confirms_requested_local_termination(tmp_path, assignment, ignore_termination):
    directory = tmp_path / "recording"
    directory.mkdir()
    script = tmp_path / "cancellable.py"
    script.write_text("""
import signal
import sys
import time
from pathlib import Path
if sys.argv[2] == "ignore":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).touch()
time.sleep(10)
""")
    _write(directory / "prompt.json", {})
    _write(
        directory / "intent.json",
        {
            "task": {"deadline": datetime.now(UTC) + timedelta(seconds=5)},
            "workspace": str(assignment.workspace),
            "max_output_bytes": 2048,
            "command": [
                sys.executable,
                str(script),
                str(directory / "cancel"),
                "ignore" if ignore_termination else "terminate",
            ],
        },
    )
    record(directory)
    result = _read(directory / "result.json")
    assert result["status"] == "cancelled"
    assert "external effects" in result["reason"]
    assert result["exit_code"] < 0


def test_recorder_does_not_wait_forever_for_inherited_streams(tmp_path, assignment):
    directory = tmp_path / "recording"
    directory.mkdir()
    script = tmp_path / "inherited_stream.py"
    script.write_text("""
import subprocess
import sys
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
""")
    _write(directory / "prompt.json", {})
    _write(
        directory / "intent.json",
        {
            "task": {"deadline": datetime.now(UTC) + timedelta(seconds=5)},
            "workspace": str(assignment.workspace),
            "max_output_bytes": 2048,
            "command": [sys.executable, str(script)],
        },
    )
    record(directory)
    assert _read(directory / "result.json")["exit_code"] == 0
