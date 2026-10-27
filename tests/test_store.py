"""Compact persistence, immutable handoffs, recovery, fencing, and corruption."""

from __future__ import annotations

import sqlite3
import time
import tracemalloc
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from aced._json import canonical_hash, canonical_text, utc_text
from aced.store import ConflictError, NotFoundError, SQLiteStore, StaleLeaseError, StoreError

NOW = datetime(2026, 10, 20, tzinfo=UTC)


def task(number: int, *, result: bool = False) -> dict[str, Any]:
    return {
        "task": {"id": f"task-{number}", "inputs": {"source": "baseline"}, "runner": "fixture"},
        "status": "result" if result else "prepared",
        "result": {"status": "completed", "summary": f"Output {number}"} if result else None,
        "verification": None,
    }


async def test_restart_detached_inputs_and_compact_history(tmp_path: Path) -> None:
    path = tmp_path / "four-stage.sqlite"
    store = SQLiteStore(path)
    data = {"status": "active", "wake_at": None, "task": task(1), "current": "task-1"}
    record = await store.create("run", "project", "request", "fingerprint", data)
    data["task"]["task"]["inputs"]["source"] = "not committed"  # type: ignore[index]
    fetched = await store.get("run")
    assert fetched == record
    fetched.data["task"]["task"]["inputs"]["source"] = "also not committed"
    assert (await store.get("run")).data["task"]["task"]["inputs"]["source"] == "baseline"
    record = await store.save(
        record, {**record.data, "task": task(1, result=True)}, "result", "worker", NOW
    )
    record = await store.save(record, {**record.data, "current": None}, "accepted", "worker", NOW)
    await store.close()
    reopened = SQLiteStore(path)
    assert await reopened.get("run") == record
    assert await reopened.find("project", "request") == record
    assert await reopened.find("project", "missing") is None
    history = await reopened.history("run")
    assert [event["event"] for event in history] == ["created", "result", "accepted"]
    assert history[1]["previous_hash"] == history[0]["hash"]
    assert "data" not in history[1]
    assert history[1]["actor"] == "worker"
    assert len(history[1]["record_refs"]) == 2
    assert await reopened.verify_audit()
    await reopened.close()


async def test_tasks_results_evidence_retained_once_and_paginated(tmp_path: Path) -> None:
    path = tmp_path / "four-stage.sqlite"
    store = SQLiteStore(path)
    record = await store.create("run", "project", "key", "f", {"status": "active"})
    for number in range(5):
        entry = task(number, result=True)
        entry["verification"] = {"outcome": "verified", "record": f"receipt-{number}"}
        record = await store.save(
            record, {**record.data, "task": entry, "current": None}, "result", "worker", NOW
        )
        # Re-reading the same completed result must not append events or rewrite it.
        assert await store.save(record, record.data, "result", "worker", NOW) == record
    first = await store.tasks("run", limit=2)
    second = await store.tasks("run", limit=2, after=first[-1]["seq"])
    third = await store.tasks("run", limit=2, after=second[-1]["seq"])
    assert [item["task"]["id"] for item in (*first, *second, *third)] == [
        f"task-{i}" for i in range(5)
    ]
    assert first[0]["result"]["summary"] == "Output 0"
    assert first[0]["verification"]["record"] == "receipt-0"
    history = await store.history("run", limit=2)
    assert len(await store.history("run", limit=100, after=history[-1]["seq"])) == 4
    with closing(sqlite3.connect(path)) as raw:
        assert raw.execute("SELECT count(*) FROM tasks").fetchone()[0] == 5
        assert raw.execute("SELECT count(*) FROM records WHERE kind = 'result'").fetchone()[0] == 5
        assert raw.execute("SELECT count(*) FROM events").fetchone()[0] == 6
        assert "Output" not in raw.execute("SELECT data FROM runs").fetchone()[0]
        assert (
            "Output"
            not in raw.execute("SELECT payload FROM events ORDER BY seq DESC LIMIT 1").fetchone()[0]
        )
    assert await store.verify_audit()
    await store.close()


