import hashlib
import importlib.util
import json
from pathlib import Path

from jinja2 import FileSystemLoader
from PIL import Image

from imagelab.services.media import ThumbnailService

SPEC = importlib.util.spec_from_file_location("mac_image_lab_media", Path(__file__).parents[1] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def image(path: Path, size=(1200, 800), color="red") -> str:
    Image.new("RGB", size, color).save(path, format="PNG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_thumbnail_preserves_aspect_and_is_keyed_by_source_hash(tmp_path):
    source = tmp_path / "source.png"
    digest = image(source)
    service = ThumbnailService(tmp_path / "cache")

    result = service.get_or_create(source, digest, 320)

    assert result.width == 320
    assert result.height == 213
    assert result.path.name == "320.webp"
    assert result.path.parent.name == digest
    assert result.path.exists()


def test_changed_hash_uses_new_cache_key(tmp_path):
    source = tmp_path / "source.png"
    first = image(source, color="red")
    service = ThumbnailService(tmp_path / "cache")
    one = service.get_or_create(source, first, 320)
    second = image(source, color="blue")

    two = service.get_or_create(source, second, 320)

    assert one.path != two.path
    assert one.path.exists()
    assert two.path.exists()


def test_thumbnail_write_is_atomic_and_leaves_no_temporary_file(tmp_path):
    source = tmp_path / "source.png"
    digest = image(source)
    service = ThumbnailService(tmp_path / "cache")

    result = service.get_or_create(source, digest, 640)

    assert result.path.exists()
    assert list(result.path.parent.glob("*.tmp")) == []


def test_invalid_thumbnail_size_is_rejected(tmp_path):
    source = tmp_path / "source.png"
    digest = image(source)
    service = ThumbnailService(tmp_path / "cache")

    try:
        service.get_or_create(source, digest, 9999)
    except ValueError as exc:
        assert "thumbnail size" in str(exc).lower()
    else:
        raise AssertionError("invalid size accepted")


def test_library_grid_uses_private_thumbnails_not_originals(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(lab, "RUNS", runs)
    monkeypatch.setattr(lab, "THUMBNAIL_ROOT", tmp_path / "thumbnails")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "library")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "library-root")
    monkeypatch.setattr(lab.app, "jinja_loader", FileSystemLoader(Path(__file__).parents[1] / "app" / "templates"))
    run_id = "12345678-1234-1234-1234-123456789abc"
    directory = runs / run_id
    directory.mkdir(parents=True)
    digest = image(directory / "output.png", size=(1200, 800))
    receipt = {
        "run_id": run_id,
        "family_id": run_id,
        "relationship": "original",
        "model_id": "qwen-image-2.1-local",
        "title": "Thumbnail test",
        "prompt": "test",
        "profile": "fast",
        "parameters": {"width": 1200, "height": 800, "steps": 8, "seed": 1},
        "created_at": "2026-09-21T12:00:00Z",
        "generation_state": "succeeded",
        "archive_state": "local_only",
        "output": {"file": "output.png", "sha256": digest, "width": 1200, "height": 800},
    }
    (directory / "receipt.json").write_text(json.dumps(receipt))
    lab.write_receipt(run_id, receipt)
    client = lab.app.test_client()

    library = client.get("/")
    thumbnail = client.get(f"/media/{run_id}/thumbnail/640")

    assert f"/media/{run_id}/thumbnail/640" in library.get_data(as_text=True)
    assert f"/runs/{run_id}/download/output.png" not in library.get_data(as_text=True)
    assert thumbnail.status_code == 200
    assert thumbnail.mimetype == "image/webp"
    assert thumbnail.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    assert thumbnail.headers["ETag"] == f'"{digest}-640"'
    assert thumbnail.headers["X-Image-Width"] == "640"
    assert thumbnail.headers["X-Image-Height"] == "427"
