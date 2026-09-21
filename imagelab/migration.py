"""Idempotent legacy receipt discovery and SQLite migration."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from imagelab.db import initialize_database


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _states(receipt: dict[str, Any]) -> tuple[str, str]:
    status = str(receipt.get("status") or "unknown")
    generation = str(receipt.get("generation_state") or ("succeeded" if status in {"local_only", "archived", "archive_failed"} else status))
    archive = str(receipt.get("archive_state") or ("verified" if status == "archived" else "failed" if status == "archive_failed" else "local_only"))
    return generation, archive


def _validate_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("receipt root must be an object")
    for field in ("run_id", "prompt", "created_at"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"missing required field: {field}")
    if not isinstance(value.get("model_id"), str) or not value.get("model_id", "").strip():
        recorded_models = json.dumps(value.get("models") or {}, sort_keys=True).lower()
        if "qwen_image_2.1" in recorded_models:
            value["model_id"] = "qwen-image-2.1-local"
        else:
            raise ValueError("missing required field: model_id")
    if not isinstance(value.get("parameters", {}), dict):
        raise ValueError("parameters must be an object")
    return value


def _discover(runs_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    valid: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in sorted(Path(runs_root).glob("*/receipt.json")):
        digest = _sha256(path)
        try:
            receipt = _validate_receipt(json.loads(path.read_text()))
            valid.append({"path": str(path.resolve()), "sha256": digest, "receipt": receipt})
        except Exception as exc:
            errors.append({
                "path": str(path.resolve()),
                "sha256": digest,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
    return valid, errors


def _upsert_run(connection, item: dict[str, Any]) -> None:
    receipt = item["receipt"]
    parameters = receipt.get("parameters") or {}
    output = receipt.get("output") or {}
    generation_state, archive_state = _states(receipt)
    run_id = receipt["run_id"]
    family_id = receipt.get("family_id") or run_id
    relationship = receipt.get("relationship") or "original"
    reference_edit = receipt.get("reference_edit") or {}
    operation = "reference_edit" if isinstance(reference_edit, dict) and (reference_edit.get("enabled") is True or reference_edit.get("source_file")) else "text_to_image"
    updated_at = receipt.get("completed_at") or receipt.get("started_at") or receipt["created_at"]
    values = (
        run_id,
        family_id,
        receipt.get("parent_run_id"),
        relationship,
        receipt["model_id"],
        operation,
        receipt.get("title") or receipt["prompt"][:80],
        receipt["prompt"],
        receipt.get("profile") or "unknown",
        json.dumps(parameters, sort_keys=True),
        json.dumps(receipt, sort_keys=True),
        item["path"],
        item["sha256"],
        output.get("file"),
        output.get("sha256"),
        output.get("width"),
        output.get("height"),
        generation_state,
        archive_state,
        int(bool(receipt.get("favorite", False))),
        receipt.get("deleted_at"),
        receipt["created_at"],
        receipt.get("started_at"),
        receipt.get("completed_at"),
        updated_at,
    )
    connection.execute(
        """
        INSERT INTO runs(
            id, family_id, parent_run_id, relationship, model_id, operation,
            title, prompt, profile, request_json, legacy_receipt_json,
            receipt_path, receipt_sha256, output_path, output_sha256,
            output_width, output_height, generation_state, archive_state,
            favorite, deleted_at, created_at, started_at, completed_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            family_id=excluded.family_id,
            parent_run_id=excluded.parent_run_id,
            relationship=excluded.relationship,
            model_id=excluded.model_id,
            operation=excluded.operation,
            title=excluded.title,
            prompt=excluded.prompt,
            profile=excluded.profile,
            request_json=excluded.request_json,
            legacy_receipt_json=excluded.legacy_receipt_json,
            receipt_path=excluded.receipt_path,
            receipt_sha256=excluded.receipt_sha256,
            output_path=excluded.output_path,
            output_sha256=excluded.output_sha256,
            output_width=excluded.output_width,
            output_height=excluded.output_height,
            generation_state=excluded.generation_state,
            archive_state=excluded.archive_state,
            favorite=excluded.favorite,
            deleted_at=excluded.deleted_at,
            created_at=excluded.created_at,
            started_at=excluded.started_at,
            completed_at=excluded.completed_at,
            updated_at=excluded.updated_at
        """,
        values,
    )
    collection = receipt.get("library_folder")
    if isinstance(collection, str) and collection.strip():
        connection.execute(
            "INSERT OR IGNORE INTO collections(name, relative_path, created_at) VALUES(?, ?, ?)",
            (Path(collection).name, collection, receipt["created_at"]),
        )
        connection.execute(
            """INSERT OR IGNORE INTO run_collections(run_id, collection_id)
               SELECT ?, id FROM collections WHERE relative_path = ?""",
            (run_id, collection),
        )


def migrate_legacy(
    runs_root: Path,
    database_path: Path,
    *,
    dry_run: bool = True,
    quarantine_root: Path | None = None,
    model_notes_path: Path | None = None,
) -> dict[str, Any]:
    runs_root = Path(runs_root)
    database_path = Path(database_path)
    receipts, errors = _discover(runs_root)
    report: dict[str, Any] = {
        "dry_run": dry_run,
        "runs_root": str(runs_root.resolve()),
        "database_path": str(database_path.resolve()),
        "valid": len(receipts),
        "malformed": len(errors),
        "receipts": [{"run_id": item["receipt"]["run_id"], "path": item["path"], "sha256": item["sha256"]} for item in receipts],
        "errors": errors,
        "imported": 0,
        "database_run_count": None,
        "hash_mismatches": [],
    }
    if dry_run:
        return report

    if errors:
        quarantine = Path(quarantine_root or database_path.parent / "quarantine")
        quarantine.mkdir(parents=True, exist_ok=True)
        for error in errors:
            destination = quarantine / f"{error['sha256'][:16]}.json"
            destination.write_text(json.dumps(error, indent=2, sort_keys=True) + "\n")

    connection = initialize_database(database_path)
    try:
        with connection:
            for item in receipts:
                _upsert_run(connection, item)
            if model_notes_path and Path(model_notes_path).exists():
                notes = json.loads(Path(model_notes_path).read_text())
                for model_id, note in notes.items():
                    connection.execute(
                        """INSERT INTO model_notes(model_id, note, revision, updated_at) VALUES(?, ?, 1, ?)
                           ON CONFLICT(model_id) DO UPDATE SET note=excluded.note, revision=model_notes.revision+1, updated_at=excluded.updated_at""",
                        (model_id, str(note), _now()),
                    )
        report["imported"] = len(receipts)
        report["database_run_count"] = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        for item in receipts:
            row = connection.execute("SELECT receipt_sha256 FROM runs WHERE id = ?", (item["receipt"]["run_id"],)).fetchone()
            if not row or row[0] != item["sha256"]:
                report["hash_mismatches"].append(item["receipt"]["run_id"])
    finally:
        connection.close()
    return report
