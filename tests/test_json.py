import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from uuid import UUID

import pytest

from aced._json import (
    JSON_FORMAT_VERSION,
    canonical_bytes,
    canonical_hash,
    canonical_text,
    freeze,
    parse_text,
    require_json_format_version,
    utc_text,
)


class Outcome(Enum):
    OK = "ok"


@dataclass
class Payload:
    value: int


def test_utc_text_requires_and_normalizes_aware_timestamps() -> None:
    with pytest.raises(ValueError, match="required"):
        utc_text(None)
    with pytest.raises(ValueError, match="UTC offset"):
        utc_text(datetime(2026, 1, 1))

    default = datetime(2026, 1, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert utc_text(None, default=default) == "2026-01-01T02:03:04.000005Z"
    assert utc_text("2026-01-01T04:03:04+02:00") == "2026-01-01T02:03:04.000000Z"
    assert (
        utc_text(datetime(2026, 1, 1, 4, 3, 4, tzinfo=timezone(timedelta(hours=2))))
        == "2026-01-01T02:03:04.000000Z"
    )


def test_canonical_json_supports_storage_types_and_rejects_others() -> None:
    value = {
        "uuid": UUID("12345678-1234-5678-1234-567812345678"),
        "outcome": Outcome.OK,
        "payload": Payload(2),
        "when": datetime(2026, 1, 1, tzinfo=UTC),
        "unicode": "café",
    }
    encoded = canonical_text(value)
    assert encoded == (
        '{"outcome":"ok","payload":{"value":2},"unicode":"café",'
        '"uuid":"12345678-1234-5678-1234-567812345678",'
        '"when":"2026-01-01T00:00:00.000000Z"}'
    )
    assert json.loads(encoded)["payload"] == {"value": 2}

    with pytest.raises(TypeError, match="object is not JSON serializable"):
        canonical_text(object())
    with pytest.raises(ValueError):
        canonical_text(float("nan"))


def test_canonical_json_v1_compatibility_vector() -> None:
    value = {
        2: {
            "duration": timedelta(milliseconds=1_500),
            "items": {"β", "a"},
            "outcome": Outcome.OK,
            "payload": Payload(2),
            "uuid": UUID("12345678-1234-5678-1234-567812345678"),
            "when": datetime(2026, 1, 1, 2, tzinfo=timezone(timedelta(hours=2))),
        }
    }
    expected = (
        '{"2":{"duration":1.5,"items":["a","β"],"outcome":"ok",'
        '"payload":{"value":2},"uuid":"12345678-1234-5678-1234-567812345678",'
        '"when":"2026-01-01T00:00:00.000000Z"}}'
    )

    assert JSON_FORMAT_VERSION == 1
    assert canonical_text(value) == expected
    assert canonical_bytes(value) == expected.encode()
    assert canonical_hash(value) == sha256(expected.encode()).hexdigest()


@pytest.mark.parametrize("version", [None, True, 0, 2, "1"])
def test_json_format_version_fails_closed(version: object) -> None:
    with pytest.raises(ValueError, match="unsupported JSON format version"):
        require_json_format_version(version)


def test_strict_json_parser_rejects_nonstandard_constants() -> None:
    for constant in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValueError, match="invalid JSON constant"):
            parse_text('{"value":' + constant + "}")


def test_strict_json_parser_rejects_duplicate_object_keys() -> None:
    with pytest.raises(ValueError, match="duplicate JSON object key 'format_version'"):
        parse_text('{"format_version":2,"format_version":1,"payload":{}}')


def test_strict_json_parser_requires_utf8_bytes() -> None:
    assert parse_text('{"label":"β"}'.encode()) == {"label": "β"}
    with pytest.raises(UnicodeDecodeError):
        parse_text('{"label":"β"}'.encode("utf-16"))


def test_format_version_accepts_exact_supported_integer() -> None:
    require_json_format_version(JSON_FORMAT_VERSION)


def test_freeze_keeps_input_independent_and_hash_stable() -> None:
    original = {"nested": [{"enabled": True}], "names": {"β", "a"}}
    frozen = freeze(original)
    expected = canonical_bytes(original)
    original["nested"][0]["enabled"] = False
    original["names"].add("new")
    assert canonical_bytes(frozen) == expected
    assert canonical_hash(frozen) == canonical_hash(expected)
    with pytest.raises(TypeError):
        frozen["nested"][0]["enabled"] = False


def test_preencoded_audit_hash_matches_canonical_structure():
    from aced._json import (
        canonical_hash,
        canonical_link_hash,
        canonical_parsed_text,
        canonical_text,
        parse_text,
    )

    entry = {"data": {"text": 'unicode ✓ and "quotes"', "values": [None, True, 2.5]}, "seq": 1}
    encoded = canonical_text(entry)
    assert canonical_parsed_text(parse_text(encoded)) == encoded
    for previous in ["", "abc123", 'quoted"value']:
        assert canonical_link_hash(previous, encoded) == canonical_hash(
            {"previous": previous, "entry": entry}
        )
