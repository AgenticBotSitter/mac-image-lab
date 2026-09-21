import importlib.util
import io
import json
from pathlib import Path

from PIL import Image

SPEC = importlib.util.spec_from_file_location("mac_image_lab_lineage", Path(__file__).parents[1] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def png_bytes(size=(640, 480)):
    stream = io.BytesIO()
    Image.new("RGB", size, (90, 50, 120)).save(stream, format="PNG")
    return stream.getvalue()


class Upload:
    mimetype = "image/png"

    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload


def form(**overrides):
    value = {
        "prompt": "Change only the background to pale stone.",
        "model_id": "qwen-image-2.1-local",
        "profile": "fast",
        "library_folder": "Inbox",
        "action": "reference_transform",
    }
    value.update(overrides)
    return value


def configure(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "COMFY_ROOT", tmp_path / "comfy")
    (lab.COMFY_ROOT / "input").mkdir(parents=True)


def seed_source(run_id):
    directory = lab.RUNS / run_id
    directory.mkdir(parents=True)
    output = directory / "output.png"
    output.write_bytes(png_bytes())
    receipt = {
        "run_id": run_id,
        "family_id": run_id,
        "parent_run_id": None,
        "relationship": "original",
        "model_id": "qwen-image-2.1-local",
        "prompt": "purple bottle on linen",
        "profile": "fast",
        "parameters": {"width": 640, "height": 480, "steps": 8, "seed": 2},
        "generation_state": "succeeded",
        "archive_state": "local_only",
        "created_at": "2026-09-21T00:00:00Z",
        "output": {"file": "output.png", "width": 640, "height": 480, "sha256": "source-hash"},
    }
    (directory / "receipt.json").write_text(json.dumps(receipt))
    lab.write_receipt(run_id, receipt)
    return receipt


def test_existing_image_transform_is_child_in_same_family(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    source = seed_source("11111111-1111-1111-1111-111111111111")

    child_id = lab.create_reference_transform(form(source_run_id=source["run_id"]), None)
    child = lab.read_receipt(child_id)

    assert child["family_id"] == source["family_id"]
    assert child["parent_run_id"] == source["run_id"]
    assert child["relationship"] == "reference_transform"
    assert child["reference_edit"]["source_run_id"] == source["run_id"]
    assert (lab.RUNS / child_id / "reference-original.png").read_bytes() == (lab.RUNS / source["run_id"] / "output.png").read_bytes()


def test_external_transform_creates_new_family_with_source_asset(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)

    child_id = lab.create_reference_transform(form(), Upload(png_bytes()))
    child = lab.read_receipt(child_id)

    assert child["family_id"] == child_id
    assert child["parent_run_id"] is None
    assert child["reference_edit"]["source_run_id"] is None
    assert (lab.RUNS / child_id / child["reference_edit"]["source_file"]).is_file()


def test_repeating_transform_keeps_reference_workflow_and_lineage(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    source = seed_source("22222222-2222-2222-2222-222222222222")
    transform_id = lab.create_reference_transform(form(source_run_id=source["run_id"]), None)
    transform = lab.read_receipt(transform_id)

    repeat_id = lab.create_reference_transform(form(action="repeat", prompt=""), None, parent=transform)
    repeat = lab.read_receipt(repeat_id)

    assert repeat["family_id"] == source["family_id"]
    assert repeat["parent_run_id"] == transform_id
    assert repeat["relationship"] == "repeat"
    assert repeat["reference_edit"]["enabled"] is True
    workflow = json.loads((lab.RUNS / repeat_id / "workflow.json").read_text())
    assert any(node.get("class_type") == "LoadImage" for node in workflow.values())
