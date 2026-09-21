import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

from imagelab.db import initialize_database
from imagelab.services.organization import MetadataConflict, OrganizationService

SPEC = importlib.util.spec_from_file_location("mac_image_lab_organization", Path(__file__).parents[1] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def seed_run(root: Path, run_id: str = "41000000-0000-0000-0000-000000000001") -> dict:
    directory = root / run_id; directory.mkdir(parents=True)
    output = directory / "output.png"; Image.new("RGBA", (80, 60), (120, 80, 40, 180)).save(output)
    receipt = {
        "run_id": run_id, "family_id": "41000000-0000-0000-0000-000000000010", "parent_run_id": None,
        "relationship": "original", "model_id": "qwen-image-2.1-local", "title": "Original title", "prompt": "test",
        "profile": "fast", "parameters": {"width": 80, "height": 60, "steps": 8, "seed": 4},
        "created_at": "2026-09-21T10:00:00Z", "generation_state": "succeeded", "archive_state": "local_only",
        "output": {"file": "output.png", "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "width": 80, "height": 60},
        "reference_edit": {"enabled": False},
    }
    (directory / "receipt.json").write_text(json.dumps(receipt))
    return receipt


def store(connection, receipt, root):
    from imagelab.repositories.runs import RunRepository
    RunRepository(connection).upsert_receipt(receipt, root / receipt["run_id"] / "receipt.json", "a" * 64)


def test_metadata_updates_require_current_revision(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    receipt = seed_run(tmp_path / "runs"); store(connection, receipt, tmp_path / "runs")
    service = OrganizationService(connection)
    updated = service.update_metadata(receipt["run_id"], revision=1, title="Edited title", favorite=True)
    assert updated == {"title": "Edited title", "favorite": True, "deleted_at": None, "revision": 2}
    with pytest.raises(MetadataConflict): service.update_metadata(receipt["run_id"], revision=1, favorite=False)
    row = connection.execute("SELECT title, favorite FROM runs WHERE id=?", (receipt["run_id"],)).fetchone()
    assert tuple(row) == ("Edited title", 1)


def test_trash_is_reversible_and_does_not_delete_files(tmp_path):
    connection = initialize_database(tmp_path / "library.sqlite3")
    receipt = seed_run(tmp_path / "runs"); store(connection, receipt, tmp_path / "runs")
    service = OrganizationService(connection)
    trashed = service.update_metadata(receipt["run_id"], revision=1, trashed=True)
    assert trashed["deleted_at"] and (tmp_path / "runs" / receipt["run_id"] / "output.png").is_file()
    restored = service.update_metadata(receipt["run_id"], revision=2, trashed=False)
    assert restored["deleted_at"] is None and (tmp_path / "runs" / receipt["run_id"] / "receipt.json").is_file()


def test_nested_collection_rejects_traversal_and_symlink_escape(tmp_path):
    root = tmp_path / "library"; root.mkdir()
    service = OrganizationService(initialize_database(tmp_path / "library.sqlite3"), library_root=root)
    assert service.create_collection("Clients/Autumn 2026") == root / "Clients" / "Autumn 2026"
    for bad in ("../escape", "/absolute", "Clients/../../escape", ".hidden"):
        with pytest.raises(ValueError): service.create_collection(bad)
    outside = tmp_path / "outside"; outside.mkdir(); (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError): service.create_collection("link/escape")


def test_file_copy_is_duplicate_safe_and_writes_family_manifest(tmp_path, monkeypatch):
    receipt = seed_run(tmp_path / "runs")
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "lab")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "lab" / "Generated Images")
    lab.write_receipt(receipt["run_id"], receipt)
    first = lab.file_run_output(receipt["run_id"], "Clients/Autumn")
    second = lab.file_run_output(receipt["run_id"], "Clients/Autumn")
    assert first == second
    collection = tmp_path / "lab" / "Generated Images" / "Clients" / "Autumn"
    assert len(list(collection.glob("*.png"))) == 1
    manifest = json.loads((collection / "family.json").read_text())
    assert manifest["family_id"] == receipt["family_id"]
    assert manifest["members"][0]["relationship"] == "original"


def test_metadata_route_updates_title_and_rejects_stale_form(tmp_path, monkeypatch):
    receipt = seed_run(tmp_path / "runs")
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "lab")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "lab" / "Generated Images")
    lab.write_receipt(receipt["run_id"], receipt)
    client = lab.app.test_client()
    response = client.post(f"/runs/{receipt['run_id']}/metadata", data={"revision": "1", "title": "Renamed artwork", "favorite": "1"})
    assert response.status_code == 302
    page = client.get(f"/runs/{receipt['run_id']}").get_data(as_text=True)
    assert "Renamed artwork" in page and "Remove favorite" in page
    stale = client.post(f"/runs/{receipt['run_id']}/metadata", data={"revision": "1", "title": "Stale overwrite"})
    assert stale.status_code == 409
    assert "changed in another tab" in stale.get_data(as_text=True)
