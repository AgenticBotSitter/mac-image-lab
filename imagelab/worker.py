"""Persistent single-worker execution for image generation."""

from __future__ import annotations

import argparse
import fcntl
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from imagelab.db import initialize_database
from imagelab.repositories.jobs import JobRepository
from imagelab.services.recovery import RecoverableBackend, RecoveryCoordinator


class WorkerAlreadyRunning(RuntimeError):
    pass


class WorkerLeadership:
    """Advisory process lock ensuring one heavyweight worker owner."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._file: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise WorkerAlreadyRunning("another generation worker owns the lock") from exc
        self._file = handle

    def release(self) -> None:
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
            self._file = None

    def __enter__(self) -> "WorkerLeadership":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


class PersistentWorker:
    def __init__(
        self,
        database_path: Path,
        *,
        execute_generation: Callable[[str], None] | None = None,
        backend: RecoverableBackend | None = None,
    ):
        if (execute_generation is None) == (backend is None):
            raise ValueError("configure exactly one generation executor or recoverable backend")
        self.database_path = Path(database_path)
        self.execute_generation = execute_generation
        self.backend = backend

    def run_once(self) -> bool:
        connection = initialize_database(self.database_path)
        try:
            repository = JobRepository(connection)
            job = repository.active()
            if job is not None and job["state"] == "needs_attention":
                return False
            if job is None:
                job = repository.claim_next()
            if job is None:
                return False
            if self.backend is not None:
                RecoveryCoordinator(repository, self.backend).step(job)
                return True
            try:
                assert self.execute_generation is not None
                self.execute_generation(job["run_id"])
            except Exception as exc:
                repository.fail(job["id"], exc)
            else:
                repository.succeed(job["id"])
            return True
        finally:
            connection.close()

    def run_forever(self, *, poll_seconds: float = 1.0) -> None:
        while True:
            self.run_once()
            time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Mac Image Lab generation worker")
    parser.add_argument("--database", type=Path, default=Path(__file__).parents[1] / "state/library.sqlite3")
    parser.add_argument("--lock", type=Path, default=Path(__file__).parents[1] / "state/worker.lock")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    # Imported only by the worker entry point; the web module never starts a worker.
    from app.app import recovery_backend

    worker = PersistentWorker(args.database, backend=recovery_backend())
    try:
        with WorkerLeadership(args.lock):
            if args.once:
                worker.run_once()
            else:
                worker.run_forever()
    except WorkerAlreadyRunning as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
