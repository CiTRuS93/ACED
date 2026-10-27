"""Compact SQLite projections, immutable task records, and a chained audit log.

Opening a database checks the active recovery surface, not every historical event.
``verify_audit`` explicitly verifies all retained content. Native product receipts
remain authoritative; this audit detects accidental modification, not hostile access.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aced._json import canonical_hash, canonical_link_hash, canonical_text, parse_text, utc_text

# Branding changes do not change persisted identities or the compatible store format.
_FORMAT = "cddai-four-stage-1"
_STATES = frozenset({"active", "held", "stopping", "stopped", "completed"})
_RECORD_FIELDS = ("task", "result", "verification", "checkpoint", "learning")


class StoreError(RuntimeError):
    """Persistence is unavailable, incompatible, or corrupt."""


class ConflictError(StoreError):
    """An identity, resource owner, or optimistic revision conflicts."""


class StaleLeaseError(ConflictError):
    """A worker no longer owns an unexpired execution lease."""


class NotFoundError(StoreError):
    """The requested run does not exist."""


@dataclass(frozen=True)
class Record:
    id: str
    project_id: str
    key: str
    fingerprint: str
    revision: int
    data: dict[str, Any]


@dataclass(frozen=True)
class Lease:
    run_id: str
    owner: str
    fence: int
    expires_at: datetime


def _data(value: Mapping[str, Any]) -> dict[str, Any]:
    result = parse_text(canonical_text(value))
    if not isinstance(result, dict) or result.get("status") not in _STATES:
        raise ValueError("run data requires a recognized status")
    if "tasks" in result:
        raise ValueError("run data holds one task; inspect retained tasks through tasks()")
    wake = result.get("wake_at")
    if wake is not None and (not isinstance(wake, str) or utc_text(wake) != wake):
        raise ValueError("wake_at must use canonical UTC timestamp text")
    return result


def _nonempty(*values: str) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("identifiers, events, and actors must be nonempty strings")


def _page(limit: int, after: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10000:
        raise ValueError("page limit must be between 1 and 10000")
    if isinstance(after, bool) or not isinstance(after, int) or after < 0:
        raise ValueError("page cursor must be a nonnegative sequence")


def _resource(data: Mapping[str, Any], project_id: str) -> str:
    config = data.get("config", {})
    resource = config.get("resource_id", project_id) if isinstance(config, dict) else project_id
    _nonempty(resource)
    return str(resource)


def _changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "set": {
            key: value for key, value in after.items() if key not in before or before[key] != value
        },
        "remove": sorted(before.keys() - after.keys()),
    }


def _apply_changes(before: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(before)
    for key in changes["remove"]:
        del result[key]
    result.update(changes["set"])
    return result


class SQLiteStore:
    """One database with a durable task outbox and resource ownership through cleanup."""

    def __init__(self, path: str | Path) -> None:
        self._connection = sqlite3.connect(str(path), isolation_level=None, timeout=5)
        self._connection.row_factory = sqlite3.Row
        self._verified_stamp: tuple[int, int, int] | None = None
        self._corrupt = False
        try:
            self._initialize()
            self._connection.execute("PRAGMA foreign_keys = ON")
        except Exception:
            self._connection.close()
            raise

    def _initialize(self) -> None:
        with self._transaction(write=True):
            objects = {
                row[0]
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                )
            }
            if objects:
                if "cddai_metadata" not in objects:
                    raise StoreError("existing database belongs to an incompatible ACED format")
                marker = self._connection.execute(
                    "SELECT value FROM cddai_metadata WHERE key = 'format'"
                ).fetchone()
                if marker is None or marker[0] != _FORMAT:
                    raise StoreError("unsupported ACED database format; use a fresh database")
                self._require_valid()
                return
            statements = (
                "CREATE TABLE cddai_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                """CREATE TABLE runs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, resource_id TEXT NOT NULL,
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision >= 0), status TEXT NOT NULL,
                    wake_at TEXT, data TEXT NOT NULL, data_digest TEXT NOT NULL,
                    latest_hash TEXT NOT NULL, last_seq INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT, fence INTEGER NOT NULL DEFAULT 0 CHECK(fence >= 0),
                    lease_expires TEXT, UNIQUE(project_id, request_key)
                )""",
                """CREATE UNIQUE INDEX one_nonterminal_run ON runs(project_id)
                   WHERE status NOT IN ('stopped', 'completed')""",
                """CREATE UNIQUE INDEX one_resource_owner ON runs(resource_id)
                   WHERE status NOT IN ('stopped', 'completed')""",
                """CREATE INDEX due_runs ON runs(wake_at, id)
                   WHERE status NOT IN ('stopped', 'completed')""",
                """CREATE TABLE records (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, digest TEXT NOT NULL,
                    content TEXT NOT NULL
                )""",
                """CREATE TABLE tasks (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id), id TEXT NOT NULL,
                    data TEXT NOT NULL, digest TEXT NOT NULL, last_seq INTEGER NOT NULL,
                    UNIQUE(run_id, id)
                )""",
                "CREATE INDEX tasks_by_run ON tasks(run_id, seq)",
                """CREATE TABLE events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id), revision INTEGER NOT NULL,
                    payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL,
                    UNIQUE(run_id, revision)
                )""",
                "CREATE INDEX events_by_run ON events(run_id, seq)",
            )
            for statement in statements:
                self._connection.execute(statement)
            self._connection.executemany(
                "INSERT INTO cddai_metadata(key, value) VALUES (?, ?)",
                (("format", _FORMAT), ("last_seq", "0"), ("last_hash", ""), ("run_count", "0")),
            )

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[None]:
        try:
            self._connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield
            if write and self._verified_stamp is not None:
                self._verified_stamp = self._stamp()
            self._connection.commit()
        except BaseException as error:
            self._verified_stamp = None
            self._connection.rollback()
            if isinstance(error, sqlite3.IntegrityError):
                raise ConflictError(str(error)) from error
            if isinstance(error, sqlite3.Error):
                raise StoreError(str(error)) from error
            raise

    def _get(self, run_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = self._connection.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"run {run_id!r} does not exist")
        return row

    def _read_record(self, reference: Mapping[str, str]) -> Any:
        row = self._connection.execute(
            "SELECT * FROM records WHERE id = ?", (reference["id"],)
        ).fetchone()
        if (
            row is None
            or row["digest"] != reference["digest"]
            or row["kind"] != reference["kind"]
            or row["id"] != f"{row['kind']}:{row['digest']}"
            or canonical_hash(row["content"].encode()) != row["digest"]
        ):
            raise ValueError("immutable record identity or digest mismatch")
        content = parse_text(row["content"])
        if canonical_text(content) != row["content"]:
            raise ValueError("immutable record must be canonical")
        return content

    def _put_record(self, kind: str, value: Any) -> dict[str, str]:
        content = canonical_text(value)
        digest = canonical_hash(content.encode())
        reference = {"id": f"{kind}:{digest}", "kind": kind, "digest": digest}
        self._connection.execute(
            "INSERT OR IGNORE INTO records(id, kind, digest, content) VALUES (?, ?, ?, ?)",
            (reference["id"], kind, digest, content),
        )
        # Do not silently reuse corrupted content-addressed records.
        self._read_record(reference)
        return reference

    def _task(self, run_id: str, task_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = self._connection.execute(
            "SELECT * FROM tasks WHERE run_id = ? AND id = ?", (run_id, task_id)
        ).fetchone()
        if row is None:
            raise ValueError("run references a missing task")
        return row

    def _task_entry(self, row: sqlite3.Row) -> dict[str, Any]:
        compact = parse_text(row["data"])
        if canonical_text(compact) != row["data"] or canonical_hash(compact) != row["digest"]:
            raise ValueError("task projection digest mismatch")
        entry = dict(compact["metadata"])
        for field, reference in compact["records"].items():
            entry[field] = self._read_record(reference)
        if entry["task"]["id"] != row["id"]:
            raise ValueError("task identity mismatch")
        event = self._event(row["last_seq"])
        if (
            event["id"] != row["run_id"]
            or event["task_id"] != row["id"]
            or event["task_digest"] != row["digest"]
        ):
            raise ValueError("task projection is not bound to its committing event")
        return entry

    def _record(self, row: sqlite3.Row) -> Record:
        try:
            data = _data(parse_text(row["data"]))
            _nonempty(row["id"], row["project_id"], row["request_key"], row["fingerprint"])
            if (
                canonical_text(data) != row["data"]
                or canonical_hash(data) != row["data_digest"]
                or data["status"] != row["status"]
                or data.get("wake_at") != row["wake_at"]
                or _resource(data, row["project_id"]) != row["resource_id"]
                or row["fence"] < 0
                or (row["lease_owner"] is None) != (row["lease_expires"] is None)
            ):
                raise ValueError("run projection mismatch")
            if row["lease_expires"] is not None:
                _nonempty(row["lease_owner"])
                if utc_text(row["lease_expires"]) != row["lease_expires"]:
                    raise ValueError("invalid lease expiry")
            event = self._event(row["last_seq"])
            if any(
                event[name] != row[column]
                for name, column in (
                    ("id", "id"),
                    ("project_id", "project_id"),
                    ("key", "request_key"),
                    ("fingerprint", "fingerprint"),
                    ("revision", "revision"),
                    ("data_digest", "data_digest"),
                    ("hash", "latest_hash"),
                )
            ):
                raise ValueError("run projection is not bound to its committing event")
            if data.get("task") is not None:
                task_id = data["task"]["task_id"]
                if data.get("current") not in (None, task_id):
                    raise ValueError("current task does not match task projection")
                current_task = self._task(row["id"], task_id)
                if event["task_id"] != task_id or event["task_digest"] != current_task["digest"]:
                    raise ValueError("run and task projections disagree")
                data["task"] = self._task_entry(current_task)
            elif event["task_id"] is not None or data.get("current") is not None:
                raise ValueError("current task is missing")
            return Record(
                row["id"],
                row["project_id"],
                row["request_key"],
                row["fingerprint"],
                row["revision"],
                data,
            )
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise StoreError(
                "database projection or referenced record verification failed"
            ) from error

    def _event(self, sequence: int) -> dict[str, Any]:
        row = self._connection.execute("SELECT * FROM events WHERE seq = ?", (sequence,)).fetchone()
        if row is None:
            raise ValueError("missing audit event")
        payload = parse_text(row["payload"])
        if (
            not isinstance(payload, dict)
            or canonical_text(payload) != row["payload"]
            or canonical_link_hash(row["previous_hash"], row["payload"]) != row["hash"]
            or payload["seq"] != sequence
            or payload["id"] != row["run_id"]
            or payload["revision"] != row["revision"]
            or utc_text(payload["at"]) != payload["at"]
        ):
            raise ValueError("audit event digest or identity mismatch")
        _nonempty(payload["event"], payload["actor"])
        return dict(payload, hash=row["hash"], previous_hash=row["previous_hash"])

    def _valid(self, *, full: bool = False) -> bool:
        try:
            metadata = dict(self._connection.execute("SELECT key, value FROM cddai_metadata"))
            if metadata.get("format") != _FORMAT:
                return False
            tail = self._connection.execute(
                "SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1"
            )
            last = tail.fetchone()
            sequence, digest = (0, "") if last is None else (last["seq"], last["hash"])
            if metadata.get("last_seq") != str(sequence) or metadata.get("last_hash") != digest:
                return False
            if sequence:
                tail_event = self._event(sequence)
                if str(tail_event["run_count"]) != metadata.get("run_count"):
                    return False
            run_count = self._connection.execute("SELECT count(*) FROM runs").fetchone()[0]
            if metadata.get("run_count") != str(run_count):
                return False
            # Validate indexed run projections, including terminal statuses: otherwise
            # corruption could hide an active owner by changing its status. This
            # does not scan historical task or event content.
            for row in self._connection.execute("SELECT * FROM runs"):
                self._record(row)
            if not full:
                return True
            previous = ""
            revisions: dict[str, int] = {}
            projections: dict[str, dict[str, Any]] = {}
            task_projections: dict[tuple[str, str], dict[str, Any]] = {}
            for expected, row in enumerate(
                self._connection.execute("SELECT seq FROM events ORDER BY seq"), 1
            ):
                event = self._event(row["seq"])
                if (
                    event["seq"] != expected
                    or event["previous_hash"] != previous
                    or event["revision"] != revisions.get(event["id"], -1) + 1
                ):
                    return False
                run = self._get(event["id"])
                if any(
                    event[key] != run[column]
                    for key, column in (
                        ("project_id", "project_id"),
                        ("key", "request_key"),
                        ("fingerprint", "fingerprint"),
                    )
                ):
                    return False
                projection = _data(
                    _apply_changes(projections.get(event["id"], {}), event["changes"])
                )
                if canonical_hash(projection) != event["data_digest"]:
                    return False
                projections[event["id"]] = projection
                if event["task_id"] is not None:
                    task_key = (event["id"], event["task_id"])
                    before = task_projections.get(task_key, {})
                    task_projection = {
                        field: _apply_changes(before.get(field, {}), event["task_changes"][field])
                        for field in ("metadata", "records")
                    }
                    if canonical_hash(task_projection) != event["task_digest"]:
                        return False
                    task_projections[task_key] = task_projection
                for reference in event["record_refs"]:
                    self._read_record(reference)
                revisions[event["id"]] = event["revision"]
                previous = event["hash"]
            if any(
                revisions.get(row["id"]) != row["revision"]
                for row in self._connection.execute("SELECT id, revision FROM runs")
            ):
                return False
            actual_task_keys = set()
            for row in self._connection.execute("SELECT * FROM tasks"):
                actual_task_keys.add((row["run_id"], row["id"]))
                self._task_entry(row)
                if task_projections.get((row["run_id"], row["id"])) != parse_text(row["data"]):
                    return False
            if actual_task_keys != set(task_projections):
                return False
            for row in self._connection.execute("SELECT id, kind, digest FROM records"):
                self._read_record(dict(row))
            return True
        except (
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            OverflowError,
            sqlite3.Error,
            StoreError,
        ):
            return False

    def _stamp(self) -> tuple[int, int, int]:
        return (
            int(self._connection.execute("PRAGMA data_version").fetchone()[0]),
            self._connection.total_changes,
            int(self._connection.execute("PRAGMA schema_version").fetchone()[0]),
        )

    def _require_valid(self) -> None:
        self._connection.execute(
            "SELECT value FROM cddai_metadata WHERE key = 'last_hash'"
        ).fetchone()
        stamp = self._stamp()
        if self._corrupt or (stamp != self._verified_stamp and not self._valid()):
            self._corrupt = True
            raise StoreError("database projection or audit verification failed")
        self._verified_stamp = stamp

    def _project_task(self, run_id: str, data: dict[str, Any], sequence: int) -> dict[str, Any]:
        entry = data.get("task")
        if entry is None:
            if data.get("current") is not None:
                raise ValueError("current task is missing")
            return {"task_id": None, "task_digest": None, "record_refs": [], "task_changes": None}
        if not isinstance(entry, dict) or not isinstance(entry.get("task"), dict):
            raise ValueError("task entry requires immutable task inputs")
        task_id = entry["task"].get("id")
        _nonempty(task_id)
        if data.get("current") not in (None, task_id):
            raise ValueError("current task does not match task entry")
        old = self._connection.execute(
            "SELECT * FROM tasks WHERE run_id = ? AND id = ?", (run_id, task_id)
        ).fetchone()
        if old is not None:
            previous = self._task_entry(old)
            for field in ("task", "result"):
                if previous.get(field) is not None and previous[field] != entry.get(field):
                    raise ConflictError(f"retained task {field} is immutable")
        references = {
            field: self._put_record(field, entry[field])
            for field in _RECORD_FIELDS
            if entry.get(field) is not None
        }
        compact = {
            "metadata": {key: value for key, value in entry.items() if key not in references},
            "records": references,
        }
        before = {} if old is None else parse_text(old["data"])
        changes = {
            field: _changes(before.get(field, {}), compact[field])
            for field in ("metadata", "records")
        }
        digest = canonical_hash(compact)
        self._connection.execute(
            """INSERT INTO tasks(run_id, id, data, digest, last_seq) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(run_id, id) DO UPDATE SET
                   data = excluded.data, digest = excluded.digest, last_seq = excluded.last_seq""",
            (run_id, task_id, canonical_text(compact), digest, sequence),
        )
        data["task"] = {"task_id": task_id}
        return {
            "task_id": task_id,
            "task_digest": digest,
            "record_refs": list(references.values()),
            "task_changes": changes,
        }

    def _persist(self, record: Record, event: str, actor: str, now: datetime) -> None:
        metadata = dict(self._connection.execute("SELECT key, value FROM cddai_metadata"))
        sequence = int(metadata["last_seq"]) + 1
        data = _data(record.data)
        task = self._project_task(record.id, data, sequence)
        data_digest = canonical_hash(data)
        payload = {
            "seq": sequence,
            "id": record.id,
            "project_id": record.project_id,
            "key": record.key,
            "fingerprint": record.fingerprint,
            "revision": record.revision,
            "event": event,
            "actor": actor,
            "at": utc_text(now),
            "data_digest": data_digest,
            "changes": _changes(parse_text(self._get(record.id)["data"]), data),
            "run_count": int(metadata["run_count"]),
            **task,
        }
        serialized = canonical_text(payload)
        digest = canonical_link_hash(metadata["last_hash"], serialized)
        self._connection.execute(
            """INSERT INTO events(seq, run_id, revision, payload, previous_hash, hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sequence, record.id, record.revision, serialized, metadata["last_hash"], digest),
        )
        self._connection.execute(
            """UPDATE runs SET revision = ?, status = ?, wake_at = ?, data = ?,
                   data_digest = ?, latest_hash = ?, last_seq = ? WHERE id = ?""",
            (
                record.revision,
                data["status"],
                data.get("wake_at"),
                canonical_text(data),
                data_digest,
                digest,
                sequence,
                record.id,
            ),
        )
        self._connection.executemany(
            "UPDATE cddai_metadata SET value = ? WHERE key = ?",
            ((str(sequence), "last_seq"), (digest, "last_hash")),
        )

    async def create(
        self, id: str, project_id: str, key: str, fingerprint: str, data: Mapping[str, Any]
    ) -> Record:
        _nonempty(id, project_id, key, fingerprint)
        record = Record(id, project_id, key, fingerprint, 0, _data(data))
        with self._transaction(write=True):
            self._require_valid()
            self._connection.execute(
                """INSERT INTO runs(id, project_id, resource_id, request_key, fingerprint,
                   revision, status, data, data_digest, latest_hash)
                   VALUES (?, ?, ?, ?, ?, 0, ?, '{}', '', '')""",
                (
                    id,
                    project_id,
                    _resource(record.data, project_id),
                    key,
                    fingerprint,
                    record.data["status"],
                ),
            )
            self._connection.execute(
                "UPDATE cddai_metadata SET value = CAST(value AS INTEGER) + 1 "
                "WHERE key = 'run_count'"
            )
            self._persist(record, "created", "system", datetime.now(UTC))
        return record

    async def get(self, id: str) -> Record:
        with self._transaction():
            self._require_valid()
            return self._record(self._get(id))

    async def find(self, project_id: str, key: str) -> Record | None:
        with self._transaction():
            self._require_valid()
            row = self._connection.execute(
                "SELECT * FROM runs WHERE project_id = ? AND request_key = ?", (project_id, key)
            ).fetchone()
            return None if row is None else self._record(row)

    async def list_runs(
        self, project_id: str, *, limit: int = 100, after: int = 0
    ) -> tuple[tuple[int, str], ...]:
        """Page identities by immutable creation-event sequence, without schema changes."""
        _page(limit, after)
        with self._transaction():
            self._require_valid()
            return tuple(
                (row["seq"], row["id"])
                for row in self._connection.execute(
                    """SELECT e.seq, r.id FROM runs r JOIN events e ON e.run_id = r.id
                       AND e.revision = 0 WHERE r.project_id = ? AND e.seq > ?
                       ORDER BY e.seq LIMIT ?""",
                    (project_id, after, limit),
                )
            )

    async def list_due(self, now: datetime, *, include_waiting: bool = False) -> tuple[Record, ...]:
        """Select due work, or all live projections for independent safety checks."""
        timestamp = utc_text(now)
        with self._transaction():
            self._require_valid()
            return tuple(
                self._record(row)
                for row in self._connection.execute(
                    """SELECT * FROM runs WHERE status NOT IN ('stopped', 'completed')
                       AND (? OR wake_at IS NULL OR wake_at <= ?) ORDER BY id""",
                    (include_waiting, timestamp),
                )
            )

    async def acquire(self, id: str, owner: str, now: datetime, seconds: int = 60) -> Lease | None:
        _nonempty(owner)
        timestamp = utc_text(now)
        if seconds <= 0:
            raise ValueError("lease duration must be positive")
        expires = utc_text(now + timedelta(seconds=seconds))
        with self._transaction(write=True):
            self._require_valid()
            row = self._get(id)
            self._record(row)
            if row["lease_expires"] is not None and row["lease_expires"] > timestamp:
                return None
            fence = row["fence"] + 1
            self._connection.execute(
                "UPDATE runs SET lease_owner = ?, fence = ?, lease_expires = ? WHERE id = ?",
                (owner, fence, expires, id),
            )
            return Lease(id, owner, fence, datetime.fromisoformat(expires))

    async def save(
        self,
        record: Record,
        data: Mapping[str, Any],
        event: str,
        actor: str,
        now: datetime,
        lease: Lease | None = None,
    ) -> Record:
        _nonempty(event, actor)
        timestamp = utc_text(now)
        updated = Record(
            record.id,
            record.project_id,
            record.key,
            record.fingerprint,
            record.revision + 1,
            _data(data),
        )
        with self._transaction(write=True):
            self._require_valid()
            row = self._get(record.id)
            self._record(row)
            if lease is not None and (
                lease.run_id != record.id
                or row["lease_owner"] != lease.owner
                or row["fence"] != lease.fence
                or row["lease_expires"] is None
                or row["lease_expires"] <= timestamp
                or utc_text(lease.expires_at) != row["lease_expires"]
            ):
                raise StaleLeaseError("worker lease is expired or has been superseded")
            if (
                row["revision"] != record.revision
                or row["project_id"] != record.project_id
                or row["request_key"] != record.key
                or row["fingerprint"] != record.fingerprint
                or row["resource_id"] != _resource(updated.data, record.project_id)
            ):
                raise ConflictError("run identity, resource, or revision has changed")
            if updated.data == self._record(row).data:
                return self._record(row)
            self._persist(updated, event, actor, now)
        return updated

    async def release(self, lease: Lease) -> None:
        with self._transaction(write=True):
            self._require_valid()
            self._connection.execute(
                """UPDATE runs SET lease_owner = NULL, lease_expires = NULL
                   WHERE id = ? AND lease_owner = ? AND fence = ?""",
                (lease.run_id, lease.owner, lease.fence),
            )

    async def tasks(
        self, id: str, *, limit: int = 100, after: int = 0
    ) -> tuple[dict[str, Any], ...]:
        """Return retained entries with ``seq`` cursors in task creation order."""
        _page(limit, after)
        with self._transaction():
            self._require_valid()
            self._get(id)
            return tuple(
                dict(self._task_entry(row), seq=row["seq"])
                for row in self._connection.execute(
                    "SELECT * FROM tasks WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                    (id, after, limit),
                )
            )

    async def history(
        self, id: str, *, limit: int = 100, after: int = 0
    ) -> tuple[dict[str, Any], ...]:
        """Return compact changes; ``seq`` is the exclusive cursor for the next page."""
        _page(limit, after)
        with self._transaction():
            self._require_valid()
            self._get(id)
            return tuple(
                self._event(row["seq"])
                for row in self._connection.execute(
                    "SELECT seq FROM events WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                    (id, after, limit),
                )
            )

    async def verify_audit(self) -> bool:
        """Explicitly scan the complete audit, retained tasks and immutable records."""
        with self._transaction():
            valid = self._valid(full=True)
            self._corrupt = not valid
            self._verified_stamp = self._stamp() if valid else None
            return valid

    async def close(self) -> None:
        self._connection.close()
