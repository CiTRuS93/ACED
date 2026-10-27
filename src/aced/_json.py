"""One canonical JSON conversion path for framework values."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any
from uuid import UUID

JSON_FORMAT_VERSION = 1


def freeze(value: Any) -> Any:
    """Copy nested containers as immutable values without validating their leaves."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze(item) for item in value)
    return value


class JSONFormatError(ValueError):
    """A serialized document uses an unsupported canonical JSON format."""


def require_json_format_version(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != JSON_FORMAT_VERSION:
        raise JSONFormatError(
            f"unsupported JSON format version {value!r}; supported version is {JSON_FORMAT_VERSION}"
        )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def parse_text(value: str | bytes) -> Any:
    """Parse strict JSON while rejecting JavaScript-only numeric constants."""

    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(
        value,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_unique_json_object,
    )


def utc_text(value: datetime | str | None, *, default: datetime | None = None) -> str:
    if value is None:
        if default is None:
            raise ValueError("a timestamp is required")
        value = default
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        converted = [json_value(item) for item in value]
        return sorted(converted, key=canonical_text)
    if isinstance(value, datetime):
        return utc_text(value)
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return json_value(value.value)
    return value


def canonical_text(value: Any) -> str:
    return canonical_parsed_text(json_value(value))


def canonical_parsed_text(value: Any) -> str:
    """Serialize values already returned by parse_text, without converting again."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_text(value).encode("utf-8")


def canonical_hash(value: Any) -> str:
    encoded = value if isinstance(value, bytes) else canonical_bytes(value)
    return sha256(encoded).hexdigest()


def canonical_link_hash(previous: str, entry_text: str) -> str:
    """Hash an already canonical audit entry without serializing its tree again."""
    return canonical_hash(
        b'{"entry":'
        + entry_text.encode("utf-8")
        + b',"previous":'
        + canonical_bytes(previous)
        + b"}"
    )
