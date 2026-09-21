import importlib.util
import io
import json
from pathlib import Path

import pytest
from jinja2 import FileSystemLoader
from PIL import Image
from werkzeug.datastructures import FileStorage


SPEC = importlib.util.spec_from_file_location("mac_image_lab_regressions", Path(__file__).parents[1] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def png_upload() -> FileStorage:
    data = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(data, format="PNG")
    data.seek(0)
    return FileStorage(stream=data, filename="reference.png", content_type="image/png")


def test_larger_profile_overrides_parent_dimensions(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "RUNS", tmp_path)
    parent_id = "12345678-1234-1234-1234-123456789abc"
    parent = {
        "run_id": parent_id,
        "family_id": parent_id,
        "model_id": "qwen-image-2.1-local",
        "profile": "fast",
        "parameters": {"width": 768, "height": 768, "steps": 8},
        "library_folder": "Inbox",
        "title": "Parent",
    }

    child_id = lab.validate_and_create({"prompt": "larger", "profile": "maximum"}, parent=parent)
    receipt = json.loads((tmp_path / child_id / "receipt.json").read_text())

    assert receipt["parameters"]["width"] == lab.PROFILES["maximum"]["width"]
    assert receipt["parameters"]["height"] == lab.PROFILES["maximum"]["height"]
    assert receipt["parameters"]["steps"] == lab.PROFILES["maximum"]["steps"]


def test_transform_rejects_unknown_profile_before_writes(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    comfy = tmp_path / "comfy"
    (comfy / "input").mkdir(parents=True)
    monkeypatch.setattr(lab, "RUNS", runs)
    monkeypatch.setattr(lab, "COMFY_ROOT", comfy)

    with pytest.raises(ValueError, match="Unknown profile"):
        lab.create_reference_transform({"prompt": "change it", "profile": "missing"}, png_upload())

    assert not runs.exists() or list(runs.iterdir()) == []
    assert list((comfy / "input").iterdir()) == []


class FakeR2:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        self.objects[Key] = {"body": Body, "metadata": Metadata}

    def head_object(self, *, Bucket, Key):
        value = self.objects[Key]
        return {"ContentLength": len(value["body"]), "Metadata": value["metadata"]}


def test_archive_includes_reference_source(tmp_path, monkeypatch):
    run_id = "12345678-1234-1234-1234-123456789abc"
    run = tmp_path / run_id
    run.mkdir()
    receipt = {
        "run_id": run_id,
        "status": "local_only",
        "reference_edit": {"source_file": "reference.png"},
    }
    for name in ["workflow.json", "comfy-history.json", "comfy-submit.json"]:
        (run / name).write_text("{}\n")
    (run / "output.png").write_bytes(b"output")
    (run / "reference.png").write_bytes(b"reference")
    (run / "receipt.json").write_text(json.dumps(receipt))
    fake = FakeR2()
    monkeypatch.setattr(lab, "RUNS", tmp_path)
    monkeypatch.setattr(lab, "r2_client", lambda: fake)

    lab.archive_run(run_id)

    assert f"{lab.R2_PREFIX}/{run_id}/reference.png" in fake.objects


@pytest.mark.xfail(strict=True, reason="T03/T12 detail status uses actual output dimensions")
def test_run_detail_displays_actual_output_dimensions(tmp_path, monkeypatch):
    run_id = "12345678-1234-1234-1234-123456789abc"
    run = tmp_path / run_id
    run.mkdir()
    receipt = {
        "run_id": run_id,
        "family_id": run_id,
        "status": "local_only",
        "title": "Output size",
        "model_id": "qwen-image-2.1-local",
        "prompt": "test",
        "parameters": {"width": 768, "height": 768, "steps": 8, "seed": 1},
        "output": {"file": "output.png", "width": 1024, "height": 896},
    }
    (run / "receipt.json").write_text(json.dumps(receipt))
    monkeypatch.setattr(lab, "RUNS", tmp_path)
    monkeypatch.setattr(lab, "family_groups", lambda: [{"family_id": run_id, "runs": [receipt]}])
    monkeypatch.setattr(lab, "list_library_folders", lambda: ["Inbox"])
    monkeypatch.setattr(lab.app, "jinja_loader", FileSystemLoader(Path(__file__).parents[1] / "app" / "templates"))

    response = lab.app.test_client().get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert "1024×896" in response.get_data(as_text=True)


def test_duplicate_generate_submission_enqueues_once(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(lab, "RUNS", runs)
    client = lab.app.test_client()
    form = {"prompt": "one", "idempotency_key": "same-browser-submit"}

    first = client.post("/generate", data=form)
    second = client.post("/generate", data=form)

    assert first.status_code == 302
    assert second.status_code == 302
    assert first.headers["Location"] == second.headers["Location"]
    connection = lab.initialize_database(lab.database_path())
    try:
        assert lab.JobRepository(connection).count(state="queued") == 1
    finally:
        connection.close()
    assert len([path for path in runs.iterdir() if path.is_dir()]) == 1
