import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("mac_image_lab", Path(__file__).parents[1] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def test_workflow_has_proven_qwen_nodes():
    workflow = lab.build_workflow("a test", 768, 768, 8, 1, 768, "x", "qwen-image-2.1-local")
    assert workflow["4"]["class_type"] == "TextEncodeQwenImage21"
    assert workflow["4"]["inputs"]["resolution"] == 768
    assert workflow["6"]["inputs"]["sampler_name"] == "euler"


def test_reference_edit_workflow_has_validated_conditioning_shape():
    workflow = lab.build_reference_edit_workflow("change the scene", 8, 1, 768, "x", "reference.png")
    assert workflow["4"]["class_type"] == "LoadImage"
    assert workflow["5"]["class_type"] == "TextEncodeQwenImage21"
    assert workflow["5"]["inputs"]["images"] == {"image_1": ["4", 0]}
    assert workflow["5"]["inputs"]["vae"] == ["3", 0]
    assert workflow["6"]["inputs"]["latent_image"] == ["5", 2]


def test_only_verified_model_is_available():
    assert lab.model_for("qwen-image-2.1-local")["source"] == "Local"
    with pytest.raises(ValueError):
        lab.model_for("not-a-model")


def test_profile_dimensions_are_within_qwen_limits():
    for profile in lab.PROFILES.values():
        assert profile["width"] % 32 == 0
        assert profile["height"] % 32 == 0
        assert 512 <= profile["width"] <= 2752
        assert 512 <= profile["height"] <= 2752


def test_loopback_and_r2_prefix_are_nonnegotiable():
    assert lab.HOST == "127.0.0.1"
    assert lab.R2_PREFIX == "Marvin/Mac Image Lab/runs"


def test_invalid_run_id_and_path_escape_are_rejected():
    with lab.app.test_request_context("/"):
        with pytest.raises(Exception):
            lab.safe_id("../../etc/passwd")
    with pytest.raises(ValueError):
        lab.safe_library_rel("../../Desktop")


def test_safe_nested_library_folder():
    assert lab.safe_library_rel("Collections/Floral Studies") == "Collections/Floral Studies"


def test_family_lineage_is_created(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "RUNS", tmp_path)
    parent_id = "12345678-1234-1234-1234-123456789abc"
    parent = {"run_id": parent_id, "family_id": parent_id, "model_id": "qwen-image-2.1-local", "profile": "fast", "parameters": {"width": 768, "height": 768, "steps": 8}, "library_folder": "Inbox", "title": "Test family"}
    child = lab.validate_and_create({"prompt": "new test"}, parent=parent)
    receipt = json.loads((tmp_path / child / "receipt.json").read_text())
    assert receipt["family_id"] == parent_id
    assert receipt["parent_run_id"] == parent_id


def test_archive_disallows_incomplete_run(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "RUNS", tmp_path)
    run_id = "12345678-1234-1234-1234-123456789abc"
    d = tmp_path / run_id
    d.mkdir()
    (d / "receipt.json").write_text(json.dumps({"status": "running"}))
    with lab.app.test_request_context("/"):
        with pytest.raises(RuntimeError, match="Only completed"):
            lab.archive_run(run_id)
