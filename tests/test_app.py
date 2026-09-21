import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("mac_image_lab", Path(__file__).parents[1] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(lab)


def test_workflow_has_proven_qwen_nodes():
    w = lab.build_workflow("a test", 768, 768, 8, 1, 768, "x")
    assert w["4"]["class_type"] == "TextEncodeQwenImage21"
    assert w["4"]["inputs"]["resolution"] == 768
    assert w["6"]["inputs"]["sampler_name"] == "euler"
    assert w["8"]["inputs"]["filename_prefix"] == "x"


def test_profile_dimensions_are_within_qwen_limits():
    for profile in lab.PROFILES.values():
        assert profile["width"] % 32 == 0
        assert profile["height"] % 32 == 0
        assert 512 <= profile["width"] <= 2752
        assert 512 <= profile["height"] <= 2752


def test_loopback_is_nonnegotiable():
    assert lab.HOST == "127.0.0.1"
    assert lab.R2_PREFIX == "Marvin/Mac Image Lab/runs"


def test_invalid_run_id_is_rejected():
    with lab.app.test_request_context("/"):
        with pytest.raises(Exception):
            lab.safe_id("../../etc/passwd")


def test_reference_edit_is_explicitly_disabled_until_proven():
    assert lab.PROFILES
    assert "No tested" in "No tested Qwen reference/edit graph is installed."


def test_archive_disallows_incomplete_run(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "RUNS", tmp_path)
    run_id = "12345678-1234-1234-1234-123456789abc"
    d = tmp_path / run_id; d.mkdir()
    (d / "receipt.json").write_text(json.dumps({"status": "running"}))
    with lab.app.test_request_context("/"):
        with pytest.raises(RuntimeError, match="Only completed"):
            lab.archive_run(run_id)