async def test_task_inputs_and_completed_results_are_immutable(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "four-stage.sqlite")
    record = await store.create(
        "run", "project", "key", "f", {"status": "active", "task": task(1, result=True)}
    )
    for field, value in (
        ("task", {"id": "task-1", "runner": "other"}),
        ("result", None),
        ("result", {"status": "failed"}),
    ):
        with pytest.raises(ConflictError, match="immutable"):
            await store.save(
                record,
                {**record.data, "task": {**record.data["task"], field: value}},
                "change",
                "worker",
                NOW,
            )
    # Pending evidence can change, but both immutable facts remain referenced by events.
    for outcome in ("pending", "verified"):
        entry = {**record.data["task"], "verification": {"outcome": outcome}}
        record = await store.save(
            record, {**record.data, "task": entry}, "verification", "worker", NOW
        )
    assert await store.verify_audit()
    await store.close()


async def test_duplicates_and_shared_resource_ownership_through_cleanup(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "four-stage.sqlite")
    active = {"status": "active", "config": {"resource_id": "one-shop"}}
    record = await store.create("first", "project", "key", "f", active)
    for status in ("active", "held", "stopping"):
        record = await store.save(
            record, {**record.data, "status": status}, "control", "operator", NOW
        )
        with pytest.raises(ConflictError):
            await store.create("other", "different-project", "key", "f", active)
        with pytest.raises(ConflictError):
            await store.create("other", "project", "other-key", "f", {"status": "active"})
    with pytest.raises(ConflictError, match="resource"):
        await store.save(
            record,
            {"status": "active", "config": {"resource_id": "other"}},
            "change",
            "operator",
            NOW,
        )
    await store.save(record, {**record.data, "status": "stopped"}, "closed", "operator", NOW)
    await store.create("second", "different-project", "key", "f", active)
    with pytest.raises(ConflictError):
        await store.create("duplicate", "project", "key", "f", {"status": "completed"})
    assert await store.verify_audit()
    await store.close()


async def test_revisions_detached_record_mutation_and_identity(tmp_path: Path) -> None:
    path = tmp_path / "four-stage.sqlite"
    first, second = SQLiteStore(path), SQLiteStore(path)
    record = await first.create("run", "project", "key", "f", {"status": "active"})
    old = await second.get("run")
    record.data["status"] = "held"
    updated = await first.save(record, record.data, "held", "operator", NOW)
    assert updated.revision == 1
    with pytest.raises(ConflictError, match="revision"):
        await second.save(old, {"status": "stopped"}, "stop", "operator", NOW)
    for field in ("project_id", "key", "fingerprint"):
        with pytest.raises(ConflictError, match="identity"):
            await first.save(
                replace(updated, **{field: "changed"}), updated.data, "change", "operator", NOW
            )
    assert await second.get("run") == updated
    await first.close()
    await second.close()


async def test_fencing_expiry_and_stale_release(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "four-stage.sqlite")
    record = await store.create("run", "project", "key", "f", {"status": "active"})
    first = await store.acquire("run", "worker-one", NOW, seconds=10)
    assert first is not None and first.fence == 1
    assert await store.acquire("run", "worker-two", NOW) is None
    record = await store.save(
        record, {**record.data, "observation": 1}, "observed", "worker-one", NOW, first
    )
    expiry = NOW + timedelta(seconds=10)
    with pytest.raises(StaleLeaseError):
        await store.save(record, record.data, "late", "worker-one", expiry, first)
    second = await store.acquire("run", "worker-two", expiry)
    assert second is not None and second.fence == 2
    await store.release(first)
    assert await store.acquire("run", "worker-three", expiry) is None
    for invalid in (
        first,
        replace(second, run_id="different"),
        replace(second, owner="different"),
        replace(second, expires_at=second.expires_at + timedelta(seconds=1)),
    ):
        with pytest.raises(StaleLeaseError):
            await store.save(record, record.data, "invalid", "worker-two", expiry, invalid)
    record = await store.save(
        record, {**record.data, "observation": 2}, "observed", "worker-two", expiry, second
    )
    await store.release(second)
    with pytest.raises(StaleLeaseError):
        await store.save(record, record.data, "released", "worker-two", expiry, second)
    assert await store.verify_audit()
    await store.close()


async def test_due_runs_include_held_safety_work(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "four-stage.sqlite")
    for name, status, wake in (
        ("active", "active", None),
        ("held", "held", utc_text(NOW)),
        ("stopping", "stopping", utc_text(NOW - timedelta(seconds=1))),
        ("future", "active", utc_text(NOW + timedelta(seconds=1))),
        ("complete", "completed", None),
        ("stop", "stopped", None),
    ):
        await store.create(name, name, "key", "f", {"status": status, "wake_at": wake})
    assert [record.id for record in await store.list_due(NOW)] == ["active", "held", "stopping"]
    assert await store.verify_audit()
    await store.close()


