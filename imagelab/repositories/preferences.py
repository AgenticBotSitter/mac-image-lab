"""Versioned named recipes and optimistic model notes."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping


class PreferenceConflict(RuntimeError):
    """Raised when a stale revision would overwrite a newer preference."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, label: str, *, maximum: int, required: bool = True) -> str:
    text = str(value or "").strip()
    if (required and not text) or len(text) > maximum:
        qualifier = f"1–{maximum}" if required else f"at most {maximum}"
        raise ValueError(f"{label} must be {qualifier} characters")
    return text


class PreferenceRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    @staticmethod
    def validate_recipe(request: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"schema_version", "mode", "model_id", "prompt", "profile", "aspect", "collection"}
        if set(request) - allowed:
            raise ValueError("Recipe contains unsupported fields")
        if request.get("schema_version") != 1:
            raise ValueError("Recipe schema version must be 1")
        mode = str(request.get("mode") or "")
        if mode not in {"text", "transform"}:
            raise ValueError("Recipe mode must be text or transform")
        aspect = str(request.get("aspect") or "")
        if aspect not in {"square", "portrait", "landscape", "custom"}:
            raise ValueError("Recipe aspect is invalid")
        return {
            "schema_version": 1,
            "mode": mode,
            "model_id": _clean_text(request.get("model_id"), "Recipe model", maximum=120),
            "prompt": _clean_text(request.get("prompt"), "Recipe prompt", maximum=4000),
            "profile": _clean_text(request.get("profile"), "Recipe profile", maximum=80),
            "aspect": aspect,
            "collection": _clean_text(request.get("collection"), "Recipe collection", maximum=180, required=False),
        }

    def save_recipe(self, *, recipe_id: str, name: str, description: str, request: Mapping[str, Any]) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", recipe_id):
            raise ValueError("Recipe ID is invalid")
        clean_name = _clean_text(name, "Recipe name", maximum=120)
        clean_description = _clean_text(description, "Recipe description", maximum=500, required=False)
        clean_request = self.validate_recipe(request)
        timestamp = _now()
        self.connection.execute(
            """INSERT INTO recipes(id, name, description, request_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description,
                   request_json=excluded.request_json, updated_at=excluded.updated_at""",
            (recipe_id, clean_name, clean_description, json.dumps(clean_request, sort_keys=True), timestamp, timestamp),
        )
        self.connection.commit()
        return {"id": recipe_id, "name": clean_name, "description": clean_description, "request": clean_request}

    def list_recipes(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, name, description, request_json, created_at, updated_at FROM recipes ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
        return [
            {
                "id": row[0], "name": row[1], "description": row[2],
                "request": json.loads(row[3]), "created_at": row[4], "updated_at": row[5],
            }
            for row in rows
        ]

    def get_model_note(self, model_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT note, revision, updated_at FROM model_notes WHERE model_id = ?", (model_id,)
        ).fetchone()
        return {"note": row[0], "revision": row[1], "updated_at": row[2]} if row else {"note": "", "revision": 0, "updated_at": None}

    def save_model_note(self, model_id: str, note: str, *, expected_revision: int) -> dict[str, Any]:
        clean_note = _clean_text(note, "Personal note", maximum=5000, required=False)
        self.connection.execute("BEGIN IMMEDIATE")
        current = self.get_model_note(model_id)
        if current["revision"] != expected_revision:
            self.connection.rollback()
            raise PreferenceConflict("Model note changed in another session; reload before saving")
        revision = expected_revision + 1
        timestamp = _now()
        self.connection.execute(
            """INSERT INTO model_notes(model_id, note, revision, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(model_id) DO UPDATE SET note=excluded.note, revision=excluded.revision, updated_at=excluded.updated_at""",
            (model_id, clean_note, revision, timestamp),
        )
        self.connection.commit()
        return {"note": clean_note, "revision": revision, "updated_at": timestamp}
