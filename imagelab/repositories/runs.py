"""Run persistence and indexed library queries."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class RunRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    @staticmethod
    def _states(receipt: dict[str, Any]) -> tuple[str, str]:
        status = str(receipt.get("status") or "unknown")
        generation = str(receipt.get("generation_state") or ("succeeded" if status in {"local_only", "archived", "archive_failed"} else status))
        archive = str(receipt.get("archive_state") or ("verified" if status == "archived" else "failed" if status == "archive_failed" else "local_only"))
        return generation, archive

    def upsert_receipt(self, receipt: dict[str, Any], receipt_path: Path, receipt_sha256: str) -> None:
        parameters = receipt.get("parameters") or {}
        output = receipt.get("output") or {}
        generation_state, archive_state = self._states(receipt)
        run_id = receipt["run_id"]
        reference_edit = receipt.get("reference_edit") or {}
        operation = "reference_edit" if isinstance(reference_edit, dict) and (reference_edit.get("enabled") is True or reference_edit.get("source_file")) else "text_to_image"
        updated_at = receipt.get("completed_at") or receipt.get("started_at") or receipt["created_at"]
        values = (
            run_id, receipt.get("family_id") or run_id, receipt.get("parent_run_id"),
            receipt.get("relationship") or "original", receipt["model_id"], operation,
            receipt.get("title") or receipt["prompt"][:80], receipt["prompt"],
            receipt.get("profile") or "unknown", json.dumps(parameters, sort_keys=True),
            json.dumps(receipt, sort_keys=True), str(Path(receipt_path).resolve()), receipt_sha256,
            output.get("file"), output.get("sha256"), output.get("width"), output.get("height"),
            generation_state, archive_state, int(bool(receipt.get("favorite", False))),
            receipt.get("deleted_at"), receipt["created_at"], receipt.get("started_at"),
            receipt.get("completed_at"), updated_at,
        )
        self.connection.execute(
            """
            INSERT INTO runs(
                id, family_id, parent_run_id, relationship, model_id, operation,
                title, prompt, profile, request_json, legacy_receipt_json,
                receipt_path, receipt_sha256, output_path, output_sha256,
                output_width, output_height, generation_state, archive_state,
                favorite, deleted_at, created_at, started_at, completed_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                family_id=excluded.family_id, parent_run_id=excluded.parent_run_id,
                relationship=excluded.relationship, model_id=excluded.model_id,
                operation=excluded.operation, title=excluded.title, prompt=excluded.prompt,
                profile=excluded.profile, request_json=excluded.request_json,
                legacy_receipt_json=excluded.legacy_receipt_json,
                receipt_path=excluded.receipt_path, receipt_sha256=excluded.receipt_sha256,
                output_path=excluded.output_path, output_sha256=excluded.output_sha256,
                output_width=excluded.output_width, output_height=excluded.output_height,
                generation_state=excluded.generation_state, archive_state=excluded.archive_state,
                favorite=excluded.favorite, deleted_at=excluded.deleted_at,
                created_at=excluded.created_at, started_at=excluded.started_at,
                completed_at=excluded.completed_at, updated_at=excluded.updated_at
            """,
            values,
        )
        collection = receipt.get("library_folder")
        if isinstance(collection, str) and collection.strip():
            self.connection.execute(
                "INSERT OR IGNORE INTO collections(name, relative_path, created_at) VALUES(?, ?, ?)",
                (Path(collection).name, collection, receipt["created_at"]),
            )
            self.connection.execute(
                """INSERT OR IGNORE INTO run_collections(run_id, collection_id)
                   SELECT ?, id FROM collections WHERE relative_path = ?""",
                (run_id, collection),
            )

    @staticmethod
    def _receipt_from_row(row: sqlite3.Row) -> dict[str, Any]:
        receipt = json.loads(row["legacy_receipt_json"])
        receipt["generation_state"] = row["generation_state"]
        receipt["archive_state"] = row["archive_state"]
        receipt["title"] = row["title"]
        receipt["favorite"] = bool(row["favorite"])
        if row["deleted_at"]:
            receipt["deleted_at"] = row["deleted_at"]
        return receipt

    def get_receipt(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._receipt_from_row(row) if row else None

    def list_receipts(self, *, limit: int | None = None, query: str | None = None, family_id: str | None = None, include_deleted: bool = False) -> list[dict[str, Any]]:
        clauses = [] if include_deleted else ["deleted_at IS NULL"]
        values: list[Any] = []
        if query:
            clauses.append("(prompt LIKE ? OR title LIKE ?)")
            pattern = f"%{query}%"
            values.extend([pattern, pattern])
        if family_id:
            clauses.append("family_id = ?")
            values.append(family_id)
        sql = "SELECT * FROM runs"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            values.append(limit)
        return [self._receipt_from_row(row) for row in self.connection.execute(sql, values)]

    def set_favorite(self, run_id: str, favorite: bool) -> None:
        cursor = self.connection.execute("UPDATE runs SET favorite = ? WHERE id = ?", (int(favorite), run_id))
        if cursor.rowcount != 1:
            raise KeyError(run_id)
