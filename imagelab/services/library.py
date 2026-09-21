"""Bounded, indexed Library queries."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from imagelab.repositories.runs import RunRepository


@dataclass(frozen=True)
class LibraryQuery:
    page: int = 1
    per_page: int = 40
    search: str = ""
    model: str = ""
    collection: str = ""
    family_id: str = ""
    favorite: bool = False
    layout: str = "natural"
    sort: str = "newest"


@dataclass(frozen=True)
class LibraryPage:
    items: list[dict[str, Any]]
    page: int
    per_page: int
    pages: int
    total_images: int
    total_families: int


class LibraryService:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    @staticmethod
    def _validate(query: LibraryQuery) -> None:
        if query.page < 1:
            raise ValueError("Page must be positive")
        if query.per_page < 1 or query.per_page > 100:
            raise ValueError("Page size must be between 1 and 100")
        if len(query.search) > 200:
            raise ValueError("Search must be 200 characters or fewer")
        if len(query.model) > 100 or len(query.collection) > 180 or len(query.family_id) > 36:
            raise ValueError("Library filter is too long")
        if query.sort not in {"newest", "oldest", "title"}:
            raise ValueError("Unknown Library sort")
        if query.layout not in {"natural", "cropped"}:
            raise ValueError("Unknown Library layout")

    def page(self, query: LibraryQuery) -> LibraryPage:
        self._validate(query)
        clauses = ["r.deleted_at IS NULL", "r.generation_state = 'succeeded'", "r.output_path IS NOT NULL", "r.output_sha256 IS NOT NULL"]
        values: list[Any] = []
        if query.search:
            clauses.append("(r.title LIKE ? OR r.prompt LIKE ?)")
            pattern = f"%{query.search}%"
            values.extend([pattern, pattern])
        if query.model:
            clauses.append("r.model_id = ?")
            values.append(query.model)
        if query.family_id:
            clauses.append("r.family_id = ?")
            values.append(query.family_id)
        if query.favorite:
            clauses.append("r.favorite = 1")
        if query.collection:
            clauses.append(
                "EXISTS (SELECT 1 FROM run_collections rc JOIN collections c ON c.id=rc.collection_id "
                "WHERE rc.run_id=r.id AND c.relative_path=?)"
            )
            values.append(query.collection)
        where = " AND ".join(clauses)
        count = self.connection.execute(
            f"SELECT COUNT(*) AS images, COUNT(DISTINCT family_id) AS families FROM runs r WHERE {where}",
            values,
        ).fetchone()
        total = int(count["images"])
        families = int(count["families"])
        orders = {
            "newest": "r.created_at DESC, r.id DESC",
            "oldest": "r.created_at ASC, r.id ASC",
            "title": "r.title COLLATE NOCASE ASC, r.id ASC",
        }
        offset = (query.page - 1) * query.per_page
        rows = self.connection.execute(
            f"SELECT r.* FROM runs r WHERE {where} ORDER BY {orders[query.sort]} LIMIT ? OFFSET ?",
            [*values, query.per_page, offset],
        ).fetchall()
        items = [RunRepository._receipt_from_row(row) for row in rows]
        return LibraryPage(items, query.page, query.per_page, max(1, math.ceil(total / query.per_page)), total, families)
