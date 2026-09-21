import importlib.util
import json
from pathlib import Path

from jinja2 import FileSystemLoader
from imagelab.repositories.jobs import JobRepository

SPEC = importlib.util.spec_from_file_location("mac_image_lab_queue_api", Path(__file__).parents[1] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def configure_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "library")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "library-root")
    monkeypatch.setattr(lab.app, "jinja_loader", FileSystemLoader(Path(__file__).parents[1] / "app" / "templates"))
    return lab.app.test_client()


def enqueue(client, key="queue-api-key"):
    response = client.post("/generate", data={"prompt": "queue test", "idempotency_key": key})
    assert response.status_code == 302
    connection = lab.initialize_database(lab.database_path())
    job = JobRepository(connection).list(limit=1)[0]
    connection.close()
    return job


def test_queue_api_exposes_compact_safe_job_state(tmp_path, monkeypatch):
    client = configure_isolated(tmp_path, monkeypatch)
    job = enqueue(client)

    response = client.get("/api/jobs")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["jobs"][0]["id"] == job["id"]
    assert payload["jobs"][0]["state"] == "queued"
    assert "idempotency_key" not in payload["jobs"][0]
    assert "receipt_path" not in json.dumps(payload)


def test_queue_api_includes_backend_progress_when_reported(tmp_path, monkeypatch):
    client = configure_isolated(tmp_path, monkeypatch)
    job = enqueue(client)
    connection = lab.initialize_database(lab.database_path())
    repository = JobRepository(connection)
    claimed = repository.claim_next()
    repository.record_backend_acceptance(claimed["id"], "backend-progress")
    repository.heartbeat(claimed["id"], {"backend_state": "running", "progress": 0.625})
    connection.close()

    payload = client.get("/api/jobs").get_json()

    assert payload["jobs"][0]["progress"] == 0.625


def test_queued_job_can_be_cancelled_transactionally(tmp_path, monkeypatch):
    client = configure_isolated(tmp_path, monkeypatch)
    job = enqueue(client)

    response = client.post(f"/api/jobs/{job['id']}/cancel")

    assert response.status_code == 200
    connection = lab.initialize_database(lab.database_path())
    stored = JobRepository(connection).get(job["id"])
    connection.close()
    assert stored["state"] == "cancelled"


def test_running_cancel_is_rejected_when_exact_backend_ownership_is_unproven(tmp_path, monkeypatch):
    client = configure_isolated(tmp_path, monkeypatch)
    job = enqueue(client)
    connection = lab.initialize_database(lab.database_path())
    repository = JobRepository(connection)
    claimed = repository.claim_next()
    repository.record_backend_acceptance(claimed["id"], "backend-owned")
    connection.close()
    monkeypatch.setattr(lab.ComfyRecoveryBackend, "cancel", lambda self, _job_id: False)

    response = client.post(f"/api/jobs/{job['id']}/cancel")

    assert response.status_code == 409
    assert "cannot be safely cancelled" in response.get_json()["error"]


def test_retry_creates_linked_new_run_and_job(tmp_path, monkeypatch):
    client = configure_isolated(tmp_path, monkeypatch)
    original = enqueue(client)
    connection = lab.initialize_database(lab.database_path())
    repository = JobRepository(connection)
    repository.claim_next()
    repository.fail(original["id"], RuntimeError("test failure"))
    connection.close()

    response = client.post(f"/api/jobs/{original['id']}/retry")

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["job_id"] != original["id"]
    assert payload["run_id"] != original["run_id"]
    connection = lab.initialize_database(lab.database_path())
    repository = JobRepository(connection)
    assert repository.retry_parent(payload["job_id"]) == original["id"]
    connection.close()


def test_queue_page_is_available(tmp_path, monkeypatch):
    client = configure_isolated(tmp_path, monkeypatch)

    response = client.get("/queue")

    assert response.status_code == 200
    assert "Generation queue" in response.get_data(as_text=True)
