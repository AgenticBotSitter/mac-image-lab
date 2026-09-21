import importlib.util
from pathlib import Path

import pytest

from imagelab.models.contracts import ModelSpec, UnsupportedOperation
from imagelab.models.qwen21 import Qwen21Adapter
from imagelab.models.registry import ModelRegistry, registry
from imagelab.validation import GenerationRequest


def request(action="original"):
    return GenerationRequest(
        prompt="a test",
        model_id="qwen-image-2.1-local",
        profile="fast",
        width=768,
        height=768,
        steps=8,
        seed=1,
        resolution=768,
        action=action,
    )


def test_registry_exposes_only_validated_available_qwen():
    available = registry.available()
    assert [spec.id for spec in available] == ["qwen-image-2.1-local"]
    spec = available[0]
    assert spec.installed is True
    assert spec.validated is True
    assert spec.available is True
    assert spec.adapter_id == "qwen-image-2.1-comfy"
    assert spec.capabilities == frozenset({"text_to_image", "reference_transform", "rgba"})
    assert "best effort" in spec.warnings[0].lower()


def test_text_workflow_keeps_validated_qwen_wiring_and_models():
    workflow = Qwen21Adapter().build_workflow(request(), prefix="test")
    assert workflow["1"]["inputs"]["unet_name"] == "qwen_image_2.1_int8_convrot.safetensors"
    assert workflow["2"]["inputs"]["clip_name"] == "qwen3vl_8b_int8_convrot.safetensors"
    assert workflow["3"]["inputs"]["vae_name"] == "qwen_image_2.1_vae_bf16.safetensors"
    assert workflow["4"]["class_type"] == "TextEncodeQwenImage21"
    assert workflow["5"]["inputs"] == {"width": 768, "height": 768, "batch_size": 1}
    assert workflow["6"]["inputs"]["latent_image"] == ["5", 0]
    assert workflow["8"]["inputs"]["filename_prefix"] == "test"


def test_reference_workflow_keeps_validated_source_conditioning():
    workflow = Qwen21Adapter().build_workflow(request("reference_transform"), prefix="test", input_name="reference.png")
    assert workflow["4"] == {"class_type": "LoadImage", "inputs": {"image": "reference.png"}}
    assert workflow["5"]["inputs"]["images"] == {"image_1": ["4", 0]}
    assert workflow["5"]["inputs"]["vae"] == ["3", 0]
    assert workflow["6"]["inputs"]["latent_image"] == ["5", 2]


def test_reference_workflow_requires_a_source_name():
    with pytest.raises(ValueError, match="source image"):
        Qwen21Adapter().build_workflow(request("reference_transform"), prefix="test")


def test_unsupported_runtime_operations_are_explicit():
    adapter = Qwen21Adapter()
    assert isinstance(adapter.cancel({"prompt_id": "x"}), UnsupportedOperation)
    assert isinstance(adapter.unload(), UnsupportedOperation)


def test_new_model_metadata_changes_registry_view_without_template_changes():
    spec = ModelSpec(
        id="future-test-model",
        label="Future Test",
        version="0",
        source="Local",
        adapter_id="future-adapter",
        installed=False,
        validated=False,
        available=False,
        capabilities=frozenset({"text_to_image"}),
        profiles={"fast": {"width": 512, "height": 512, "steps": 1, "resolution": 512}},
        guidance={"summary": "Future-specific guidance"},
        warnings=("Not validated",),
        artifacts={},
        runtime_estimate_provenance="No measurement",
    )

    class FakeAdapter:
        def __init__(self, value):
            self.spec = value

    test_registry = ModelRegistry()
    test_registry.register(spec, FakeAdapter(spec))

    assert test_registry.available() == []
    assert test_registry.legacy_view()[spec.id]["guide"]["summary"] == "Future-specific guidance"
    assert test_registry.legacy_view()[spec.id]["status"] == "unavailable"


def test_legacy_reference_upload_is_retired_without_writing(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("mac_image_lab_adapter_test", Path(__file__).parents[1] / "app" / "app.py")
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    monkeypatch.setattr(lab, "REFERENCES", tmp_path / "references")

    response = lab.app.test_client().post("/reference/upload")

    assert response.status_code == 410
    assert response.get_json()["transform_url"] == "/transform"
    assert not (tmp_path / "references").exists()
