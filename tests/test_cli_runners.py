"""Offline subprocess contracts for coding CLIs; no vendor binaries or credentials."""

import asyncio
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from aced import ClaudeCliRunner, CursorCliRunner, OpenCodeCliRunner
from aced._cli import _read, _write
from aced._cli_job import record
from aced._cli_output import decode_output
from aced._json import canonical_text
from aced.agents import AgentStatus, AgentTask, ExecutionRef

RUNNERS = [ClaudeCliRunner, CursorCliRunner, OpenCodeCliRunner]


@pytest.fixture(params=RUNNERS, ids=lambda cls: cls.adapter)
def runner_class(request):
    return request.param


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
        "selected-agent",
        "Make a safe change; preserve `literal` $(instructions)",
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
provider = os.environ["TEST_PROVIDER"]
mode = os.environ.get("TEST_MODE", "ok")
assert os.environ["PRIVATE_VALUE"] == "never-persist-this"
assert "INHERITED_SECRET" not in os.environ
prompt = parse_text(sys.stdin.read())
assert prompt["task_id"] == "task-1"
assert "$(instructions)" in prompt["instructions"]
assert prompt["output_schema"]["required"] == ["summary", "arguments"]
assert "JSON" in prompt["response_instructions"]
assert prompt["instructions"] not in args
with Path(os.environ["LAUNCH_COUNT"]).open("a") as launches:
    launches.write("launch\\n")
Path(os.environ["CHILD_STARTED"]).touch()
if mode in {"slow", "timeout"}:
    time.sleep(2)
if mode == "failure":
    sys.exit(3)
if mode == "huge":
    print("x" * 100000, flush=True)
    sys.exit(0)
if mode == "missing":
    sys.exit(0)
if mode == "invalid":
    print("not JSON")
    sys.exit(0)
output = {"summary": "done", "arguments": args}
if mode == "wrong":
    output["summary"] = 42
if mode == "array":
    output = []
if provider == "claude":
    envelope = {
        "type": "result", "subtype": "success", "is_error": False,
        "structured_output": output, "session_id": "session-1",
        "usage": {"input_tokens": 7, "output_tokens": 3},
    }
    if mode == "provider_error":
        envelope.update(subtype="error_during_execution", is_error=True)
        envelope.pop("structured_output")
        envelope["errors"] = ["provider unavailable"]
    print(canonical_text(envelope))
elif provider == "cursor":
    envelope = {
        "type": "result", "subtype": "success", "is_error": False,
        "result": "Working on the task\\n" + canonical_text(output), "session_id": "session-1",
    }
    if mode == "provider_error":
        envelope.update(subtype="error", is_error=True, result="provider unavailable")
    else:
        print(canonical_text({
            "type": "assistant", "session_id": "session-1",
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": canonical_text(output)},
            ]},
        }))
    print(canonical_text(envelope))
else:
    if mode == "provider_error":
        print(canonical_text({
            "type": "error", "sessionID": "session-1",
            "error": {"name": "APIError", "data": {"message": "provider unavailable"}},
        }))
        sys.exit(0)
    print(canonical_text({
        "type": "text", "sessionID": "session-1",
        "part": {
            "type": "text", "sessionID": "session-1", "messageID": "message-1",
            "text": canonical_text(output),
        },
    }))
    print(canonical_text({
        "type": "step_finish", "sessionID": "session-1",
        "part": {
            "type": "step-finish", "sessionID": "session-1", "messageID": "message-1",
            "reason": "stop", "tokens": {"input": 7, "output": 3},
        },
    }))