async def test_projection_records_and_audit_rollback_together(tmp_path: Path) -> None:
    path = tmp_path / "four-stage.sqlite"
    store = SQLiteStore(path)
    record = await store.create("run", "project", "key", "f", {"status": "active"})
    with closing(sqlite3.connect(path, isolation_level=None)) as raw:
        raw.execute(
            "CREATE TRIGGER injected_failure BEFORE INSERT ON events "
            "BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END"
        )
    with pytest.raises(ConflictError, match="simulated disk failure"):
        await store.save(
            record, {"status": "active", "task": task(1, result=True)}, "result", "worker", NOW
        )
    assert await store.get("run") == record
    assert await store.tasks("run") == ()
    with closing(sqlite3.connect(path, isolation_level=None)) as raw:
        assert raw.execute("SELECT count(*) FROM records").fetchone()[0] == 0
        raw.execute("DROP TRIGGER injected_failure")
    updated = await store.save(record, {"status": "completed"}, "closed", "operator", NOW)
    assert updated.revision == 1
    assert [event["seq"] for event in await store.history("run")] == [1, 2]
    assert await store.verify_audit()
    await store.close()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE runs SET data = '{}'",
        "UPDATE runs SET status = 'completed'",
        "UPDATE runs SET wake_at = '2026-10-20T00:00:00.000000Z'",
        "UPDATE runs SET fingerprint = 'changed'",
        "UPDATE runs SET resource_id = 'changed'",
        "UPDATE runs SET revision = 0",
        "UPDATE runs SET latest_hash = 'changed'",
        "UPDATE runs SET data_digest = 'changed'",
        "UPDATE runs SET lease_owner = 'orphan'",
        "UPDATE runs SET lease_expires = 'bad', lease_owner = 'worker'",
        "UPDATE tasks SET digest = 'changed'",
        "UPDATE tasks SET data = '{}'",
        "UPDATE tasks SET last_seq = 1",
        "DELETE FROM tasks",
        "UPDATE records SET content = '{}' WHERE kind = 'task'",
        "UPDATE records SET digest = 'changed' WHERE kind = 'result'",
        "DELETE FROM records WHERE kind = 'task'",
        "UPDATE events SET payload = '{}' WHERE seq = 2",
        "UPDATE events SET previous_hash = 'changed' WHERE seq = 2",
        "UPDATE events SET hash = 'changed' WHERE seq = 2",
        "DELETE FROM events WHERE seq = 2",
        "DELETE FROM events",
        "DELETE FROM runs",
        "UPDATE cddai_metadata SET value = 'changed' WHERE key = 'last_hash'",
        "UPDATE cddai_metadata SET value = 'changed' WHERE key = 'format'",
    ],
)
async def test_active_corruption_fails_closed(tmp_path: Path, statement: str) -> None:
    path = tmp_path / "four-stage.sqlite"
    store = SQLiteStore(path)
    record = await store.create("run", "project", "key", "f", {"status": "active", "task": task(1)})
    await store.save(
        record, {"status": "held", "task": task(1, result=True)}, "result", "worker", NOW
    )
    with closing(sqlite3.connect(path, isolation_level=None)) as raw:
        raw.execute(statement)
    assert not await store.verify_audit()
    with pytest.raises(StoreError):
        await store.get("run")
    await store.close()
    with pytest.raises(StoreError):
        SQLiteStore(path)


async def test_historical_corruption_requires_explicit_full_audit(tmp_path: Path) -> None:
    path = tmp_path / "four-stage.sqlite"
    store = SQLiteStore(path)
    record = await store.create("run", "project", "key", "f", {"status": "active", "task": task(1)})
    record = await store.save(record, {"status": "active", "task": task(2)}, "next", "worker", NOW)
    await store.close()
    with closing(sqlite3.connect(path, isolation_level=None)) as raw:
        raw.execute("UPDATE events SET payload = '{}' WHERE seq = 1")
    reopened = SQLiteStore(path)
    assert await reopened.get("run") == record
    assert not await reopened.verify_audit()
    with pytest.raises(StoreError):
        await reopened.get("run")
    await reopened.close()


