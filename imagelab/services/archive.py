"""Explicit, verified R2 archival of immutable run evidence."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from imagelab.storage import atomic_write_beneath

BASE_EVIDENCE = ("output.png", "workflow.json", "comfy-history.json", "comfy-submit.json")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    text = re.sub(r"(?i)(secret|token|password|access[_ -]?key)\s*[=:]\s*\S+", r"\1=[REDACTED]", text)
    return f"{type(exc).__name__}: {text[:500]}"


def _put_verified(client: Any, *, bucket: str, key: str, data: bytes, content_type: str) -> dict[str, Any]:
    digest = _sha256(data)
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type, Metadata={"sha256": digest})
    head = client.head_object(Bucket=bucket, Key=key)
    if head.get("ContentLength") != len(data) or head.get("Metadata", {}).get("sha256") != digest:
        raise RuntimeError(f"head_object mismatch: {key}")
    return {"key": key, "bytes": len(data), "sha256": digest, "head_verified": True}


def _write_receipt(run_dir: Path, receipt: dict[str, Any]) -> None:
    atomic_write_beneath(run_dir, "receipt.json", _json_bytes(receipt))


def archive_evidence(
    run_dir: Path,
    receipt: dict[str, Any],
    *,
    client_factory: Callable[[], Any],
    bucket: str,
    prefix: str,
    now_fn: Callable[[], str],
) -> dict[str, Any]:
    """Snapshot and head-verify one completed run; safe to retry with the same keys."""
    run_dir = run_dir.resolve()
    value = deepcopy(receipt)
    legacy_status = value.get("status")
    generation_state = value.get("generation_state") or ("succeeded" if legacy_status in {"local_only", "archived", "archive_failed"} else legacy_status)
    if generation_state != "succeeded":
        raise RuntimeError("Only completed generation evidence can be archived")
    value["generation_state"] = "succeeded"
    value["archive_state"] = "archiving"
    value.pop("archive_error", None)
    _write_receipt(run_dir, value)

    try:
        names: list[str] = list(BASE_EVIDENCE)
        reference = value.get("reference_edit") or {}
        for field in ("source_file", "inference_file"):
            name = reference.get(field)
            if name and name not in names:
                names.append(name)

        for name in names:
            path = run_dir / name
            if not path.is_file():
                raise FileNotFoundError(name)

        model_manifest = {
            "schema_version": 1,
            "model_id": value.get("model_id"),
            "profile": value.get("profile"),
            "models": value.get("models", {}),
            "parameters": value.get("parameters", {}),
        }
        lineage = {
            "schema_version": 1,
            "run_id": value.get("run_id") or run_dir.name,
            "family_id": value.get("family_id"),
            "parent_run_id": value.get("parent_run_id"),
            "relationship": value.get("relationship", "original"),
            "reference_edit": reference,
        }
        atomic_write_beneath(run_dir, "model-manifest.json", _json_bytes(model_manifest))
        atomic_write_beneath(run_dir, "lineage.json", _json_bytes(lineage))
        names.extend(["model-manifest.json", "lineage.json"])

        client = client_factory()
        run_id = value.get("run_id") or run_dir.name
        key_root = f"{prefix.rstrip('/')}/{run_id}"
        result = {
            "run_id": run_id,
            "started_at": now_fn(),
            "receipt_schema_version": value.get("schema_version", 1),
            "objects": [],
        }
        for name in names:
            path = run_dir / name
            data = path.read_bytes()
            record = _put_verified(
                client,
                bucket=bucket,
                key=f"{key_root}/{name}",
                data=data,
                content_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
            )
            record["verified_at"] = now_fn()
            result["objects"].append(record)

        result.update(status="ok", completed_at=now_fn(), receipt_verified=True, manifest_verified=True)
        value["archive_state"] = "verified"
        value["archive"] = result
        _write_receipt(run_dir, value)
        receipt_data = (run_dir / "receipt.json").read_bytes()
        _put_verified(client, bucket=bucket, key=f"{key_root}/receipt.json", data=receipt_data, content_type="application/json")

        archive_data = _json_bytes(result)
        atomic_write_beneath(run_dir, "archive.json", archive_data)
        _put_verified(client, bucket=bucket, key=f"{key_root}/archive.json", data=archive_data, content_type="application/json")
        return value
    except Exception as exc:
        value["archive_state"] = "failed"
        value["archive_error"] = _safe_error(exc)
        value["generation_state"] = "succeeded"
        value["status"] = legacy_status
        _write_receipt(run_dir, value)
        raise