""")
    return (sys.executable, str(script))


def runner(tmp_path, runner_class, executable, mode="ok", **kwargs):
    return runner_class(
        tmp_path / "state",
        executable=executable,
        env={
            "TEST_PROVIDER": runner_class.adapter,
            "TEST_MODE": mode,
            "PRIVATE_VALUE": "never-persist-this",
            "LAUNCH_COUNT": str(tmp_path / "launches"),
            "CHILD_STARTED": str(tmp_path / "child-started"),
        },
        **kwargs,
    )


async def finished(instance, reference):
    for _ in range(250):
        result = await instance.observe(reference)
        if result.status not in {AgentStatus.PENDING, AgentStatus.UNKNOWN}:
            return result
        if instance._directory(reference).joinpath("result.json").exists():
            return await instance.observe(reference)
        await asyncio.sleep(0.02)
    pytest.fail("fake CLI did not finish")


async def started(tmp_path):
    for _ in range(250):
        if (tmp_path / "child-started").exists():
            return
        await asyncio.sleep(0.01)
    pytest.fail("fake CLI did not start")


async def test_cli_contract_restart_identity_and_private_environment(
    tmp_path, runner_class, executable, assignment, monkeypatch
):
    monkeypatch.setenv("INHERITED_SECRET", "must-not-reach-the-agent")
    original = runner(tmp_path, runner_class, executable)
    reference = await original.start(assignment)
    assert reference == ExecutionRef(assignment.id, assignment.id)
    restarted = runner(tmp_path, runner_class, executable)
    assert await restarted.start(assignment) == reference
    result = await finished(restarted, reference)
    assert result.status is AgentStatus.COMPLETED
    assert result.output["summary"] == "done"
    assert result.usage is None
    args = result.output["arguments"]
    if runner_class is ClaudeCliRunner:
        assert "--print" in args
        assert args[args.index("--output-format") + 1] == "json"
        assert args[args.index("--permission-mode") + 1] == "dontAsk"
        assert args[args.index("--json-schema") + 1] == canonical_text(assignment.output_schema)
    elif runner_class is CursorCliRunner:
        assert "--print" in args
        assert args[args.index("--output-format") + 1] == "stream-json"
        assert args[args.index("--workspace") + 1] == str(assignment.workspace)
        assert "--force" not in args
    else:
        assert args[0] == "run"
        assert args[args.index("--format") + 1] == "json"
        assert args[args.index("--agent") + 1] == "build"
    assert (tmp_path / "launches").read_text().splitlines() == ["launch"]
    directory = original._directory(reference)
    assert _read(directory / "intent.json")["adapter"] == runner_class.adapter
    assert _read(directory / "result.json")["session_id"] == "session-1"
    for path in directory.iterdir():
        assert "never-persist-this" not in path.read_text()
        assert "must-not-reach-the-agent" not in path.read_text()
    assert await original.observe(reference) == result
    assert await restarted.cancel(reference) == result
    with pytest.raises(ValueError, match="changed input"):
        await restarted.start(replace(assignment, instructions="different instructions"))


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("failure", AgentStatus.FAILED),
        ("provider_error", AgentStatus.FAILED),
        ("huge", AgentStatus.FAILED),
        ("invalid", AgentStatus.UNKNOWN),
        ("missing", AgentStatus.UNKNOWN),
        ("wrong", AgentStatus.UNKNOWN),
        ("array", AgentStatus.UNKNOWN),
    ],
)
async def test_unsuccessful_and_unverifiable_output_never_completes(
    tmp_path, runner_class, executable, assignment, mode, expected
):
    instance = runner(tmp_path, runner_class, executable, mode, max_output_bytes=2048)
    result = await finished(instance, await instance.start(assignment))
    assert result.status is expected
    assert not result.output


async def test_cancellation_observes_original_job(tmp_path, runner_class, executable, assignment):
    instance = runner(tmp_path, runner_class, executable, "slow")
    reference = await instance.start(assignment)
    await started(tmp_path)
    assert (await instance.observe(reference)).status is AgentStatus.PENDING
    requested = await instance.cancel(reference)
    assert "unconfirmed" in requested.reason
    result = await finished(instance, reference)
    assert result.status is AgentStatus.CANCELLED
    assert "external effects" in result.reason
    assert await instance.cancel(reference) == result
    assert (tmp_path / "launches").read_text().splitlines() == ["launch"]


async def test_deadline_is_durable_and_does_not_allow_redispatch(
    tmp_path, runner_class, executable, assignment
):
    instance = runner(tmp_path, runner_class, executable, "timeout")
    task = replace(assignment, deadline=datetime.now(UTC) + timedelta(seconds=0.25))
    reference = await instance.start(task)
    result = await finished(instance, reference)
    assert result.status in {AgentStatus.FAILED, AgentStatus.CANCELLED}
    assert "deadline" in result.reason or "expired" in result.reason
    assert await instance.start(task) == reference
    assert await instance.observe(reference) == result
    expired = replace(assignment, id="expired", deadline=datetime.now(UTC) - timedelta(seconds=1))
    assert (await instance.observe(await instance.start(expired))).status is AgentStatus.FAILED


async def test_stale_intent_remains_unknown_without_redispatch(
    tmp_path, runner_class, executable, assignment
):
    instance = runner(tmp_path, runner_class, executable)
    reference = ExecutionRef(assignment.id, assignment.id)
    assert (await instance.observe(reference)).status is AgentStatus.ABSENT
    assert (await instance.cancel(reference)).status is AgentStatus.ABSENT
    directory = instance._directory(reference)
    directory.mkdir(parents=True)
    _write(
        directory / "intent.json",
        {
            "adapter": runner_class.adapter,
            "task_id": assignment.id,
            "fingerprint": assignment.fingerprint,
        },
    )
    assert await instance.start(assignment) == reference
    assert (await instance.observe(reference)).status is AgentStatus.UNKNOWN
    assert (await instance.cancel(reference)).status is AgentStatus.UNKNOWN
    assert (directory / "cancel").exists()
    assert not (directory / "started.json").exists()
    assert not (tmp_path / "launches").exists()


async def test_different_adapter_cannot_launch_observe_or_cancel_owned_job(
    tmp_path, runner_class, executable, assignment
):
    instance = runner(tmp_path, runner_class, executable, "slow")
    reference = await instance.start(assignment)
    await started(tmp_path)
    directory = instance._directory(reference)
    for other_class in RUNNERS:
        if other_class is runner_class:
            continue
        other = runner(tmp_path, other_class, executable)
        with pytest.raises(ValueError, match="adapter"):
            await other.start(assignment)
        assert (await other.observe(reference)).status is AgentStatus.UNKNOWN
        assert (await other.cancel(reference)).status is AgentStatus.UNKNOWN
        assert not (directory / "cancel").exists()
    assert (await instance.observe(reference)).status is AgentStatus.PENDING
    await instance.cancel(reference)
    assert (await finished(instance, reference)).status is AgentStatus.CANCELLED


async def test_different_adapter_cannot_adopt_completed_receipt(
    tmp_path, runner_class, executable, assignment
):
    instance = runner(tmp_path, runner_class, executable)
    reference = await instance.start(assignment)
    assert (await finished(instance, reference)).status is AgentStatus.COMPLETED
    for other_class in RUNNERS:
        if other_class is runner_class:
            continue
        other = runner(tmp_path, other_class, executable)
        assert (await other.observe(reference)).status is AgentStatus.UNKNOWN
        assert (await other.cancel(reference)).status is AgentStatus.UNKNOWN


@pytest.mark.parametrize(
    ("runner_class", "profile", "flag", "value"),
    [
        (ClaudeCliRunner, "plan", "--permission-mode", "plan"),
        (ClaudeCliRunner, "acceptEdits", "--permission-mode", "acceptEdits"),
        (CursorCliRunner, "ask", "--mode", "ask"),
        (CursorCliRunner, "plan", "--mode", "plan"),
        (OpenCodeCliRunner, "plan", "--agent", "plan"),
    ],
)
async def test_explicit_host_profiles_select_native_controls(
    tmp_path, runner_class, executable, assignment, profile, flag, value
):
    instance = runner(tmp_path, runner_class, executable, tool_profiles={"review": profile})
    task = replace(assignment, tool_profile="review")
    result = await finished(instance, await instance.start(task))
    assert result.status is AgentStatus.COMPLETED
    arguments = result.output["arguments"]
    assert flag in arguments
    if value is not None:
        assert arguments[arguments.index(flag) + 1] == value


async def test_unconfigured_profile_does_not_create_launch_intent(
    tmp_path, runner_class, executable, assignment
):
    instance = runner(tmp_path, runner_class, executable)
    with pytest.raises(ValueError, match="unconfigured"):
        await instance.start(replace(assignment, tool_profile="unconfigured"))
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"executable": []},
        {"executable": "agent"},
        {"launcher_prefix": "shell"},
        {"max_output_bytes": 1},
    ],
)
def test_invalid_configuration(tmp_path, runner_class, kwargs):
    with pytest.raises(ValueError):
        runner_class(tmp_path, **kwargs)


@pytest.mark.parametrize(
    ("runner_class", "profile"),
    [
        (ClaudeCliRunner, "bypassPermissions"),
        (ClaudeCliRunner, "default"),
        (CursorCliRunner, "unknown"),
        (CursorCliRunner, "force"),
        (OpenCodeCliRunner, ""),
        (OpenCodeCliRunner, "host-review"),
    ],
)
def test_invalid_native_profile(tmp_path, runner_class, profile):
    with pytest.raises(ValueError):
        runner_class(tmp_path, tool_profiles={"custom": profile})


def result_envelope(adapter, **changes):
    response = changes.pop("assistant_response", '{"summary":"done"}')
    envelope = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": "session-1",
        "structured_output" if adapter == "claude" else "result": (
            {"summary": "done"} if adapter == "claude" else '{"summary":"done"}'
        ),
    }
    envelope.update(changes)
    if adapter == "cursor":
        return stream(cursor_assistant(response), envelope)
    return canonical_text(envelope).encode()


def cursor_assistant(text='{"summary":"done"}', session="session-1"):
    return {
        "type": "assistant",
        "session_id": session,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def event(kind, message="message-1", session="session-1", **part):
    return {
        "type": kind,
        "sessionID": session,
        "part": {"sessionID": session, "messageID": message, **part},
    }


def stream(*events):
    return "\n".join(canonical_text(item) for item in events).encode()


@pytest.mark.parametrize("adapter", ["claude", "cursor"])
def test_result_envelopes_require_complete_success_identity_and_object(adapter):
    output, metadata = decode_output(adapter, result_envelope(adapter))
    assert output == {"summary": "done"}
    assert metadata == {"session_id": "session-1"}


@pytest.mark.parametrize("adapter", ["claude", "cursor"])
@pytest.mark.parametrize(
    "changes",
    [
        {"type": "assistant"},
        {"type": None},
        {"subtype": "pending"},
        {"is_error": None},
        {"is_error": 0},
        {"session_id": ""},
        {"session_id": 7},
        {"structured_output": [], "assistant_response": "[]"},
        {"structured_output": None, "assistant_response": None},
    ],
)
def test_ambiguous_result_envelopes_are_unknown(adapter, changes):
    with pytest.raises(ValueError):
        decode_output(adapter, result_envelope(adapter, **changes))


@pytest.mark.parametrize("adapter", ["claude", "cursor"])
@pytest.mark.parametrize("payload", [b"", b"[]", b"null", b"{", b"{}\n{}"])
def test_malformed_transport_never_yields_a_result(adapter, payload):
    with pytest.raises(ValueError):
        decode_output(adapter, payload)


@pytest.mark.parametrize("adapter", ["claude", "cursor"])
@pytest.mark.parametrize("changes", [{"is_error": True}, {"subtype": "error_max_turns"}])
def test_explicit_provider_failure_is_preserved(adapter, changes):
    output, metadata = decode_output(adapter, result_envelope(adapter, **changes))
    assert not output
    assert metadata["status"] == "failed"


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"deferred_tool_use": [{"id": "pending-tool"}]}, "unknown"),
        ({"permission_denials": [{"tool_name": "Bash"}]}, "failed"),
        ({"terminal_reason": "budget_exceeded"}, "failed"),
    ],
)
def test_claude_unfinished_or_denied_work_is_not_success(changes, status):
    output, metadata = decode_output("claude", result_envelope("claude", **changes))
    assert not output
    assert metadata["status"] == status


def test_claude_usage_is_native_metadata_and_cursor_requires_plain_json():
    _, metadata = decode_output("claude", result_envelope("claude", usage={"input_tokens": 7}))
    assert metadata["token_usage"] == {"input_tokens": 7}
    for response in ["```json\n{}\n```", "Here is your result: {}", "{", "null"]:
        with pytest.raises(ValueError):
            decode_output("cursor", result_envelope("cursor", assistant_response=response))


def cursor_terminal(**changes):
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": "session-1",
        "result": "I will inspect the source.\nHere is the final result: {}",
    }
    result.update(changes)
    return result


def cursor_tool(subtype, call="call-1"):
    return {
        "type": "tool_call",
        "session_id": "session-1",
        "subtype": subtype,
        "call_id": call,
    }


def test_cursor_final_assistant_is_separate_from_aggregate_progress():
    final = cursor_assistant()
    final["message"]["content"] = [
        {"type": "thinking", "text": "untrusted progress"},
        {"type": "text", "text": '{"summary":'},
        {"type": "text", "text": '"done"}'},
    ]
    output, metadata = decode_output(
        "cursor",
        stream(
            {"type": "system", "subtype": "init", "session_id": "session-1"},
            cursor_assistant("I will inspect the source."),
            cursor_tool("started"),
            cursor_tool("completed"),
            cursor_assistant("The source has been inspected."),
            {"type": "user", "session_id": "session-1", "message": {"role": "user"}},
            final,
            cursor_terminal(),
        )
        + b"\n\n",
    )
    assert output == {"summary": "done"}
    assert metadata == {"session_id": "session-1"}


@pytest.mark.parametrize(
    "events",
    [
        [cursor_terminal()],
        [cursor_assistant()],
        [cursor_assistant(), cursor_terminal(), cursor_terminal()],
        [cursor_assistant(), cursor_terminal(), cursor_assistant()],
        [cursor_assistant(session="different"), cursor_terminal()],
        [cursor_assistant(), cursor_tool("started"), cursor_terminal()],
        [cursor_tool("started"), cursor_assistant(), cursor_terminal()],
        [cursor_tool("completed"), cursor_assistant(), cursor_terminal()],
        [cursor_tool("started"), cursor_tool("completed", "other"), cursor_terminal()],
        [cursor_tool("unknown"), cursor_assistant(), cursor_terminal()],
        [cursor_tool("started", ""), cursor_assistant(), cursor_terminal()],
        [cursor_tool("started"), cursor_tool("completed"), cursor_terminal()],
        [cursor_assistant(), {"type": "user", "session_id": "session-1"}, cursor_terminal()],
        [{"type": "assistant", "session_id": "session-1", "message": None}, cursor_terminal()],
        [
            {
                "type": "assistant",
                "session_id": "session-1",
                "message": {"role": "user", "content": []},
            },
            cursor_terminal(),
        ],
        [
            {
                "type": "assistant",
                "session_id": "session-1",
                "message": {"role": "assistant", "content": "{}"},
            },
            cursor_terminal(),
        ],
        [
            {
                "type": "assistant",
                "session_id": "session-1",
                "message": {"role": "assistant", "content": [None]},
            },
            cursor_terminal(),
        ],
    ],
)
def test_cursor_missing_ambiguous_or_unfinished_handoff_is_unknown(events):
    with pytest.raises(ValueError):
        decode_output("cursor", stream(*events))


def test_opencode_uses_final_message_and_accepts_late_text():
    output, metadata = decode_output(
        "opencode",
        stream(
            event("step_start", "earlier"),
            event("text", "earlier", text="Working on the task"),
            event("tool_use", "earlier", state={"status": "completed"}),
            event("step_finish", "earlier", reason="tool-calls"),
            event("step_start"),
            event("step_finish", reason="stop", tokens={"input": 7, "output": 3}),
            event("text", text='{"summary":'),
            event("text", text='"done"}'),
        )
        + b"\n\n",
    )
    assert output == {"summary": "done"}
    assert metadata == {"session_id": "session-1", "last_step_tokens": {"input": 7, "output": 3}}


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"type": "text"}],
        [event("text", text="{}")],
        [event("step_finish", reason="stop")],
        [event("text", text="{}"), event("step_finish", reason="tool-calls")],
        [event("text", text=7), event("step_finish", reason="stop")],
        [event("text", text="[]"), event("step_finish", reason="stop")],
        [event("text", text="{}"), event("step_finish", "different", reason="stop")],
        [event("text", text="{}"), event("step_finish", session="another", reason="stop")],
        [event("text", text="{}"), event("step_finish", reason="stop"), event("step_start")],
        [
            event("text", text="{}"),
            event("step_finish", reason="stop"),
            event("step_start", "other"),
        ],
        [
            event("text", text="{}"),
            event("step_finish", reason="stop"),
            event("step_finish", reason="stop"),
        ],
        [{"type": "text", "sessionID": "session-1", "part": []}],
        [{"type": "text", "sessionID": "session-1", "part": {"sessionID": "another"}}],
        [{"type": "text", "sessionID": "session-1", "part": {"messageID": ""}}],
        [event("tool_use", state="unknown")],
    ],
)
def test_opencode_incomplete_mixed_and_duplicate_streams_are_unknown(events):
    with pytest.raises(ValueError):
        decode_output("opencode", stream(*events))


def test_opencode_truncated_and_unknown_events_cannot_create_success():
    complete = stream(event("text", text="{}"), event("step_finish", reason="stop"))
    with pytest.raises(ValueError):
        decode_output("opencode", complete + b'\n{"type":')
    output, _ = decode_output(
        "opencode", stream({"type": "diagnostic", "sessionID": "session-1"}) + b"\n" + complete
    )
    assert output == {}
    with pytest.raises(ValueError):
        decode_output("unsupported", complete)


@pytest.mark.parametrize(
    "failure",
    [
        {"type": "error", "error": {"name": "APIError"}},
        event("tool_use", state={"status": "error", "error": "permission denied"}),
    ],
)
def test_opencode_explicit_session_and_tool_failure_are_preserved(failure):
    output, metadata = decode_output("opencode", stream(failure))
    assert not output
    assert metadata["status"] == "failed"


@pytest.mark.parametrize("status", ["pending", "running", "unrecognized", None])
def test_opencode_unfinished_tool_cannot_be_hidden_by_final_success(status):
    with pytest.raises(ValueError, match="unfinished tool"):
        decode_output(
            "opencode",
            stream(
                event("tool_use", state={} if status is None else {"status": status}),
                event("text", text='{"summary":"done"}'),
                event("step_finish", reason="stop"),
            ),
        )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("ok", "completed"), ("provider_error", "failed"), ("invalid", "unknown")],
)
def test_native_recorder_captures_protected_output(
    tmp_path, runner_class, executable, assignment, monkeypatch, mode, expected
):
    # Exercise the recorder directly for coverage, alongside detached-process tests.
    instance = runner(tmp_path, runner_class, executable, mode)
    for name, value in instance.env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("INHERITED_SECRET", raising=False)
    directory = tmp_path / "recording"
    directory.mkdir()
    _write(directory / "prompt.json", instance._prompt(assignment))
    _write(directory / "schema.json", assignment.output_schema)
    _write(
        directory / "intent.json",
        {
            "adapter": runner_class.adapter,
            "task": assignment.payload(),
            "workspace": str(assignment.workspace),
            "max_output_bytes": 4096,
            "command": [*executable],
            "output_path": str(directory / "output.json"),
        },
    )
    record(directory)
    receipt = _read(directory / "result.json")
    assert receipt["status"] == expected
    if mode == "ok":
        assert _read(directory / "output.json")["summary"] == "done"
        assert receipt["session_id"] == "session-1"
