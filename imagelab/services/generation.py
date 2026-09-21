"""Generation queue service used by the web application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from imagelab.db import initialize_database
from imagelab.repositories.jobs import JobRepository


def enqueue_generation(database_path: Path, run_id: str, idempotency_key: str) -> tuple[dict[str, Any], bool]:
    connection = initialize_database(database_path)
    try:
        with connection:
            return JobRepository(connection).enqueue(run_id, "generation", idempotency_key)
    finally:
        connection.close()


def queue_depth(database_path: Path) -> int:
    if not Path(database_path).exists():
        return 0
    connection = initialize_database(database_path)
    try:
        repository = JobRepository(connection)
        return repository.count(state="queued") + repository.count(state="running")
    finally:
        connection.close()
