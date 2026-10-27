"""Decode bounded CLI transport output, never authoritative product evidence."""

from typing import Any

from aced._json import parse_text


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("CLI output must be a JSON object")
    return value


def _identity(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("CLI output lacks a valid native identity")
    return value


def _result_metadata(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("type") != "result":
        raise ValueError("CLI output lacks a terminal result")
    if result.get("is_error") is True or str(result.get("subtype", "")).startswith("error"):
        return {"status": "failed", "reason": "CLI reported an unsuccessful result"}
    if result.get("subtype") != "success" or result.get("is_error") is not False:
        raise ValueError("CLI output lacks an explicit success result")
    return {"session_id": _identity(result.get("session_id"))}


def _claude(payload: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    result = _object(parse_text(payload))
    metadata = _result_metadata(result)
    if "status" in metadata:
        return {}, metadata
    if result.get("deferred_tool_use"):
        return {}, {"status": "unknown", "reason": "CLI reported deferred tool work"}
    if result.get("permission_denials") or result.get("terminal_reason") not in {
        None,
        "completed",
    }:
        return {}, {"status": "failed", "reason": "CLI reported denied or unfinished work"}
    output = _object(result.get("structured_output"))
    if isinstance(result.get("usage"), dict):
        metadata["token_usage"] = result["usage"]
    return output, metadata


def _cursor(payload: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    session: str | None = None
    response: str | None = None
    terminal: dict[str, Any] | None = None
    pending_tools: set[str] = set()
    for line in payload.splitlines():
        if not line.strip():
            continue
        if terminal is not None:
            raise ValueError("CLI stream continues after its terminal result")
        event = _object(parse_text(line))
        kind = event.get("type")
        if kind == "result":
            terminal = _result_metadata(event)
            if "status" in terminal:
                return {}, terminal
        current_session = _identity(event.get("session_id"))
        if session is not None and current_session != session:
            raise ValueError("CLI output mixes native sessions")
        session = current_session
        if kind == "assistant":
            message = _object(event.get("message"))
            content = message.get("content")
            if message.get("role") != "assistant" or not isinstance(content, list):
                raise ValueError("CLI assistant message is malformed")
            parts: list[str] = []
            for item in content:
                block = _object(item)
                if block.get("type") == "text":
                    if not isinstance(block.get("text"), str):
                        raise ValueError("CLI text block must contain response text")
                    parts.append(block["text"])
            response = "".join(parts)
        elif kind == "tool_call":
            call = _identity(event.get("call_id"))
            subtype = event.get("subtype")
            if subtype == "started" and call not in pending_tools:
                pending_tools.add(call)
            elif subtype == "completed" and call in pending_tools:
                pending_tools.remove(call)
            else:
                raise ValueError("CLI tool-call sequence is incomplete or repeated")
            response = None
        elif kind == "user":
            # Text preceding tool work is progress, not the final handoff.
            response = None
    if terminal is None or response is None or pending_tools:
        raise ValueError("CLI stream lacks a final assistant response and completion")
    return _object(parse_text(response)), terminal


def _opencode(payload: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    session: str | None = None
    text: dict[str, list[str]] = {}
    finished: set[str] = set()
    active: set[str] = set()
    final: dict[str, Any] | None = None
    for line in payload.splitlines():
        if not line.strip():
            continue
        event = _object(parse_text(line))
        kind = event.get("type")
        if kind == "error":
            return {}, {"status": "failed", "reason": "CLI reported a session error"}
        current_session = _identity(event.get("sessionID"))
        if session is not None and session != current_session:
            raise ValueError("CLI output mixes native sessions")
        session = current_session
        if kind not in {"text", "step_start", "step_finish", "tool_use"}:
            continue
        part = _object(event.get("part"))
        if part.get("sessionID", session) != session:
            raise ValueError("CLI part has a different native session")
        message = _identity(part.get("messageID"))
        if kind == "text":
            response = part.get("text")
            if not isinstance(response, str):
                raise ValueError("CLI text event must contain response text")
            text.setdefault(message, []).append(response)
        elif kind == "step_start":
            if message in finished:
                raise ValueError("CLI restarted a finished message")
            active.add(message)
        elif kind == "step_finish":
            if message in finished:
                raise ValueError("CLI repeated a finished message")
            finished.add(message)
            active.discard(message)
            final = part
        else:
            status = _object(part.get("state")).get("status")
            if status == "error":
                return {}, {"status": "failed", "reason": "CLI reported a tool error or denial"}
            if status != "completed":
                raise ValueError("CLI stream contains unfinished tool work")
    if session is None or final is None or final.get("reason") != "stop" or active:
        raise ValueError("CLI stream lacks a completed final step")
    message = _identity(final.get("messageID"))
    # Earlier messages may contain progress prose or tool-call explanations.
    # Cleanup may publish final text after step_finish, so order alone is not identity.
    if any(identity not in finished for identity in text):
        raise ValueError("CLI stream contains unfinished response text")
    output = _object(parse_text("".join(text.get(message, ()))))
    metadata: dict[str, Any] = {"session_id": session}
    if isinstance(final.get("tokens"), dict):
        metadata["last_step_tokens"] = final["tokens"]
    return output, metadata


def decode_output(adapter: str, payload: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require the native completion envelope before accepting task JSON.

    Malformed, truncated or unfamiliar output raises ValueError and leaves the
    execution unknown. Explicit provider failure becomes a durable failed receipt.
    No Markdown stripping, session resumption or model-assisted repair occurs.
    """
    if adapter == "claude":
        return _claude(payload)
    if adapter == "cursor":
        return _cursor(payload)
    if adapter == "opencode":
        return _opencode(payload)
    raise ValueError("unsupported CLI output protocol")
