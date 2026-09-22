from pathlib import Path

from imagelab.db import initialize_database
from imagelab.repositories.jobs import JobRepository
from imagelab.repositories.runs import RunRepository
from imagelab.runtime import IdleSleepAssertion, rotate_logs_copytruncate
from imagelab.worker import PersistentWorker


class FakeAssertion:
    def __init__(self):
        self.states = []

    def set_active(self, active):
        self.states.append(active)

    def release(self):
        self.states.append(False)


def seed_job(path: Path):
    connection = initialize_database(path)
    run_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    RunRepository(connection).upsert_receipt(
        {
            "run_id": run_id,
            "family_id": run_id,
            "status": "queued",
            "generation_state": "queued",
            "archive_state": "local_only",
            "model_id": "qwen-image-2.1-local",
            "prompt": "test",
            "profile": "fast",
            "parameters": {},
            "created_at": "2026-09-22T00:00:00Z",
        },
        Path(f"/{run_id}/receipt.json"),
        "hash",
    )
    JobRepository(connection).enqueue(run_id, "generation", "runtime-test")
    connection.commit()
    connection.close()
    return run_id


def test_sleep_assertion_tracks_owned_generation_and_releases_on_success(tmp_path):
    database = tmp_path / "library.sqlite3"
    seed_job(database)
    assertion = FakeAssertion()
    worker = PersistentWorker(database, execute_generation=lambda _run_id: None, sleep_assertion=assertion)

    assert worker.run_once() is True
    assert assertion.states == [True, False]


def test_sleep_assertion_releases_on_failure(tmp_path):
    database = tmp_path / "library.sqlite3"
    seed_job(database)
    assertion = FakeAssertion()

    def fail(_run_id):
        raise RuntimeError("expected")

    worker = PersistentWorker(database, execute_generation=fail, sleep_assertion=assertion)
    assert worker.run_once() is True
    assert assertion.states == [True, False]


def test_caffeinate_lifecycle_is_idempotent_and_bounded_to_worker_pid():
    class FakeProcess:
        def __init__(self):
            self.running = True
            self.terminated = 0

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.terminated += 1
            self.running = False

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.running = False

    calls = []
    process = FakeProcess()

    def factory(arguments, **kwargs):
        calls.append(arguments)
        return process

    assertion = IdleSleepAssertion(factory)
    assertion.set_active(True)
    assertion.set_active(True)
    assert len(calls) == 1
    assert calls[0][:3] == ["/usr/bin/caffeinate", "-i", "-w"]
    assert calls[0][3].isdigit()
    assertion.set_active(False)
    assert process.terminated == 1


def test_copytruncate_rotation_bounds_open_launchd_logs(tmp_path):
    log = tmp_path / "worker.err.log"
    log.write_bytes(b"0123456789")

    assert rotate_logs_copytruncate(tmp_path, max_bytes=5, backups=2) == [log]
    assert log.read_bytes() == b""
    assert (tmp_path / "worker.err.log.1").read_bytes() == b"0123456789"

    log.write_bytes(b"abcdefghij")
    rotate_logs_copytruncate(tmp_path, max_bytes=5, backups=2)
    assert (tmp_path / "worker.err.log.1").read_bytes() == b"abcdefghij"
    assert (tmp_path / "worker.err.log.2").read_bytes() == b"0123456789"
