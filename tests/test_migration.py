import hashlib
import json
import sqlite3
from pathlib import Path

from imagelab.db import backup_database, connect_database, initialize_database
from imagelab.migration import migrate_legacy


def make_receipt(runs, run_id, *, parent=None, status="local_only"):
    directory = runs / run_id
    directory.mkdir(parents=True)
    receipt = {
        "schema_version": 2,
        "run_id": run_id,
        "family_id": parent or run_id,
        "parent_run_id": parent,
        "relationship": "variation" if parent else "original",
        "model_id": "qwen-image-2.1-local",
        "prompt": f"prompt {run_id}",
        "profile": "fast",
        "parameters": {"width": 768, "height": 768, "steps": 8, "seed": 1},
        "created_at": "2026-09-21T00:00:00Z",
        "completed_at": "2026-09-21T00:02:00Z",
        "status": status,
        "archive_state": "verified" if status == "archived" else "local_only",
        "output": {"file": "output.png", "width": 768, "height": 768, "sha256": "output-hash"},
        "title": "Test",
        "library_folder": "Collections/Test",
        "library_copies": [f"Generated Images/Collections/Test/{run_id}.png"],
    }
    path = directory / "receipt.json"
    path.write_text(json.dumps(receipt))
    return path, receipt


def test_schema_enables_wal_foreign_keys_and_expected_tables(tmp_path):
    db_path = tmp_path / "state" / "library.sqlite3"
    connection = initialize_database(db_path)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"runs", "jobs", "job_events", "collections", "run_collections", "model_notes", "recipes", "family_choices", "archive_attempts", "schema_migrations"} <= tables
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    connection.close()


def test_dry_run_reads_and_hashes_without_creating_database(tmp_path):
    runs = tmp_path / "runs"
    run_id = "11111111-1111-1111-1111-111111111111"
    path, _ = make_receipt(runs, run_id)
    db_path = tmp_path / "state" / "library.sqlite3"

    report = migrate_legacy(runs, db_path, dry_run=True)

    assert report["valid"] == 1
    assert report["malformed"] == 0
    assert report["receipts"][0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not db_path.exists()


def test_apply_is_idempotent_and_preserves_full_receipt_and_collections(tmp_path):
    runs = tmp_path / "runs"
    root_id = "11111111-1111-1111-1111-111111111111"
    child_id = "22222222-2222-2222-2222-222222222222"
    make_receipt(runs, root_id, status="archived")
    _, child = make_receipt(runs, child_id, parent=root_id)
    db_path = tmp_path / "state" / "library.sqlite3"

    first = migrate_legacy(runs, db_path, dry_run=False)
    second = migrate_legacy(runs, db_path, dry_run=False)

    with connect_database(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        row = connection.execute("SELECT * FROM runs WHERE id = ?", (child_id,)).fetchone()
        assert row["family_id"] == root_id
        assert row["parent_run_id"] == root_id
        assert row["generation_state"] == "succeeded"
        assert json.loads(row["legacy_receipt_json"])["prompt"] == child["prompt"]
        assert connection.execute("SELECT COUNT(*) FROM run_collections").fetchone()[0] == 2
    assert first["imported"] == 2
    assert second["imported"] == 2
    assert second["database_run_count"] == 2


def test_legacy_v1_model_is_inferred_from_recorded_qwen_assets(tmp_path):
    runs = tmp_path / "runs"
    run_id = "33333333-3333-3333-3333-333333333333"
    path, receipt = make_receipt(runs, run_id)
    receipt.pop("model_id")
    receipt["models"] = {"unet": "qwen_image_2.1_int8_convrot.safetensors"}
    path.write_text(json.dumps(receipt))
    db_path = tmp_path / "state" / "library.sqlite3"

    report = migrate_legacy(runs, db_path, dry_run=False)

    assert report["malformed"] == 0
    with connect_database(db_path) as connection:
        row = connection.execute("SELECT model_id FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row[0] == "qwen-image-2.1-local"


def test_malformed_receipt_is_reported_and_quarantined_on_apply(tmp_path):
    runs = tmp_path / "runs"
    bad = runs / "bad-run"
    bad.mkdir(parents=True)
    (bad / "receipt.json").write_text("{bad json")
    db_path = tmp_path / "state" / "library.sqlite3"
    quarantine = tmp_path / "state" / "quarantine"

    report = migrate_legacy(runs, db_path, dry_run=False, quarantine_root=quarantine)

    assert report["malformed"] == 1
    assert report["errors"][0]["path"].endswith("bad-run/receipt.json")
    quarantined = list(quarantine.glob("*.json"))
    assert len(quarantined) == 1
    assert json.loads(quarantined[0].read_text())["error_type"] == "JSONDecodeError"


def test_sqlite_backup_restores_to_isolated_database(tmp_path):
    db_path = tmp_path / "state" / "library.sqlite3"
    connection = initialize_database(db_path)
    connection.execute("INSERT INTO model_notes(model_id, note, revision) VALUES(?, ?, ?)", ("qwen", "note", 1))
    connection.commit()
    connection.close()
    backup_path = tmp_path / "backups" / "library.sqlite3"

    backup_database(db_path, backup_path)

    with sqlite3.connect(backup_path) as restored:
        assert restored.execute("SELECT note FROM model_notes WHERE model_id='qwen'").fetchone()[0] == "note"