async def test_full_audit_detects_deleted_historical_task_without_reopen_scan(
    tmp_path: Path,
) -> None:
    path = tmp_path / "four-stage.sqlite"
    store = SQLiteStore(path)
    record = await store.create("run", "project", "key", "f", {"status": "active", "task": task(1)})
    record = await store.save(record, {"status": "active", "task": task(2)}, "next", "worker", NOW)
    assert await store.verify_audit()
    await store.close()
    with closing(sqlite3.connect(path, isolation_level=None)) as raw:
        raw.execute("DELETE FROM tasks WHERE id = 'task-1'")
    reopened = SQLiteStore(path)
    assert await reopened.get("run") == record
    assert len(await reopened.tasks("run")) == 1
    assert not await reopened.verify_audit()
    await reopened.close()


async def test_safety_selection_includes_future_waits_but_excludes_terminal_runs(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "four-stage.sqlite")
    for status in ("active", "held", "stopping", "completed", "stopped"):
        await store.create(
            status,
            status,
            "key",
            "f",
            {"status": status, "wake_at": utc_text(NOW + timedelta(days=1))},
        )
    assert await store.list_due(NOW) == ()
    assert {row.id for row in await store.list_due(NOW, include_waiting=True)} == {
        "active",
        "held",
        "stopping",
    }
    await store.close()


@pytest.mark.parametrize("marker", [None, "cddai-agent-tasks-1", "cddai-agent-tasks-2", "future"])
def test_old_or_unknown_database_rejected_without_changes(
    tmp_path: Path, marker: str | None
) -> None:
    path = tmp_path / "old.sqlite"
    with closing(sqlite3.connect(path, isolation_level=None)) as raw:
        raw.execute("CREATE TABLE cddai_metadata (key TEXT PRIMARY KEY, value TEXT)")
        if marker is not None:
            raw.execute("INSERT INTO cddai_metadata VALUES ('format', ?)", (marker,))
    before = path.read_bytes()
    with pytest.raises(StoreError, match="unsupported"):
        SQLiteStore(path)
    assert path.read_bytes() == before


def test_unrelated_database_rejected_without_changes(tmp_path: Path) -> None:
    path = tmp_path / "unrelated.sqlite"
    with closing(sqlite3.connect(path, isolation_level=None)) as raw:
        raw.execute("CREATE TABLE snapshots (data TEXT)")
    before = path.read_bytes()
    with pytest.raises(StoreError, match="incompatible"):
        SQLiteStore(path)
    assert path.read_bytes() == before


async def test_invalid_inputs_and_not_found(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "four-stage.sqlite")
    for data in (
        {},
        {"status": "unknown"},
        {"status": "active", "wake_at": 1},
        {"status": "active", "wake_at": "2026-10-20T00:00:00"},
        {"status": "active", "wake_at": "2026-10-20T00:00:00+00:00"},
        {"status": "active", "tasks": []},
        {"status": "active", "task": {}},
        {"status": "active", "current": "missing"},
        {"status": "active", "task": task(1), "current": "other"},
    ):
        with pytest.raises(ValueError):
            await store.create("run", "project", "key", "f", data)
    with pytest.raises(ValueError):
        await store.create("", "project", "key", "f", {"status": "active"})
    for method in (store.get, store.history, store.tasks):
        with pytest.raises(NotFoundError):
            await method("missing")
    with pytest.raises(NotFoundError):
        await store.acquire("missing", "worker", NOW)
    with pytest.raises(ValueError):
        await store.acquire("missing", "worker", NOW, seconds=0)
    with pytest.raises(ValueError, match="UTC offset"):
        await store.list_due(datetime(2026, 10, 20))
    for limit, after in ((0, 0), (10001, 0), (True, 0), (1, -1), (1, True)):
        with pytest.raises(ValueError):
            await store.tasks("missing", limit=limit, after=after)
    assert await store.verify_audit()
    await store.close()


async def test_crash_before_commit_preserves_current_projection(tmp_path: Path) -> None:
    path = tmp_path / "four-stage.sqlite"
    store = SQLiteStore(path)
    record = await store.create("run", "project", "key", "f", {"status": "active"})
    await store.close()
    raw = sqlite3.connect(path)
    raw.execute("BEGIN IMMEDIATE")
    raw.execute("UPDATE runs SET status = 'completed', revision = 100")
    raw.close()
    reopened = SQLiteStore(path)
    assert await reopened.get("run") == record
    assert await reopened.verify_audit()
    await reopened.close()


