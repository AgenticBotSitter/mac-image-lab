import json
from pathlib import Path

import pytest

from imagelab.services.archive import archive_evidence


class FakeR2:
    def __init__(self, *, mismatch_key=None, fail_key=None):
        self.objects = {}
        self.mismatch_key = mismatch_key
        self.fail_key = fail_key

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        if self.fail_key and Key.endswith(self.fail_key):
            raise OSError("simulated upload failure")
        self.objects[Key] = {"body": bytes(Body), "metadata": dict(Metadata)}

    def head_object(self, *, Bucket, Key):
        value = self.objects[Key]
        size = len(value["body"])
        if self.mismatch_key and Key.endswith(self.mismatch_key):
            size += 1
        return {"ContentLength": size, "Metadata": value["metadata"]}


def make_run(tmp_path, *, with_reference=True):
    run_id = "12345678-1234-1234-1234-123456789abc"
    run = tmp_path / run_id
    run.mkdir()
    receipt = {
        "schema_version": 2,
        "run_id": run_id,
        "status": "local_only",
        "generation_state": "succeeded",
        "archive_state": "local_only",
        "model_id": "qwen-image-2.1-local",
        "profile": "fast",
        "models": {"unet": "qwen.safetensors"},
        "family_id": run_id,
        "parent_run_id": None,
        "relationship": "reference_transform" if with_reference else "original",
    }
    if with_reference:
        receipt["reference_edit"] = {
            "source_file": "reference-original.jpg",
            "inference_file": "reference.png",
            "original_sha256": "recorded-original",
            "derivative_sha256": "recorded-derivative",
        }
        (run / "reference-original.jpg").write_bytes(b"original")
        (run / "reference.png").write_bytes(b"derivative")
    for name in ["workflow.json", "comfy-history.json", "comfy-submit.json"]:
        (run / name).write_text("{}\n")
    (run / "output.png").write_bytes(b"output")
    (run / "receipt.json").write_text(json.dumps(receipt))
    return run, receipt


def test_archive_snapshots_and_verifies_reference_and_evidence(tmp_path):
    run, receipt = make_run(tmp_path)
    client = FakeR2()

    result = archive_evidence(
        run,
        receipt,
        client_factory=lambda: client,
        bucket="hermes-data",
        prefix="Marvin/Mac Image Lab/runs",
        now_fn=lambda: "2026-09-21T00:00:00Z",
    )

    names = {key.rsplit("/", 1)[-1] for key in client.objects}
    assert {"reference-original.jpg", "reference.png", "output.png", "workflow.json", "comfy-history.json", "comfy-submit.json", "receipt.json", "model-manifest.json", "lineage.json", "archive.json"} <= names
    assert result["generation_state"] == "succeeded"
    assert result["archive_state"] == "verified"
    assert result["archive"]["status"] == "ok"
    assert all(item["head_verified"] is True for item in result["archive"]["objects"])
    local_manifest = json.loads((run / "archive.json").read_text())
    assert local_manifest["receipt_schema_version"] == 2


def test_missing_reference_marks_archive_failed_without_changing_generation(tmp_path):
    run, receipt = make_run(tmp_path)
    (run / "reference-original.jpg").unlink()

    with pytest.raises(FileNotFoundError, match="reference-original.jpg"):
        archive_evidence(run, receipt, client_factory=FakeR2, bucket="hermes-data", prefix="x", now_fn=lambda: "now")

    saved = json.loads((run / "receipt.json").read_text())
    assert saved["generation_state"] == "succeeded"
    assert saved["archive_state"] == "failed"
    assert saved["status"] == "local_only"


def test_head_mismatch_marks_failed(tmp_path):
    run, receipt = make_run(tmp_path, with_reference=False)
    client = FakeR2(mismatch_key="output.png")
    with pytest.raises(RuntimeError, match="head_object mismatch"):
        archive_evidence(run, receipt, client_factory=lambda: client, bucket="hermes-data", prefix="x", now_fn=lambda: "now")
    assert json.loads((run / "receipt.json").read_text())["archive_state"] == "failed"


def test_credential_factory_failure_is_recorded(tmp_path):
    run, receipt = make_run(tmp_path, with_reference=False)

    def unavailable():
        raise RuntimeError("credentials unavailable")

    with pytest.raises(RuntimeError, match="credentials unavailable"):
        archive_evidence(run, receipt, client_factory=unavailable, bucket="hermes-data", prefix="x", now_fn=lambda: "now")
    saved = json.loads((run / "receipt.json").read_text())
    assert saved["archive_state"] == "failed"
    assert "credentials unavailable" in saved["archive_error"]


def test_retry_is_idempotent_after_partial_failure(tmp_path):
    run, receipt = make_run(tmp_path, with_reference=False)
    failing = FakeR2(fail_key="workflow.json")
    with pytest.raises(OSError):
        archive_evidence(run, receipt, client_factory=lambda: failing, bucket="hermes-data", prefix="x", now_fn=lambda: "first")

    saved = json.loads((run / "receipt.json").read_text())
    working = FakeR2()
    result = archive_evidence(run, saved, client_factory=lambda: working, bucket="hermes-data", prefix="x", now_fn=lambda: "second")

    keys = [item["key"] for item in result["archive"]["objects"]]
    assert len(keys) == len(set(keys))
    assert result["archive_state"] == "verified"
