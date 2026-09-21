"""Reversible organization metadata and safe Finder collections."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class MetadataConflict(RuntimeError):
    """Raised when a metadata form was based on a stale revision."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class OrganizationService:
    def __init__(self, connection: sqlite3.Connection, *, library_root: Path | None = None):
        self.connection = connection
        self.library_root = library_root
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS run_metadata_revisions (
                run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )"""
        )
        self.connection.commit()

    def metadata(self, run_id: str) -> dict:
        row = self.connection.execute(
            """SELECT r.title, r.favorite, r.deleted_at, COALESCE(m.revision, 1) AS revision
               FROM runs r LEFT JOIN run_metadata_revisions m ON m.run_id=r.id WHERE r.id=?""",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return {"title": row["title"], "favorite": bool(row["favorite"]), "deleted_at": row["deleted_at"], "revision": int(row["revision"])}

    def update_metadata(
        self,
        run_id: str,
        *,
        revision: int,
        title: str | None = None,
        favorite: bool | None = None,
        trashed: bool | None = None,
    ) -> dict:
        if not isinstance(revision, int) or revision < 1:
            raise ValueError("Metadata revision must be a positive integer")
        if title is not None:
            title = title.strip()
            if not title or len(title) > 120 or any(ord(char) < 32 for char in title):
                raise ValueError("Title must contain 1 to 120 printable characters")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            current = self.metadata(run_id)
            if current["revision"] != revision:
                raise MetadataConflict(f"Metadata changed since revision {revision}")
            updates: list[str] = []
            values: list[object] = []
            if title is not None:
                updates.append("title=?"); values.append(title)
            if favorite is not None:
                updates.append("favorite=?"); values.append(1 if favorite else 0)
            if trashed is not None:
                updates.append("deleted_at=?"); values.append(utc_now() if trashed else None)
            if updates:
                updates.append("updated_at=?"); values.append(utc_now())
                self.connection.execute(f"UPDATE runs SET {', '.join(updates)} WHERE id=?", (*values, run_id))
            next_revision = revision + 1
            self.connection.execute(
                """INSERT INTO run_metadata_revisions(run_id, revision, updated_at) VALUES(?,?,?)
                   ON CONFLICT(run_id) DO UPDATE SET revision=excluded.revision, updated_at=excluded.updated_at""",
                (run_id, next_revision, utc_now()),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.metadata(run_id)

    @staticmethod
    def validate_collection(value: str) -> str:
        normalized = (value or "").strip().replace("\\", "/")
        if normalized.startswith("/"):
            raise ValueError("Collection must be relative")
        raw = normalized.strip("/")
        if not raw or len(raw) > 180 or raw.startswith(".") or any(part in {"", ".", ".."} or part.startswith(".") for part in raw.split("/")):
            raise ValueError("Collection must be a safe relative folder")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._()&'/-]*", raw):
            raise ValueError("Collection contains unsupported characters")
        return raw

    def create_collection(self, relative: str) -> Path:
        if self.library_root is None:
            raise RuntimeError("A library root is required")
        rel = self.validate_collection(relative)
        root = self.library_root.resolve()
        destination = (root / rel).resolve(strict=False)
        if root not in destination.parents:
            raise ValueError("Collection escapes the image library")
        destination.mkdir(parents=True, exist_ok=True)
        if root not in destination.resolve().parents:
            raise ValueError("Collection resolves outside the image library")
        self.connection.execute(
            "INSERT OR IGNORE INTO collections(name, relative_path, created_at) VALUES(?,?,?)",
            (destination.name, rel, utc_now()),
        )
        self.connection.commit()
        return destination
