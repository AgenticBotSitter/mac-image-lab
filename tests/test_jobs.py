from pathlib import Path

from imagelab.db import initialize_database
from imagelab.repositories.jobs import JobRepository
from imagelab.repositories.runs import RunRepository
from imagelab.worker import PersistentWorker, WorkerAlreadyRunning, WorkerLeadership


def seed_run(connection, run_id="11111111-1111-1111-1111-111111111111"):
    RunRepository(connection).upsert_receipt(
        {
            "run_id": run_id,
            "family_id": run_id,
            "model_id": "qwen-image-2.1-local",
            "prompt": "test",
            "profile": "fast",
            "parameters": {},
            "created_at": "2026-09-21T00:00:00Z",
            "status": "queued",
            "generation_state": "queued",
            "archive_state": "local_only",
        },
        Path(f"/{run_id}/receipt.json"),
        "receipt-hash",
    )
    connection.commit()
    return run_id


def test_duplicate_idempotency_key_returns_original_job(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    run_id = seed_run(connection)
    repository = JobRepository(connection)

    first, first_created = repository.enqueue(run_id, "generation", "same-submit")
    second, second_created = repository.enqueue(run_id, "generation", "same-submit")
    connection.commit()

    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    assert repository.count(state="queued") == 1
    connection.close()


def test_same_run_cannot_be_enqueued_twice_with_different_keys(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    run_id = seed_run(connection)
    repository = JobRepository(connection)
    first, first_created = repository.enqueue(run_id, "generation", "first-key")
    second, second_created = repository.enqueue(run_id, "generation", "second-key")
    connection.commit()

    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    assert repository.count() == 1
    connection.close()


def test_atomic_claim_allows_only_one_worker_to_claim_job(tmp_path):
    db_path = tmp_path / "library.sqlite3"
    first_connection = initialize_database(db_path)
    run_id = seed_run(first_connection)
    JobRepository(first_connection).enqueue(run_id, "generation", "claim-once")
    first_connection.commit()
    second_connection = initialize_database(db_path)

    first = JobRepository(first_connection).claim_next()
    second = JobRepository(second_connection).claim_next()

    assert first is not None
    assert first["run_id"] == run_id
    assert second is None
    first_connection.close()
    second_connection.close()


def test_queued_job_survives_connection_restart(tmp_path):
    db_path = tmp_path / "library.sqlite3"
    connection = initialize_database(db_path)
    run_id = seed_run(connection)
    job, _ = JobRepository(connection).enqueue(run_id, "generation", "restart-safe")
    connection.commit()
    connection.close()

    reopened = initialize_database(db_path)
    stored = JobRepository(reopened).get(job["id"])

    assert stored["state"] == "queued"
    assert stored["run_id"] == run_id
    reopened.close()


def test_claim_waits_while_an_existing_generation_is_running(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    first_run = seed_run(connection)
    second_run = seed_run(connection, "22222222-2222-2222-2222-222222222222")
    repository = JobRepository(connection)
    repository.enqueue(first_run, "generation", "first")
    connection.commit()
    assert repository.claim_next()["run_id"] == first_run
    repository.enqueue(second_run, "generation", "second")
    connection.commit()

    assert repository.claim_next() is None
    assert repository.count(state="queued") == 1
    connection.close()


def test_second_worker_refuses_leadership(tmp_path):
    first = WorkerLeadership(tmp_path / "worker.lock")
    second = WorkerLeadership(tmp_path / "worker.lock")
    first.acquire()
    try:
        try:
            second.acquire()
        except WorkerAlreadyRunning:
            pass
        else:
            raise AssertionError("second worker unexpectedly acquired leadership")
    finally:
        first.release()


def test_worker_completes_claimed_job_and_records_events(tmp_path):
    db_path = tmp_path / "library.sqlite3"
    connection = initialize_database(db_path)
    run_id = seed_run(connection)
    JobRepository(connection).enqueue(run_id, "generation", "worker-success")
    connection.commit()
    connection.close()
    executed = []

    worker = PersistentWorker(db_path, execute_generation=lambda value: executed.append(value))
    assert worker.run_once() is True

    check = initialize_database(db_path)
    repository = JobRepository(check)
    assert executed == [run_id]
    assert repository.count(state="succeeded") == 1
    assert [event["event_type"] for event in repository.events_for_run(run_id)] == ["queued", "claimed", "succeeded"]
    check.close()


def test_worker_failure_is_persisted_without_losing_job(tmp_path):
    db_path = tmp_path / "library.sqlite3"
    connection = initialize_database(db_path)
    run_id = seed_run(connection)
    JobRepository(connection).enqueue(run_id, "generation", "worker-failure")
    connection.commit()
    connection.close()

    def fail(_run_id):
        raise RuntimeError("backend unavailable")

    worker = PersistentWorker(db_path, execute_generation=fail)
    assert worker.run_once() is True

    check = initialize_database(db_path)
    job = JobRepository(check).list(state="failed")[0]
    assert job["error_type"] == "RuntimeError"
    assert job["error_message"] == "backend unavailable"
    check.close()
