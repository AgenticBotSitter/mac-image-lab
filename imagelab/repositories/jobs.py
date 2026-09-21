"""Persistent generation-job repository."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _job(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class JobRepository:
    """Transactional queue operations over the shared SQLite database."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def _event(self, job_id: str, event_type: str, detail: dict[str, Any] | None = None) -> None:
        self.connection.execute(
            "INSERT INTO job_events(job_id, event_type, detail_json, created_at) VALUES(?,?,?,?)",
            (job_id, event_type, json.dumps(detail or {}, sort_keys=True), utc_now()),
        )

    def enqueue(self, run_id: str, kind: str, idempotency_key: str, *, priority: int = 100) -> tuple[dict[str, Any], bool]:
        key = idempotency_key.strip()
        if not key or len(key) > 200:
            raise ValueError("A valid idempotency key is required")
        existing = self.connection.execute(
            "SELECT * FROM jobs WHERE idempotency_key = ? OR (run_id = ? AND kind = ?) ORDER BY created_at LIMIT 1",
            (key, run_id, kind),
        ).fetchone()
        if existing is not None:
            return dict(existing), False
        job_id = str(uuid.uuid4())
        timestamp = utc_now()
        try:
            self.connection.execute(
                """INSERT INTO jobs(
                       id, run_id, kind, state, priority, idempotency_key,
                       created_at, updated_at
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (job_id, run_id, kind, "queued", priority, key, timestamp, timestamp),
            )
        except sqlite3.IntegrityError:
            existing = self.connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ? OR (run_id = ? AND kind = ?) ORDER BY created_at LIMIT 1",
                (key, run_id, kind),
            ).fetchone()
            if existing is None:
                raise
            return dict(existing), False
        self._event(job_id, "queued", {"kind": kind})
        return dict(self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()), True

    def get(self, job_id: str) -> dict[str, Any] | None:
        return _job(self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def get_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        return _job(
            self.connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        )

    def list(self, *, state: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if state is None:
            rows = self.connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
            )
        else:
            rows = self.connection.execute(
                "SELECT * FROM jobs WHERE state = ? ORDER BY created_at, id LIMIT ?", (state, limit)
            )
        return [dict(row) for row in rows]

    def count(self, *, state: str | None = None) -> int:
        if state is None:
            row = self.connection.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()
        else:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE state = ?", (state,)
            ).fetchone()
        return int(row["count"])

    def claim_next(self) -> dict[str, Any] | None:
        """Atomically claim one queued job for the sole generation worker."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            active = self.connection.execute(
                "SELECT 1 FROM jobs WHERE state IN ('submitting', 'running', 'needs_attention') LIMIT 1"
            ).fetchone()
            if active is not None:
                self.connection.commit()
                return None
            row = self.connection.execute(
                """SELECT * FROM jobs
                   WHERE state = 'queued'
                   ORDER BY priority ASC, created_at ASC, id ASC
                   LIMIT 1"""
            ).fetchone()
            if row is None:
                self.connection.commit()
                return None
            timestamp = utc_now()
            cursor = self.connection.execute(
                """UPDATE jobs
                   SET state = 'running', started_at = COALESCE(started_at, ?),
                       heartbeat_at = ?, attempt_count = attempt_count + 1,
                       updated_at = ?
                   WHERE id = ? AND state = 'queued'""",
                (timestamp, timestamp, timestamp, row["id"]),
            )
            if cursor.rowcount != 1:
                self.connection.rollback()
                return None
            self._event(row["id"], "claimed")
            self.connection.commit()
            return dict(self.connection.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())
        except Exception:
            self.connection.rollback()
            raise

    def succeed(self, job_id: str) -> None:
        timestamp = utc_now()
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE jobs SET state='succeeded', completed_at=?, heartbeat_at=?,
                   updated_at=?, error_type=NULL, error_message=NULL
                   WHERE id=? AND state='running'""",
                (timestamp, timestamp, timestamp, job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
            self._event(job_id, "succeeded")

    def fail(self, job_id: str, error: BaseException) -> None:
        timestamp = utc_now()
        message = str(error)[:2000]
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE jobs SET state='failed', completed_at=?, heartbeat_at=?,
                   updated_at=?, error_type=?, error_message=?
                   WHERE id=? AND state='running'""",
                (timestamp, timestamp, timestamp, type(error).__name__, message, job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
            self._event(job_id, "failed", {"error_type": type(error).__name__, "message": message})

    def events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT event.* FROM job_events AS event
               JOIN jobs AS job ON job.id = event.job_id
               WHERE job.run_id = ? ORDER BY event.id""",
            (run_id,),
        )
        return [dict(row) for row in rows]
