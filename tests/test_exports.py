import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from imagelab.services.exports import ExportError, build_family_zip, convert_image, resize_to_png


def source(path: Path, *, alpha=True):
    mode = "RGBA" if alpha else "RGB"
    color = (200, 40, 60, 120) if alpha else (200, 40, 60)
    image = Image.new(mode, (120, 80), color)
    exif = Image.Exif(); exif[0x010E] = "private test metadata"
    image.save(path, exif=exif)


def test_png_original_is_not_reencoded_and_jpeg_requires_alpha_background(tmp_path):
    path = tmp_path / "source.png"; source(path)
    assert convert_image(path, "png") == path.read_bytes()
    with pytest.raises(ExportError, match="background"):
        convert_image(path, "jpeg")
    data = convert_image(path, "jpeg", background="#ffffff")
    image = Image.open(io.BytesIO(data)); image.load()
    assert image.format == "JPEG" and image.mode == "RGB" and image.size == (120, 80)
    assert not image.getexif()


def test_webp_and_resized_png_strip_metadata_and_record_actual_dimensions(tmp_path):
    path = tmp_path / "source.png"; source(path, alpha=False)
    webp = Image.open(io.BytesIO(convert_image(path, "webp"))); webp.load()
    assert webp.format == "WEBP" and not webp.getexif()
    destination = tmp_path / "resized.png"
    dimensions = resize_to_png(path, destination, width=60, height=None)
    resized = Image.open(destination); resized.load()
    assert dimensions == (60, 40) and resized.size == (60, 40) and not resized.getexif()
    with pytest.raises(ExportError): resize_to_png(path, destination, width=10000, height=10000)


def test_family_zip_uses_safe_names_and_enforces_size_bound(tmp_path):
    runs = tmp_path / "runs"; runs.mkdir()
    receipts = []
    for index, title in [(1, "../Unsafe title"), (2, "Second image")]:
        run_id = f"42000000-0000-0000-0000-{index:012d}"
        directory = runs / run_id; directory.mkdir()
        output = directory / "output.png"; Image.new("RGB", (20, 20), (index * 50, 20, 30)).save(output)
        receipt = {"run_id": run_id, "title": title, "output": {"file": "output.png", "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}}
        (directory / "receipt.json").write_text(json.dumps(receipt)); receipts.append(receipt)
        if index == 1:
            (directory / "workflow.json").write_text('{"workflow": true}')
    payload = build_family_zip(runs, receipts, max_bytes=100_000)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        assert len(names) == 5
        assert any(name.endswith("workflow.json") for name in names)
        assert all(".." not in name and not name.startswith("/") for name in names)
        assert sum(name.endswith("output.png") for name in names) == 2
    with pytest.raises(ExportError, match="size limit"):
        build_family_zip(runs, receipts, max_bytes=10)


def test_export_routes_and_resized_child_preserve_lineage(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("mac_image_lab_exports_routes", Path(__file__).parents[1] / "app" / "app.py")
    lab = importlib.util.module_from_spec(spec); spec.loader.exec_module(lab)
    run_id = "43000000-0000-0000-0000-000000000001"
    family_id = "43000000-0000-0000-0000-000000000010"
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "library")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "library" / "Generated Images")
    directory = lab.RUNS / run_id; directory.mkdir(parents=True)
    output = directory / "output.png"; source(output)
    receipt = {
        "run_id": run_id, "family_id": family_id, "parent_run_id": None, "relationship": "original",
        "model_id": "qwen-image-2.1-local", "title": "Export source", "prompt": "export test", "profile": "fast",
        "parameters": {"width": 120, "height": 80, "steps": 8, "seed": 1}, "created_at": "2026-09-21T10:00:00Z",
        "generation_state": "succeeded", "archive_state": "local_only", "reference_edit": {"enabled": False},
        "output": {"file": "output.png", "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "width": 120, "height": 80},
    }
    lab.write_receipt(run_id, receipt)
    client = lab.app.test_client()
    png = client.get(f"/runs/{run_id}/export.png")
    assert png.status_code == 200 and png.data == output.read_bytes() and png.mimetype == "image/png"
    assert client.get(f"/runs/{run_id}/export.jpeg").status_code == 400
    jpeg = client.get(f"/runs/{run_id}/export.jpeg?background=%23ffffff")
    assert jpeg.status_code == 200 and jpeg.mimetype == "image/jpeg"
    webp = client.get(f"/runs/{run_id}/export.webp")
    assert webp.status_code == 200 and webp.mimetype == "image/webp"
    resized = client.post(f"/runs/{run_id}/exports/resized", data={"width": "60", "height": ""})
    assert resized.status_code == 302
    child_id = resized.headers["Location"].rstrip("/").split("/")[-1]
    child = lab.read_receipt(child_id)
    assert child["family_id"] == family_id and child["parent_run_id"] == run_id
    assert child["relationship"] == "resized_export" and child["output"]["width"] == 60 and child["output"]["height"] == 40
    archive = client.get(f"/families/{family_id}/export.zip")
    assert archive.status_code == 200 and archive.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(archive.data)) as bundle:
        assert sum(name.endswith("output.png") for name in bundle.namelist()) == 2

