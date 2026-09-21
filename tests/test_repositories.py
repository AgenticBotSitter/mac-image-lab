import json
from pathlib import Path

from imagelab.db import initialize_database
from imagelab.repositories.runs import RunRepository


def receipt(run_id, *, created="2026-09-21T00:00:00Z", prompt="a test image"):
    return {
        "run_id": run_id,
        "family_id": run_id,
        "parent_run_id": None,
        "relationship": "original",
        "model_id": "qwen-image-2.1-local",
        "prompt": prompt,
        "profile": "fast",
        "parameters": {"width": 768, "height": 768, "steps": 8, "seed": 0},
        "created_at": created,
        "status": "queued",
        "generation_state": "queued",
        "archive_state": "local_only",
    }


def test_run_repository_upserts_reads_lists_and_updates_favorite(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    repository = RunRepository(connection)
    first = receipt("11111111-1111-1111-1111-111111111111", prompt="red flower")
    second = receipt("22222222-2222-2222-2222-222222222222", created="2026-09-22T00:00:00Z", prompt="blue vase")

    repository.upsert_receipt(first, tmp_path / "one.json", "hash-one")
    repository.upsert_receipt(second, tmp_path / "two.json", "hash-two")
    connection.commit()

    assert repository.get_receipt(first["run_id"])["prompt"] == "red flower"
    assert [item["run_id"] for item in repository.list_receipts(limit=1)] == [second["run_id"]]
    assert [item["run_id"] for item in repository.list_receipts(query="flower")] == [first["run_id"]]
    repository.set_favorite(first["run_id"], True)
    connection.commit()
    assert repository.get_receipt(first["run_id"])["favorite"] is True
    connection.close()
