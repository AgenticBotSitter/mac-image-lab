import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image

SPEC = importlib.util.spec_from_file_location(
    "mac_image_lab_release_check",
    Path(__file__).parents[1] / "scripts" / "release_check.py",
)
release_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_check)


def make_run(root: Path, run_id: str, *, parent_run_id=None, family_id=None):
    directory = root / run_id
    directory.mkdir(parents=True)
    output = directory / "output.png"
    Image.new("RGB", (64, 48), (30, 60, 90)).save(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    receipt = {
        "run_id": run_id,
        "family_id": family_id or run_id,
        "parent_run_id": parent_run_id,
        "relationship": "reference_transform" if parent_run_id else "original",
        "generation_state": "succeeded",
        "output": {"file": "output.png", "sha256": digest, "width": 64, "height": 48},
    }
    for name, payload in {
        "receipt.json": receipt,
        "workflow.json": {"prompt": {}},
        "comfy-submit.json": {"prompt_id": "backend-id"},
        "comfy-history.json": {"backend-id": {"status": {"completed": True}}},
    }.items():
        (directory / name).write_text(json.dumps(payload))
    return receipt


def test_validate_run_verifies_evidence_output_and_lineage(tmp_path):
    parent_id = "10000000-0000-0000-0000-000000000001"
    child_id = "10000000-0000-0000-0000-000000000002"
    make_run(tmp_path, parent_id)
    make_run(tmp_path, child_id, parent_run_id=parent_id, family_id=parent_id)

    report = release_check.validate_run(tmp_path, child_id)

    assert report["status"] == "ok"
    assert report["output"]["sha256_verified"] is True
    assert report["output"]["actual_dimensions"] == [64, 48]
    assert report["lineage"]["parent_exists"] is True
    assert report["lineage"]["family_matches_parent"] is True
    assert set(report["evidence"]) == {
        "receipt.json", "workflow.json", "comfy-submit.json", "comfy-history.json", "output.png"
    }


def test_validate_run_fails_for_missing_declared_output(tmp_path):
    run_id = "30000000-0000-0000-0000-000000000001"
    make_run(tmp_path, run_id)
    receipt_path = tmp_path / run_id / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["output"]["file"] = "missing.png"
    receipt_path.write_text(json.dumps(receipt))

    report = release_check.validate_run(tmp_path, run_id)

    assert report["status"] == "failed"
    assert any("declared output" in error.lower() for error in report["errors"])


def test_validate_run_rejects_output_path_escape(tmp_path):
    run_id = "40000000-0000-0000-0000-000000000001"
    make_run(tmp_path, run_id)
    receipt_path = tmp_path / run_id / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["output"]["file"] = "../outside.png"
    receipt_path.write_text(json.dumps(receipt))

    report = release_check.validate_run(tmp_path, run_id)

    assert report["status"] == "failed"
    assert any("safe relative filename" in error.lower() for error in report["errors"])


def test_validate_run_requires_both_dimensions(tmp_path):
    run_id = "50000000-0000-0000-0000-000000000001"
    make_run(tmp_path, run_id)
    receipt_path = tmp_path / run_id / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["output"].pop("width")
    receipt_path.write_text(json.dumps(receipt))

    report = release_check.validate_run(tmp_path, run_id)

    assert report["status"] == "failed"
    assert any("width and height" in error.lower() for error in report["errors"])


def test_validate_run_fails_closed_for_tampered_output(tmp_path):
    run_id = "20000000-0000-0000-0000-000000000001"
    make_run(tmp_path, run_id)
    (tmp_path / run_id / "output.png").write_bytes(b"tampered")

    report = release_check.validate_run(tmp_path, run_id)

    assert report["status"] == "failed"
    assert any("hash" in error.lower() for error in report["errors"])
