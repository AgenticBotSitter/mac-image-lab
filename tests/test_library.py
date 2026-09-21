import hashlib
import json
from pathlib import Path

from imagelab.db import initialize_database
from imagelab.repositories.runs import RunRepository
from imagelab.services.library import LibraryQuery, LibraryService


def seed(connection, root: Path, index: int, **overrides):
    run_id = f"00000000-0000-0000-0000-{index:012d}"
    receipt = {
        "run_id": run_id,
        "family_id": overrides.get("family_id", run_id),
        "parent_run_id": None,
        "relationship": "original",
        "model_id": overrides.get("model_id", "qwen-image-2.1-local"),
        "title": overrides.get("title", f"Image {index}"),
        "prompt": overrides.get("prompt", f"prompt {index}"),
        "profile": "fast",
        "parameters": {"width": 768, "height": 768, "steps": 8, "seed": index},
        "created_at": f"2026-09-21T12:{index:02d}:00Z",
        "generation_state": overrides.get("state", "succeeded"),
        "archive_state": "local_only",
        "favorite": overrides.get("favorite", False),
        "deleted_at": overrides.get("deleted_at"),
        "library_folder": overrides.get("collection", "Inbox"),
    }
    if overrides.get("output", True):
        receipt["output"] = {"file": "output.png", "sha256": f"sha-{index}", "width": 768, "height": 768}
    path = root / run_id / "receipt.json"
    path.parent.mkdir(parents=True)
    raw = json.dumps(receipt).encode()
    path.write_bytes(raw)
    with connection:
        RunRepository(connection).upsert_receipt(receipt, path, hashlib.sha256(raw).hexdigest())
    return run_id


def test_library_page_contains_only_completed_nontrashed_images(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    seed(connection, tmp_path, 1)
    seed(connection, tmp_path, 2, output=False, state="running")
    seed(connection, tmp_path, 3, deleted_at="2026-09-21T13:00:00Z")

    page = LibraryService(connection).page(LibraryQuery())

    assert [item["title"] for item in page.items] == ["Image 1"]
    assert page.total_images == 1
    assert page.total_families == 1


def test_library_query_filters_search_model_collection_and_favorite(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    wanted = seed(connection, tmp_path, 1, title="Golden flower", collection="Collections/Botanical", favorite=True)
    seed(connection, tmp_path, 2, title="Other", collection="Inbox")

    page = LibraryService(connection).page(LibraryQuery(search="flower", model="qwen-image-2.1-local", collection="Collections/Botanical", favorite=True))

    assert [item["run_id"] for item in page.items] == [wanted]


def test_library_pagination_is_bounded_and_stable(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    for index in range(1, 8):
        seed(connection, tmp_path, index)

    page = LibraryService(connection).page(LibraryQuery(page=2, per_page=3))

    assert [item["title"] for item in page.items] == ["Image 4", "Image 3", "Image 2"]
    assert page.page == 2
    assert page.pages == 3
    assert page.per_page == 3


def test_library_family_view_returns_latest_visible_version_per_family(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    family = "11111111-1111-1111-1111-111111111111"
    seed(connection, tmp_path, 1, family_id=family)
    latest = seed(connection, tmp_path, 2, family_id=family)
    other = seed(connection, tmp_path, 3)

    page = LibraryService(connection).page(LibraryQuery(family_view=True))

    assert [item["run_id"] for item in page.items] == [other, latest]
    assert page.total_images == 2


def test_library_rejects_unbounded_or_invalid_query_values(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    service = LibraryService(connection)

    for query in [LibraryQuery(page=0), LibraryQuery(per_page=101), LibraryQuery(search="x" * 201)]:
        try:
            service.page(query)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid library query accepted")
