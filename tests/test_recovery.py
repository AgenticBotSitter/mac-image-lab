from pathlib import Path

from imagelab.db import initialize_database
from imagelab.repositories.jobs import JobRepository
from imagelab.repositories.runs import RunRepository
from imagelab.services.recovery import (
    BackendDisconnected,
    BackendSnapshot,
    RecoveryCoordinator,
    SubmissionUncertain,
)


def seed(connection, run_id="11111111-1111-1111-1111-111111111111"):
    RunRepository(connection).upsert_receipt(
        {
            "run_id": run_id,
            "family_id": run_id,
            "model_id": "qwen-image-2.1-local",
            "prompt": "test",
            "profile": "fast",
            "parameters": {},
            "created_at": "2026-09-21T00:00:00Z",
            "generation_state": "queued",
            "archive_state": "local_only",
        },
        Path(f"/{run_id}/receipt.json"),
        "hash",
    )
    repository = JobRepository(connection)
    job, _ = repository.enqueue(run_id, "generation", "correlation-token")
    connection.commit()
    return repository, job


class FakeBackend:
    def __init__(self):
        self.submissions = 0
        self.found = None
        self.snapshot = BackendSnapshot("running")
        self.collected = []
        self.submit_error = None
        self.inspect_error = None

    def find_by_correlation(self, token):
        return self.found

    def submit(self, run_id, token):
        self.submissions += 1
        if self.submit_error:
            raise self.submit_error
        return "backend-1"

    def inspect(self, backend_job_id):
        if self.inspect_error:
            raise self.inspect_error
        return self.snapshot

    def collect(self, run_id, backend_job_id, snapshot):
        self.collected.append((run_id, backend_job_id))
        return True


def test_new_claim_persists_intent_before_submission(tmp_path):
    connection = initialize_database(tmp_path / "db.sqlite3")
    repository, _ = seed(connection)
    job = repository.claim_next()
    backend = FakeBackend()

    RecoveryCoordinator(repository, backend).step(job)

    stored = repository.get(job["id"])
    assert backend.submissions == 1
    assert stored["state"] == "running"
    assert stored["backend_job_id"] == "backend-1"
    assert repository.has_event(job["id"], "submission_intent")
    connection.close()


def test_restart_recovers_backend_id_by_correlation_without_resubmission(tmp_path):
    db = tmp_path / "db.sqlite3"
    connection = initialize_database(db)
    repository, _ = seed(connection)
    job = repository.claim_next()
    repository.record_submission_intent(job["id"])
    connection.close()

    reopened = initialize_database(db)
    repository = JobRepository(reopened)
    backend = FakeBackend()
    backend.found = "already-accepted"
    active = repository.active()
    RecoveryCoordinator(repository, backend).step(active)

    assert backend.submissions == 0
    assert repository.get(job["id"])["backend_job_id"] == "already-accepted"
    reopened.close()


def test_ambiguous_correlation_match_needs_attention(tmp_path):
    connection = initialize_database(tmp_path / "db.sqlite3")
    repository, _ = seed(connection)
    job = repository.claim_next()
    repository.record_submission_intent(job["id"])
    backend = FakeBackend()

    def ambiguous(_token):
        raise SubmissionUncertain("multiple matches")

    backend.find_by_correlation = ambiguous
    RecoveryCoordinator(repository, backend).step(repository.active())

    assert repository.get(job["id"])["state"] == "needs_attention"
    assert backend.submissions == 0
    connection.close()


def test_completed_backend_is_collected_after_restart(tmp_path):
    connection = initialize_database(tmp_path / "db.sqlite3")
    repository, _ = seed(connection)
    job = repository.claim_next()
    repository.record_backend_acceptance(job["id"], "done-before-reconnect")
    backend = FakeBackend()
    backend.snapshot = BackendSnapshot("succeeded", payload={"output": "ready"})

    RecoveryCoordinator(repository, backend).step(repository.active())

    assert repository.get(job["id"])["state"] == "succeeded"
    assert backend.collected == [(job["run_id"], "done-before-reconnect")]
    connection.close()


def test_disconnect_keeps_running_job_recoverable(tmp_path):
    connection = initialize_database(tmp_path / "db.sqlite3")
    repository, _ = seed(connection)
    job = repository.claim_next()
    repository.record_backend_acceptance(job["id"], "backend-1")
    backend = FakeBackend()
    backend.inspect_error = BackendDisconnected("connection refused")

    RecoveryCoordinator(repository, backend).step(repository.active())

    assert repository.get(job["id"])["state"] == "running"
    assert repository.has_event(job["id"], "backend_disconnected")
    connection.close()


def test_timeout_after_possible_acceptance_never_blindly_resubmits(tmp_path):
    connection = initialize_database(tmp_path / "db.sqlite3")
    repository, _ = seed(connection)
    job = repository.claim_next()
    backend = FakeBackend()
    backend.submit_error = SubmissionUncertain("timed out after request body sent")

    RecoveryCoordinator(repository, backend).step(job)
    RecoveryCoordinator(repository, backend).step(repository.active())

    stored = repository.get(job["id"])
    assert backend.submissions == 1
    assert stored["state"] == "needs_attention"
    connection.close()


def test_unknown_backend_history_needs_attention(tmp_path):
    connection = initialize_database(tmp_path / "db.sqlite3")
    repository, _ = seed(connection)
    job = repository.claim_next()
    repository.record_backend_acceptance(job["id"], "vanished")
    backend = FakeBackend()
    backend.snapshot = BackendSnapshot("unknown")

    RecoveryCoordinator(repository, backend).step(repository.active())

    assert repository.get(job["id"])["state"] == "needs_attention"
    connection.close()


def test_stale_heartbeat_is_reported_without_failing_or_resubmitting(tmp_path):
    connection = initialize_database(tmp_path / "db.sqlite3")
    repository, _ = seed(connection)
    job = repository.claim_next()
    repository.record_backend_acceptance(job["id"], "slow-job")
    connection.execute(
        "UPDATE jobs SET heartbeat_at='2026-09-21T00:00:00Z' WHERE id=?", (job["id"],)
    )
    connection.commit()

    stale = repository.stale_active("2026-09-21T01:00:00Z")

    assert [value["id"] for value in stale] == [job["id"]]
    assert repository.get(job["id"])["state"] == "running"
    connection.close()


def test_missing_collected_output_needs_attention(tmp_path):
    connection = initialize_database(tmp_path / "db.sqlite3")
    repository, _ = seed(connection)
    job = repository.claim_next()
    repository.record_backend_acceptance(job["id"], "missing-output")
    backend = FakeBackend()
    backend.snapshot = BackendSnapshot("succeeded")
    backend.collect = lambda *_args: False

    RecoveryCoordinator(repository, backend).step(repository.active())

    assert repository.get(job["id"])["state"] == "needs_attention"
    connection.close()