async def test_validation_cache_tracks_external_and_direct_changes(tmp_path: Path) -> None:
    path = tmp_path / "four-stage.sqlite"
    store = SQLiteStore(path)
    record = await store.create("run", "project", "key", "f", {"status": "active"})
    with patch.object(store, "_valid", wraps=store._valid) as validate:
        await store.get("run")
        await store.save(record, {"status": "held"}, "held", "operator", NOW)
        assert validate.call_count == 0
        assert await store.verify_audit()
        assert validate.call_count == 1
        with closing(sqlite3.connect(path, isolation_level=None)) as raw:
            raw.execute("UPDATE runs SET fence = fence + 1")
        await store.get("run")
        assert validate.call_count == 2
    store._connection.execute("DROP TABLE events")
    with pytest.raises(StoreError):
        await store.get("run")
    await store.close()


async def test_digest_replacement_without_committing_event_fails(tmp_path: Path) -> None:
    path = tmp_path / "four-stage.sqlite"
    store = SQLiteStore(path)
    await store.create("run", "project", "key", "f", {"status": "active"})
    forged = {"status": "held"}
    with closing(sqlite3.connect(path, isolation_level=None)) as raw:
        raw.execute(
            "UPDATE runs SET data = ?, data_digest = ?, status = 'held'",
            (canonical_text(forged), canonical_hash(forged)),
        )
    with pytest.raises(StoreError):
        await store.get("run")
    await store.close()


async def test_old_valid_task_projection_cannot_replace_current_task(tmp_path: Path) -> None:
    path = tmp_path / "four-stage.sqlite"
    store = SQLiteStore(path)
    record = await store.create("run", "project", "key", "f", {"status": "active", "task": task(1)})
    with closing(sqlite3.connect(path)) as raw:
        original = raw.execute("SELECT data, digest, last_seq FROM tasks").fetchone()
    await store.save(
        record, {"status": "active", "task": task(1, result=True)}, "result", "worker", NOW
    )
    await store.close()
    with closing(sqlite3.connect(path, isolation_level=None)) as raw:
        raw.execute("UPDATE tasks SET data = ?, digest = ?, last_seq = ?", original)
    with pytest.raises(StoreError):
        SQLiteStore(path)


async def test_linear_1250_2500_invocations_and_indexed_reopen(tmp_path: Path) -> None:
    measurements = []
    for count in (1250, 2500):
        path = tmp_path / f"invocations-{count}.sqlite"
        store = SQLiteStore(path)
        record = await store.create("run", "project", "key", "f", {"status": "active"})
        for number in range(count):
            entry = task(number, result=True)
            entry["task"]["instructions"] = "Frozen product instructions. " * 100
            entry["result"]["checkpoint"] = "Retained checkpoint content. " * 100
            record = await store.save(
                record,
                {"status": "active", "task": entry, "current": None},
                "accepted",
                "worker",
                NOW,
            )
        await store.close()
        queries: list[str] = []
        connect = sqlite3.connect

        def traced_connect(
            *args: Any, _connect: Any = connect, _queries: list[str] = queries, **kwargs: Any
        ) -> sqlite3.Connection:
            connection = _connect(*args, **kwargs)
            connection.set_trace_callback(_queries.append)
            return connection

        tracemalloc.start()
        started = time.perf_counter()
        with patch("aced.store.sqlite3.connect", side_effect=traced_connect):
            reopened = SQLiteStore(path)
        assert (await reopened.list_due(NOW))[0] == record
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert elapsed < 10
        assert not any(
            "FROM events ORDER BY seq" in query and "LIMIT" not in query for query in queries
        )
        assert not any("SELECT * FROM tasks" in query and "WHERE" not in query for query in queries)
        assert len(queries) < 50
        with closing(sqlite3.connect(path)) as raw:
            assert raw.execute("SELECT count(*) FROM tasks").fetchone()[0] == count
            assert (
                raw.execute("SELECT count(*) FROM records WHERE kind = 'task'").fetchone()[0]
                == count
            )
            assert (
                raw.execute("SELECT count(*) FROM records WHERE kind = 'result'").fetchone()[0]
                == count
            )
        measurements.append((count, path.stat().st_size, elapsed, peak))
        assert await reopened.verify_audit()
        await reopened.close()
    assert measurements[1][1] / measurements[0][1] <= 2.5
    print(
        "compact SQLite benchmark (invocations, bytes, reopen+due seconds, traced peak bytes): "
        f"{measurements}"
    )
