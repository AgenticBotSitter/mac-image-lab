import hashlib
import importlib.util
import io
import json
import struct
import warnings
import zlib
from pathlib import Path

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from imagelab import storage

APP_SPEC = importlib.util.spec_from_file_location("mac_image_lab_uploads", Path(__file__).parents[1] / "app" / "app.py")
lab = importlib.util.module_from_spec(APP_SPEC)
APP_SPEC.loader.exec_module(lab)


def image_bytes(fmt="PNG", size=(32, 24), *, exif=None, save_all=False, append_images=None):
    buffer = io.BytesIO()
    options = {"save_all": save_all, "append_images": append_images or []}
    if exif is not None:
        options["exif"] = exif
    Image.new("RGB", size, "blue").save(buffer, format=fmt, **options)
    return buffer.getvalue()


def png_with_dimensions(width, height):
    data = bytearray(image_bytes())
    data[16:24] = struct.pack(">II", width, height)
    data[29:33] = struct.pack(">I", zlib.crc32(bytes(data[12:29])) & 0xFFFFFFFF)
    return bytes(data)


def test_valid_png_is_fully_decoded_and_normalized():
    result = storage.ingest_reference(image_bytes(), "image/png")
    assert (result.width, result.height) == (32, 24)
    assert result.source_format == "PNG"
    assert result.original_suffix == ".png"
    assert result.derivative_suffix == ".png"
    with Image.open(io.BytesIO(result.derivative_bytes)) as derivative:
        derivative.load()
        assert derivative.size == (32, 24)
        assert not derivative.getexif()


@pytest.mark.parametrize("mime", ["image/heic", "text/plain", "image/gif"])
def test_unsupported_declared_type_is_rejected(mime):
    with pytest.raises(ValueError, match="PNG, JPEG, or WebP"):
        storage.ingest_reference(image_bytes(), mime)


def test_forged_mime_and_corrupt_or_truncated_images_are_rejected():
    with pytest.raises(ValueError, match="does not match"):
        storage.ingest_reference(image_bytes("JPEG"), "image/png")
    with pytest.raises(ValueError, match="valid image"):
        storage.ingest_reference(b"not an image", "image/png")
    with pytest.raises(ValueError, match="valid image"):
        storage.ingest_reference(image_bytes()[:30], "image/png")


def test_compressed_and_decoded_limits_are_enforced():
    with pytest.raises(ValueError, match="20 MiB"):
        storage.ingest_reference(b"x" * (storage.MAX_UPLOAD_BYTES + 1), "image/png")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ValueError, match="pixel limit"):
            storage.ingest_reference(png_with_dimensions(10000, 6000), "image/png")


def test_animation_is_rejected():
    second = Image.new("RGB", (32, 24), "red")
    animated = image_bytes("PNG", save_all=True, append_images=[second])
    with pytest.raises(ValueError, match="Animated"):
        storage.ingest_reference(animated, "image/png")


def test_exif_orientation_is_applied_and_metadata_removed():
    exif = Image.Exif()
    exif[274] = 6
    original = image_bytes("JPEG", size=(40, 20), exif=exif)
    result = storage.ingest_reference(original, "image/jpeg")
    assert (result.width, result.height) == (20, 40)
    assert result.exif_transposed is True
    assert result.original_sha256 != result.derivative_sha256
    with Image.open(io.BytesIO(result.derivative_bytes)) as derivative:
        assert derivative.size == (20, 40)
        assert not derivative.getexif()


def test_atomic_write_rejects_path_escape_and_leaves_no_partial(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        storage.atomic_write_beneath(tmp_path, "../outside.png", b"data")
    assert list(tmp_path.iterdir()) == []


def test_atomic_write_replaces_complete_file(tmp_path):
    path = storage.atomic_write_beneath(tmp_path, "nested/reference.png", b"complete")
    assert path.read_bytes() == b"complete"
    assert not list(path.parent.glob("*.tmp"))


def test_transform_stores_original_and_normalized_inference_derivative(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    comfy = tmp_path / "comfy"
    (comfy / "input").mkdir(parents=True)
    exif = Image.Exif()
    exif[274] = 6
    original = image_bytes("JPEG", size=(40, 20), exif=exif)
    upload = FileStorage(stream=io.BytesIO(original), filename="../../private.jpg", content_type="image/jpeg")
    monkeypatch.setattr(lab, "RUNS", runs)
    monkeypatch.setattr(lab, "COMFY_ROOT", comfy)

    run_id = lab.create_reference_transform({"prompt": "change scene", "profile": "fast"}, upload)
    receipt = json.loads((runs / run_id / "receipt.json").read_text())

    assert (runs / run_id / "reference-original.jpg").read_bytes() == original
    derivative = (runs / run_id / "reference.png").read_bytes()
    assert receipt["reference_edit"]["source_file"] == "reference-original.jpg"
    assert receipt["reference_edit"]["inference_file"] == "reference.png"
    assert receipt["reference_edit"]["source_width"] == 20
    assert receipt["reference_edit"]["source_height"] == 40
    assert receipt["reference_edit"]["original_sha256"] == hashlib.sha256(original).hexdigest()
    comfy_files = list((comfy / "input").glob(f"mac-image-lab-reference-{run_id}.png"))
    assert len(comfy_files) == 1
    assert comfy_files[0].read_bytes() == derivative


def test_invalid_transform_upload_leaves_no_run_or_backend_file(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    comfy = tmp_path / "comfy"
    (comfy / "input").mkdir(parents=True)
    upload = FileStorage(stream=io.BytesIO(b"bad"), filename="bad.png", content_type="image/png")
    monkeypatch.setattr(lab, "RUNS", runs)
    monkeypatch.setattr(lab, "COMFY_ROOT", comfy)

    with pytest.raises(ValueError, match="valid image"):
        lab.create_reference_transform({"prompt": "change scene", "profile": "fast"}, upload)

    assert not runs.exists() or list(runs.iterdir()) == []
    assert list((comfy / "input").iterdir()) == []


def test_backend_write_failure_cleans_staged_run(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    comfy = tmp_path / "comfy"
    (comfy / "input").mkdir(parents=True)
    upload = FileStorage(stream=io.BytesIO(image_bytes()), filename="okay.png", content_type="image/png")
    real_write = storage.atomic_write_beneath

    def fail_backend(root, relative, data):
        if root == comfy / "input":
            raise OSError("simulated backend write failure")
        return real_write(root, relative, data)

    monkeypatch.setattr(lab, "RUNS", runs)
    monkeypatch.setattr(lab, "COMFY_ROOT", comfy)
    monkeypatch.setattr(storage, "atomic_write_beneath", fail_backend)

    with pytest.raises(OSError, match="simulated"):
        lab.create_reference_transform({"prompt": "change scene", "profile": "fast"}, upload)

    assert list(runs.iterdir()) == []
    assert list((comfy / "input").iterdir()) == []


def test_transform_request_over_20_mib_returns_413():
    client = lab.app.test_client()
    response = client.post(
        "/transform",
        data={
            "prompt": "change scene",
            "profile": "fast",
            "reference": (io.BytesIO(b"x" * (storage.MAX_UPLOAD_BYTES + 1)), "large.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 413
