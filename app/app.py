#!/usr/bin/env python3
"""Loopback-only, model-aware control plane for local image generation."""
from __future__ import annotations

import hashlib
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import boto3
from botocore.config import Config
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from imagelab import create_app
from imagelab import storage
from imagelab.db import connect_database, initialize_database
from imagelab.models.registry import registry
from imagelab.repositories.jobs import JobRepository
from imagelab.repositories.preferences import PreferenceConflict, PreferenceRepository
from imagelab.services.organization import MetadataConflict, OrganizationService
from imagelab.repositories.runs import RunRepository
from imagelab.services.archive import archive_evidence
from imagelab.services.exports import ExportError, build_family_zip, convert_image, resize_to_png
from imagelab.services.generation import enqueue_generation, queue_depth
from imagelab.services.library import LibraryQuery, LibraryService
from imagelab.services.media import ThumbnailService
from imagelab.services.recovery import BackendDisconnected, BackendSnapshot, SubmissionUncertain
from imagelab.validation import GenerationRequest, normalize_generation_request

RUNS = ROOT / "runs"
REFERENCES = ROOT / "references"
MODEL_NOTES = ROOT / "model-notes.json"
LOGS = ROOT / "logs"
COMFY_ROOT = Path.home() / "hermes-data/Marvin/Projects/Local Image Generation/Qwen-Image-2.1/ComfyUI"
COMFY_URL = os.environ.get("MAC_IMAGE_LAB_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
HOST = "127.0.0.1"
PORT = int(os.environ.get("MAC_IMAGE_LAB_PORT", "7864"))
R2_BUCKET = "hermes-data"
R2_PREFIX = "Marvin/Mac Image Lab/runs"
LIBRARY_ROOT = Path.home() / "Documents/Mac Image Lab"
GENERATED_ROOT = LIBRARY_ROOT / "Generated Images"
THUMBNAIL_ROOT = ROOT / "cache" / "thumbnails"
DATA = ROOT / "data"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}

MODELS: dict[str, dict[str, Any]] = registry.legacy_view()
PROFILES = {key: dict(value) for key, value in registry.get("qwen-image-2.1-local").profiles.items()}
ASPECT_DIMENSIONS = {
    "fast": {"square": (768, 768), "portrait": (672, 896), "landscape": (896, 672)},
    "standard": {"square": (1024, 1024), "portrait": (896, 1152), "landscape": (1152, 896)},
    "maximum": {"square": (2048, 2048), "portrait": (1696, 2528), "landscape": (2528, 1696)},
}
BUILTIN_RECIPES = [
    {"id": "studio-product", "name": "Studio product portrait", "mode": "text", "prompt": "A refined studio product portrait of [subject], centered against a warm neutral background. Describe the exact materials, surface texture, directional soft light, restrained palette, and clean composition.", "profile": "fast", "aspect": "square"},
    {"id": "editorial-landscape", "name": "Editorial landscape", "mode": "text", "prompt": "A wide editorial photograph of [subject and setting], with a clear foreground, middle distance, and background. Natural directional light, realistic materials, balanced negative space, and a restrained color palette.", "profile": "fast", "aspect": "landscape"},
    {"id": "scene-change", "name": "Scene or background change", "mode": "transform", "prompt": "Change only the background and setting. Preserve the main people or objects, their relative placement, and the overall composition where possible.", "profile": "fast", "aspect": "square"},
    {"id": "storybook", "name": "Storybook illustration", "mode": "transform", "prompt": "Reinterpret this as a hand-painted storybook animation illustration. Preserve the people or objects and their relationships where possible.", "profile": "fast", "aspect": "square"},
]

app = create_app(
    __name__,
    template_folder=ROOT / "app" / "templates",
    static_folder=ROOT / "app" / "static",
)
archive_queue: queue.Queue[str] = queue.Queue()
archive_worker_started = False
archive_worker_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


app.jinja_env.globals["new_idempotency_key"] = lambda: str(uuid.uuid4())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_id(run_id: str) -> str:
    if not run_id or any(c not in "0123456789abcdef-" for c in run_id) or len(run_id) != 36:
        abort(404)
    return run_id


def run_dir(run_id: str) -> Path:
    return RUNS / safe_id(run_id)


def receipt_path(run_id: str) -> Path:
    return run_dir(run_id) / "receipt.json"


def database_path() -> Path:
    return RUNS.parent / "state" / "library.sqlite3"


def model_for(model_id: str) -> dict[str, Any]:
    model = MODELS.get(model_id)
    if not model or model["status"] != "available":
        raise ValueError("Selected image model is not available locally")
    return model


def ensure_library() -> None:
    for p in [GENERATED_ROOT / "Inbox", GENERATED_ROOT / "Favorites", GENERATED_ROOT / "Collections", GENERATED_ROOT / "Exports/Upscaled", GENERATED_ROOT / "Exports/Print Size", LIBRARY_ROOT / "References"]:
        p.mkdir(parents=True, exist_ok=True)


def safe_library_rel(value: str | None) -> str:
    raw = (value or "Inbox").strip().replace("\\", "/").strip("/")
    if not raw or raw == ".":
        return "Inbox"
    if len(raw) > 180 or raw.startswith(".") or any(part in {"", ".", ".."} for part in raw.split("/")):
        raise ValueError("Folder must be a safe subfolder below Generated Images")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._()&'/-]*", raw):
        raise ValueError("Folder contains unsupported characters")
    return raw


def library_dir(relative: str | None) -> Path:
    ensure_library()
    rel = safe_library_rel(relative)
    dest = (GENERATED_ROOT / rel).resolve()
    if GENERATED_ROOT.resolve() not in {dest, *dest.parents}:
        raise ValueError("Folder escapes the image library")
    return dest


def list_library_folders() -> list[str]:
    """List known collections without touching the TCC-protected Documents tree.

    A supervised LaunchAgent cannot answer an interactive Documents-folder
    permission prompt. Filesystem access therefore happens only for an explicit
    filing action; ordinary Library/Create page loads use durable receipt state.
    """
    values = {"Inbox", "Favorites", "Collections", "Exports/Upscaled", "Exports/Print Size"}
    for receipt in list_runs(limit=1000):
        candidate = str(receipt.get("library_folder") or "").strip()
        if not candidate:
            continue
        try:
            values.add(safe_library_rel(candidate))
        except ValueError:
            continue
    return sorted(values, key=lambda x: (x.lower() != "inbox", x.lower()))


def load_model_notes() -> dict[str, str]:
    if not MODEL_NOTES.exists():
        return {}
    try:
        value = json.loads(MODEL_NOTES.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_model_note(model_id: str, note: str) -> None:
    if model_id not in MODELS:
        raise ValueError("Unknown model")
    if len(note) > 5000:
        raise ValueError("Personal note must be 5,000 characters or fewer")
    notes = load_model_notes()
    notes[model_id] = note.strip()
    storage.atomic_write_beneath(MODEL_NOTES.parent, MODEL_NOTES.name, (json.dumps(notes, indent=2, sort_keys=True) + "\n").encode())


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:48] or "image"


def normalize_receipt(r: dict[str, Any], run_id: str) -> dict[str, Any]:
    r["run_id"] = run_id
    r.setdefault("model_id", "qwen-image-2.1-local")
    r.setdefault("family_id", run_id)
    r.setdefault("parent_run_id", None)
    r.setdefault("library_folder", None)
    r.setdefault("library_copies", [])
    legacy_status = r.get("status")
    r.setdefault("generation_state", "succeeded" if legacy_status in {"local_only", "archived", "archive_failed"} else legacy_status or "unknown")
    r.setdefault("archive_state", "verified" if legacy_status == "archived" else "failed" if legacy_status == "archive_failed" else "local_only")
    r.setdefault("title", slug(r.get("prompt", "image")).replace("-", " ").title())
    model = MODELS.get(r["model_id"], {"label": r["model_id"], "source": "Unknown", "runtime": "Unknown"})
    r["model_label"] = model["label"]
    r["model_source"] = model["source"]
    return r


def read_receipt(run_id: str) -> dict[str, Any]:
    db = database_path()
    if db.exists():
        with connect_database(db) as connection:
            value = RunRepository(connection).get_receipt(run_id)
        if value is not None:
            return normalize_receipt(value, run_id)
    p = receipt_path(run_id)
    if not p.exists():
        abort(404)
    return normalize_receipt(json.loads(p.read_text()), run_id)


def write_receipt(run_id: str, value: dict[str, Any]) -> None:
    for key in ["model_label", "model_source"]:
        value.pop(key, None)
    path = receipt_path(run_id)
    storage.atomic_write_beneath(path.parent, path.name, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    connection = initialize_database(database_path())
    try:
        with connection:
            RunRepository(connection).upsert_receipt(value, path, sha256(path))
    finally:
        connection.close()


def list_runs(limit: int | None = None) -> list[dict[str, Any]]:
    db = database_path()
    if db.exists():
        with connect_database(db) as connection:
            values = RunRepository(connection).list_receipts(limit=limit)
        return [normalize_receipt(value, value["run_id"]) for value in values]
    values = []
    for p in RUNS.glob("*/receipt.json"):
        try:
            values.append(normalize_receipt(json.loads(p.read_text()), p.parent.name))
        except (OSError, json.JSONDecodeError):
            continue
    values.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return values[:limit] if limit else values


def family_groups() -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in list_runs():
        groups[run["family_id"]].append(run)
    result = []
    for family_id, runs in groups.items():
        runs.sort(key=lambda r: r.get("created_at", ""))
        root = next((r for r in runs if r["run_id"] == family_id), runs[0])
        result.append({"family_id": family_id, "title": root.get("title", "Untitled family"), "runs": runs, "latest": runs[-1]})
    return sorted(result, key=lambda f: f["latest"].get("created_at", ""), reverse=True)


def build_workflow(prompt: str, width: int, height: int, steps: int, seed: int, resolution: int, prefix: str, model_id: str) -> dict[str, Any]:
    request_value = GenerationRequest(prompt, model_id, "custom", width, height, steps, seed, resolution, "original")
    return registry.adapter(model_id).build_workflow(request_value, prefix=prefix)


def build_reference_edit_workflow(prompt: str, steps: int, seed: int, resolution: int, prefix: str, input_name: str) -> dict[str, Any]:
    model_id = "qwen-image-2.1-local"
    request_value = GenerationRequest(prompt, model_id, "custom", resolution, resolution, steps, seed, resolution, "reference_transform")
    return registry.adapter(model_id).build_workflow(request_value, prefix=prefix, input_name=input_name)


def create_reference_transform(form: dict[str, str], upload: Any, *, parent: dict[str, Any] | None = None) -> str:
    action = str(form.get("action") or "reference_transform")
    normalized = normalize_generation_request(
        {**form, "action": action},
        profiles=PROFILES,
        available_models={key for key, value in MODELS.items() if value["status"] == "available"},
        parent=parent,
    )
    source_run_id: str | None = None
    lineage_parent = parent
    source_bytes: bytes
    source_mime: str
    if parent and (parent.get("reference_edit") or {}).get("enabled"):
        reference = parent["reference_edit"]
        source_name = reference.get("source_file")
        if not isinstance(source_name, str) or Path(source_name).name != source_name:
            raise ValueError("Parent transform source is unavailable")
        source_path = run_dir(parent["run_id"]) / source_name
        if not source_path.is_file():
            raise ValueError("Parent transform source is unavailable")
        source_bytes = source_path.read_bytes()
        source_mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(source_path.suffix.lower(), "image/png")
        source_run_id = reference.get("source_run_id")
    elif upload:
        source_bytes = upload.read()
        source_mime = upload.mimetype or ""
    elif form.get("source_run_id"):
        source_run_id = safe_id(str(form["source_run_id"]))
        source = read_receipt(source_run_id)
        output = source.get("output") or {}
        source_name = output.get("file")
        if source.get("generation_state") != "succeeded" or not isinstance(source_name, str) or Path(source_name).name != source_name:
            raise ValueError("Selected source run has no completed image")
        source_path = run_dir(source_run_id) / source_name
        if not source_path.is_file():
            raise ValueError("Selected source image is unavailable")
        source_bytes = source_path.read_bytes()
        source_mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(source_path.suffix.lower(), "image/png")
        lineage_parent = source
    else:
        raise ValueError("Upload a PNG, JPEG, or WebP image")
    ingested = storage.ingest_reference(source_bytes, source_mime)
    folder = safe_library_rel(form.get("library_folder") or (lineage_parent.get("library_folder") if lineage_parent else "Inbox"))

    run_id = str(uuid.uuid4())
    RUNS.mkdir(parents=True, exist_ok=True)
    stage = RUNS / f".staging-{run_id}"
    final = RUNS / run_id
    ref_name = f"mac-image-lab-reference-{run_id}.png"
    backend_path: Path | None = None
    try:
        stage.mkdir(exist_ok=False)
        storage.atomic_write_beneath(stage, "reference-original" + ingested.original_suffix, ingested.original_bytes)
        storage.atomic_write_beneath(stage, "reference.png", ingested.derivative_bytes)
        workflow = build_reference_edit_workflow(
            normalized.prompt,
            normalized.steps,
            normalized.seed,
            normalized.resolution,
            f"mac-image-lab-{run_id}",
            ref_name,
        )
        storage.atomic_write_beneath(stage, "workflow.json", (json.dumps(workflow, indent=2) + "\n").encode())
        receipt = {
            "schema_version": 2,
            "run_id": run_id,
            "created_at": now(),
            "status": "queued",
            "generation_state": "queued",
            "title": form.get("title", "").strip() or "Reference transform",
            "model_id": normalized.model_id,
            "profile": normalized.profile,
            "prompt": normalized.prompt,
            "parameters": {
                "width": normalized.width,
                "height": normalized.height,
                "steps": normalized.steps,
                "seed": normalized.seed,
                "sampler": "euler",
                "scheduler": "simple",
                "cfg": 1.0,
                "resolution": normalized.resolution,
            },
            "workflow": workflow,
            "family_id": lineage_parent["family_id"] if lineage_parent else run_id,
            "parent_run_id": lineage_parent["run_id"] if lineage_parent else None,
            "relationship": normalized.action,
            "library_folder": folder,
            "library_copies": [],
            "archive_state": "local_only",
            "reference_edit": {
                "enabled": True,
                "experimental": True,
                "source_run_id": source_run_id,
                "preservation": "best effort; do not promise exact likeness",
                "source_file": "reference-original" + ingested.original_suffix,
                "inference_file": "reference.png",
                "source_width": ingested.width,
                "source_height": ingested.height,
                "source_format": ingested.source_format,
                "source_mode": ingested.mode,
                "exif_transposed": ingested.exif_transposed,
                "source_sha256": ingested.original_sha256,
                "original_sha256": ingested.original_sha256,
                "derivative_sha256": ingested.derivative_sha256,
            },
        }
        storage.atomic_write_beneath(stage, "receipt.json", (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
        backend_path = storage.atomic_write_beneath(COMFY_ROOT / "input", ref_name, ingested.derivative_bytes)
        os.replace(stage, final)
        write_receipt(run_id, receipt)
        return run_id
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        if backend_path is not None:
            backend_path.unlink(missing_ok=True)
        raise


def http_json(path: str, method: str = "GET", data: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    payload = json.dumps(data).encode() if data is not None else None
    req = Request(COMFY_URL + path, data=payload, method=method, headers={"Content-Type": "application/json"} if payload else {})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def file_run_output(run_id: str, relative: str | None) -> str:
    r = read_receipt(run_id)
    output = run_dir(run_id) / "output.png"
    if not output.exists():
        raise RuntimeError("No completed output is available to file")
    relative = safe_library_rel(relative)
    dest_dir = library_dir(relative)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{slug(r.get('title', 'image'))}-{run_id[:8]}.png"
    shutil.copy2(output, dest)
    rel = dest.relative_to(LIBRARY_ROOT).as_posix()
    copies = r.setdefault("library_copies", [])
    if rel not in copies:
        copies.append(rel)
    r["library_folder"] = relative
    write_receipt(run_id, r)
    members = []
    for member in (item for item in list_runs() if item.get("family_id") == r["family_id"]):
        output_meta = member.get("output") or {}
        members.append({
            "run_id": member["run_id"], "title": member["title"],
            "relationship": member.get("relationship", "original"),
            "parent_run_id": member.get("parent_run_id"),
            "output_sha256": output_meta.get("sha256"),
            "dimensions": [output_meta.get("width"), output_meta.get("height")],
        })
    manifest = {
        "schema_version": 1, "family_id": r["family_id"], "collection": relative,
        "updated_at": now(), "members": members,
    }
    storage.atomic_write_beneath(dest_dir, "family.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return rel


def execute_run(run_id: str) -> None:
    r = read_receipt(run_id)
    r.update(status="running", generation_state="running", started_at=now())
    write_receipt(run_id, r)
    start = time.monotonic()
    result = http_json("/prompt", "POST", {"prompt": r["workflow"], "client_id": f"mac-image-lab-{run_id}"})
    prompt_id = result["prompt_id"]
    (run_dir(run_id) / "comfy-submit.json").write_text(json.dumps(result, indent=2) + "\n")
    r["comfy_prompt_id"] = prompt_id
    write_receipt(run_id, r)
    history: dict[str, Any] | None = None
    for _ in range(420):
        history = http_json(f"/history/{prompt_id}")
        record = history.get(prompt_id)
        if record and record.get("status", {}).get("status_str") in {"success", "error"}:
            break
        time.sleep(3)
    else:
        raise TimeoutError("ComfyUI history polling timed out")
    record = history.get(prompt_id) if history else None
    (run_dir(run_id) / "comfy-history.json").write_text(json.dumps(record, indent=2) + "\n")
    if not record or record.get("status", {}).get("status_str") != "success":
        raise RuntimeError(json.dumps(record.get("status") if record else {"status": "missing"}))
    image_info = record["outputs"]["8"]["images"][0]
    source = COMFY_ROOT / "output" / image_info["filename"]
    dest = run_dir(run_id) / "output.png"
    if not source.exists():
        raise FileNotFoundError(f"ComfyUI output not found: {source}")
    shutil.copy2(source, dest)
    with Image.open(dest) as image:
        r["output"] = {"file": "output.png", "width": image.width, "height": image.height, "mode": image.mode, "sha256": sha256(dest), "bytes": dest.stat().st_size}
    r.update(status="local_only", generation_state="succeeded", completed_at=now(), elapsed_seconds=round(time.monotonic() - start, 3))
    write_receipt(run_id, r)
    file_run_output(run_id, r.get("library_folder") or "Inbox")


def _json_contains(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return value == needle
    if isinstance(value, dict):
        return any(_json_contains(item, needle) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_json_contains(item, needle) for item in value)
    return False


def _first_output_image(record: dict[str, Any]) -> dict[str, Any] | None:
    for output in (record.get("outputs") or {}).values():
        images = output.get("images") if isinstance(output, dict) else None
        if isinstance(images, list) and images and isinstance(images[0], dict):
            return images[0]
    return None


class ComfyRecoveryBackend:
    """ComfyUI gateway with correlation-aware restart recovery."""

    def find_by_correlation(self, token: str) -> str | None:
        matches: set[str] = set()
        try:
            history = http_json("/history")
            for prompt_id, record in history.items():
                if _json_contains(record, token):
                    matches.add(str(prompt_id))
            queue_state = http_json("/queue")
            for group in ("queue_running", "queue_pending"):
                for item in queue_state.get(group, []):
                    if _json_contains(item, token) and isinstance(item, list) and item:
                        matches.add(str(item[1] if len(item) > 1 else item[0]))
        except (URLError, TimeoutError, OSError) as exc:
            raise BackendDisconnected(str(exc)) from exc
        if len(matches) > 1:
            raise SubmissionUncertain("multiple backend jobs match the durable correlation token")
        return next(iter(matches), None)

    def submit(self, run_id: str, token: str) -> str:
        receipt = read_receipt(run_id)
        payload = {"prompt": receipt["workflow"], "client_id": token}
        try:
            result = http_json("/prompt", "POST", payload)
        except (URLError, TimeoutError, OSError) as exc:
            raise SubmissionUncertain(f"backend submission result is uncertain: {exc}") from exc
        prompt_id = result.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise SubmissionUncertain("backend accepted request without a prompt identifier")
        storage.atomic_write_beneath(
            run_dir(run_id), "comfy-submit.json", (json.dumps(result, indent=2) + "\n").encode()
        )
        receipt["comfy_prompt_id"] = prompt_id
        receipt.update(status="running", generation_state="running", started_at=receipt.get("started_at") or now())
        write_receipt(run_id, receipt)
        return prompt_id

    def inspect(self, backend_job_id: str) -> BackendSnapshot:
        try:
            history = http_json(f"/history/{backend_job_id}")
            record = history.get(backend_job_id)
            if record:
                state = record.get("status", {}).get("status_str")
                if state == "success":
                    return BackendSnapshot("succeeded", payload={"record": record})
                if state == "error":
                    return BackendSnapshot("failed", detail=json.dumps(record.get("status") or {}), payload={"record": record})
            queue_state = http_json("/queue")
        except (URLError, TimeoutError, OSError) as exc:
            raise BackendDisconnected(str(exc)) from exc
        for item in queue_state.get("queue_running", []):
            if _json_contains(item, backend_job_id):
                return BackendSnapshot("running")
        for item in queue_state.get("queue_pending", []):
            if _json_contains(item, backend_job_id):
                return BackendSnapshot("queued")
        return BackendSnapshot("unknown")

    def cancel(self, backend_job_id: str) -> bool:
        try:
            queue_state = http_json("/queue")
        except (URLError, TimeoutError, OSError):
            return False
        running = queue_state.get("queue_running", [])
        owned = [item for item in running if _json_contains(item, backend_job_id)]
        if len(running) != 1 or len(owned) != 1:
            return False
        try:
            http_json("/interrupt", "POST", {})
        except (URLError, TimeoutError, OSError):
            return False
        return True

    def collect(self, run_id: str, backend_job_id: str, snapshot: BackendSnapshot) -> bool:
        record = snapshot.payload.get("record")
        if not isinstance(record, dict):
            return False
        image_info = _first_output_image(record)
        if image_info is None or not isinstance(image_info.get("filename"), str):
            return False
        source = COMFY_ROOT / "output" / image_info["filename"]
        if not source.exists():
            return False
        destination = run_dir(run_id) / "output.png"
        shutil.copy2(source, destination)
        receipt = read_receipt(run_id)
        with Image.open(destination) as image:
            receipt["output"] = {
                "file": "output.png",
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "sha256": sha256(destination),
                "bytes": destination.stat().st_size,
            }
        storage.atomic_write_beneath(
            run_dir(run_id), "comfy-history.json", (json.dumps(record, indent=2) + "\n").encode()
        )
        receipt.update(status="local_only", generation_state="succeeded", completed_at=now())
        write_receipt(run_id, receipt)
        file_run_output(run_id, receipt.get("library_folder") or "Inbox")
        return True


def recovery_backend() -> ComfyRecoveryBackend:
    return ComfyRecoveryBackend()


def enqueue_run(run_id: str, idempotency_key: str) -> dict[str, Any]:
    job, _created = enqueue_generation(database_path(), run_id, idempotency_key)
    return job


def existing_submission(idempotency_key: str) -> dict[str, Any] | None:
    db = database_path()
    if not db.exists():
        return None
    with connect_database(db) as connection:
        return JobRepository(connection).get_by_idempotency_key(idempotency_key)


def request_idempotency_key() -> str:
    key = (request.form.get("idempotency_key") or "").strip()
    return key or str(uuid.uuid4())


def r2_client():
    for env in [Path.home() / ".hermes/.env", Path.home() / "hermes-data/.env"]:
        if env.exists():
            for line in env.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    endpoint = os.environ.get("R2_ENDPOINT") or os.environ.get("AWS_ENDPOINT_URL")
    key = os.environ.get("R2_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not all([endpoint, key, secret]):
        raise RuntimeError("R2 credentials unavailable in approved local environment configuration")
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=key, aws_secret_access_key=secret, region_name="auto", config=Config(signature_version="s3v4"))


def archive_run(run_id: str) -> dict[str, Any]:
    receipt = read_receipt(run_id)
    return archive_evidence(
        run_dir(run_id),
        receipt,
        client_factory=r2_client,
        bucket=R2_BUCKET,
        prefix=R2_PREFIX,
        now_fn=now,
    )


def archive_worker() -> None:
    while True:
        run_id = archive_queue.get()
        try:
            archive_run(run_id)
        except Exception:
            pass  # archive_evidence persists a sanitized failed state
        finally:
            archive_queue.task_done()


def start_archive_worker() -> None:
    global archive_worker_started
    with archive_worker_lock:
        if not archive_worker_started:
            threading.Thread(target=archive_worker, name="mac-image-lab-archive-worker", daemon=True).start()
            archive_worker_started = True


def validate_and_create(form: dict[str, str], parent: dict[str, Any] | None = None) -> str:
    normalized = normalize_generation_request(
        form,
        profiles=PROFILES,
        available_models={key for key, value in MODELS.items() if value["status"] == "available"},
        parent=parent,
    )
    folder = safe_library_rel(form.get("library_folder") or (parent.get("library_folder") if parent else "Inbox"))
    run_id = str(uuid.uuid4())
    d = RUNS / run_id
    d.mkdir(parents=True, exist_ok=False)
    workflow = build_workflow(
        normalized.prompt,
        normalized.width,
        normalized.height,
        normalized.steps,
        normalized.seed,
        normalized.resolution,
        f"mac-image-lab-{run_id}",
        normalized.model_id,
    )
    (d / "workflow.json").write_text(json.dumps(workflow, indent=2) + "\n")
    family_id = parent["family_id"] if parent else run_id
    receipt = {
        "schema_version": 2,
        "run_id": run_id,
        "created_at": now(),
        "status": "queued",
        "generation_state": "queued",
        "title": form.get("title", "").strip() or (parent.get("title") if parent else slug(normalized.prompt).replace("-", " ").title()),
        "model_id": normalized.model_id,
        "profile": normalized.profile,
        "prompt": normalized.prompt,
        "negative_prompt": form.get("negative_prompt", "").strip(),
        "parameters": {
            "width": normalized.width,
            "height": normalized.height,
            "steps": normalized.steps,
            "seed": normalized.seed,
            "sampler": "euler",
            "scheduler": "simple",
            "cfg": 1.0,
            "resolution": normalized.resolution,
        },
        "workflow": workflow,
        "models": {
            "unet": "qwen_image_2.1_int8_convrot.safetensors",
            "text_encoder": "qwen3vl_8b_int8_convrot.safetensors",
            "vae": "qwen_image_2.1_vae_bf16.safetensors",
        },
        "family_id": family_id,
        "parent_run_id": parent["run_id"] if parent else None,
        "relationship": normalized.action,
        "library_folder": folder,
        "library_copies": [],
        "archive_state": "local_only",
        "reference_edit": {"enabled": False, "reason": "This run was created without a reference image."},
    }
    write_receipt(run_id, receipt)
    return run_id


@app.get("/service-worker.js")
def service_worker():
    response = send_file(ROOT / "app" / "static" / "service-worker.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@app.get("/")
def index():
    try:
        query = LibraryQuery(
            page=int(request.args.get("page", "1")),
            per_page=int(request.args.get("per_page", "40")),
            search=request.args.get("search", "").strip(),
            model=request.args.get("model", "").strip(),
            collection=request.args.get("collection", "").strip(),
            family_id=request.args.get("family", "").strip(),
            favorite=request.args.get("favorite") == "1",
            family_view=request.args.get("view") == "family",
            layout=request.args.get("layout", "natural"),
            sort=request.args.get("sort", "newest"),
        )
        connection = initialize_database(database_path())
        try:
            page = LibraryService(connection).page(query)
        finally:
            connection.close()
    except (ValueError, TypeError) as exc:
        return render_template("error.html", message=str(exc)), 400
    runs = [normalize_receipt(value, value["run_id"]) for value in page.items]
    return render_template(
        "library.html",
        runs=runs,
        page=page,
        query=query,
        folders=list_library_folders(),
        models=MODELS,
    )


def create_page_context(mode: str) -> dict[str, Any]:
    connection = initialize_database(database_path())
    try:
        preferences = PreferenceRepository(connection)
        saved_recipes = preferences.list_recipes()
        notes = {model_id: preferences.get_model_note(model_id) for model_id in MODELS}
        legacy_notes = load_model_notes()
        for model_id, note in legacy_notes.items():
            if model_id in MODELS and note and notes[model_id]["revision"] == 0:
                notes[model_id] = preferences.save_model_note(model_id, str(note), expected_revision=0)
    finally:
        connection.close()
    recipes = [
        {**recipe, "description": "Built-in starting point", "builtin": True}
        for recipe in BUILTIN_RECIPES if recipe["mode"] == mode
    ]
    recipes.extend(
        {
            "id": recipe["id"], "name": recipe["name"], "description": recipe["description"],
            "builtin": False, **recipe["request"],
        }
        for recipe in saved_recipes if recipe["request"]["mode"] == mode
    )
    source_run_id = request.args.get("source_run_id", "")
    source_run = read_receipt(source_run_id) if source_run_id else None
    return {
        "mode": mode,
        "models": MODELS,
        "profiles": PROFILES,
        "aspects": ASPECT_DIMENSIONS,
        "folders": list_library_folders(),
        "model_notes": notes,
        "recipes": recipes,
        "active_jobs": queue_depth(database_path()),
        "source_run_id": source_run_id,
        "source_run": source_run,
    }


@app.get("/create")
def create_view():
    return render_template("create.html", **create_page_context("text"))


@app.get("/styles")
def styles():
    return render_template("styles.html")


@app.post("/recipes")
def recipe_save_view():
    try:
        mode = request.form.get("mode", "text")
        model_id = request.form.get("model_id", "")
        profile = request.form.get("profile", "")
        if model_id not in MODELS or MODELS[model_id]["status"] != "available":
            raise ValueError("Recipe model is not available")
        if profile not in PROFILES:
            raise ValueError("Recipe profile is invalid")
        name = request.form.get("name", "")
        recipe_id = f"{slug(name)}-{uuid.uuid4().hex[:8]}"
        connection = initialize_database(database_path())
        try:
            PreferenceRepository(connection).save_recipe(
                recipe_id=recipe_id,
                name=name,
                description=request.form.get("description", ""),
                request={
                    "schema_version": 1,
                    "mode": mode,
                    "model_id": model_id,
                    "prompt": request.form.get("prompt", ""),
                    "profile": profile,
                    "aspect": request.form.get("aspect", "square"),
                    "collection": request.form.get("library_folder", ""),
                },
            )
        finally:
            connection.close()
        return redirect(url_for("transform_view" if mode == "transform" else "create_view"))
    except ValueError as exc:
        return render_template("error.html", message=str(exc)), 400


@app.post("/models/<model_id>/notes")
def model_notes_view(model_id: str):
    try:
        if model_id not in MODELS:
            raise ValueError("Unknown model")
        revision = int(request.form.get("revision", "0"))
        connection = initialize_database(database_path())
        try:
            PreferenceRepository(connection).save_model_note(
                model_id, request.form.get("note", ""), expected_revision=revision
            )
        finally:
            connection.close()
        return redirect(url_for("create_view"))
    except PreferenceConflict as exc:
        return render_template("error.html", message=str(exc)), 409
    except (ValueError, TypeError) as exc:
        return render_template("error.html", message=str(exc)), 400


@app.get("/transform")
def transform_view():
    return render_template("create.html", **create_page_context("transform"))


@app.post("/transform")
def transform_submit():
    try:
        key = request_idempotency_key()
        existing = existing_submission(key)
        if existing is not None:
            return redirect(url_for("run_view", run_id=existing["run_id"]))
        run_id = create_reference_transform(request.form, request.files.get("reference"))
        enqueue_run(run_id, key)
        return redirect(url_for("run_view", run_id=run_id))
    except (ValueError, OSError, Image.UnidentifiedImageError) as exc:
        return render_template("error.html", message=str(exc)), 400


@app.get("/gallery")
def gallery():
    return redirect(url_for("index"))


def comparison_options() -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for run in list_runs(limit=100):
        if run.get("generation_state") != "succeeded" or not run.get("output") or run.get("deleted_at"):
            continue
        output = run["output"]
        options.append({
            "token": run["run_id"], "kind": "result", "run_id": run["run_id"],
            "family_id": run["family_id"], "label": run["title"], "title": run["title"],
            "url": url_for("original_media", run_id=run["run_id"]),
            "width": int(output.get("width") or 0), "height": int(output.get("height") or 0),
            "run": run,
        })
        reference = run.get("reference_edit") or {}
        if reference.get("enabled") and reference.get("source_file"):
            source_width = int(reference.get("source_width") or 0)
            source_height = int(reference.get("source_height") or 0)
            source_name = reference.get("source_file")
            if (not source_width or not source_height) and isinstance(source_name, str) and Path(source_name).name == source_name:
                source_path = run_dir(run["run_id"]) / source_name
                try:
                    with Image.open(source_path) as source_image:
                        source_width, source_height = source_image.size
                except (OSError, Image.UnidentifiedImageError):
                    source_width, source_height = 0, 0
            options.append({
                "token": f"source:{run['run_id']}", "kind": "source", "run_id": run["run_id"],
                "family_id": run["family_id"], "label": f"Exact source · {run['title']}", "title": "Exact source asset",
                "url": url_for("reference_media", run_id=run["run_id"]),
                "width": source_width, "height": source_height,
                "run": run,
            })
    return options


@app.get("/compare")
def compare_view():
    options = comparison_options()
    by_token = {item["token"]: item for item in options}
    left_token = request.args.get("left", "")
    right_token = request.args.get("right", "")
    selection_error = None
    if left_token and left_token not in by_token:
        selection_error = "The left comparison image is unavailable, missing, or in trash."
    if right_token and right_token not in by_token:
        selection_error = "The right comparison image is unavailable, missing, or in trash."
    left = by_token.get(left_token) if left_token else (options[0] if options else None)
    if right_token:
        right = by_token.get(right_token)
    elif left:
        right = next((item for item in options if item["token"] != left["token"] and item["family_id"] == left["family_id"]), None)
    else:
        right = None
    compatible = False
    if left and right and left["width"] and left["height"] and right["width"] and right["height"]:
        compatible = abs((left["width"] / left["height"]) - (right["width"] / right["height"])) < 0.01
    preferred_run_id = None
    if left:
        connection = initialize_database(database_path())
        try:
            row = connection.execute("SELECT chosen_run_id FROM family_choices WHERE family_id = ?", (left["family_id"],)).fetchone()
            preferred_run_id = row[0] if row else None
        finally:
            connection.close()
    return render_template(
        "compare.html", options=options, left=left, right=right,
        compatible=compatible, selection_error=selection_error, preferred_run_id=preferred_run_id,
    )


@app.post("/families/<family_id>/preferred")
def preferred_version_view(family_id: str):
    safe_id(family_id)
    run_id = safe_id(request.form.get("run_id", ""))
    run = read_receipt(run_id)
    if run.get("family_id") != family_id or run.get("generation_state") != "succeeded" or run.get("deleted_at"):
        return render_template("error.html", message="Preferred version must be a visible completed result in this family"), 400
    connection = initialize_database(database_path())
    try:
        connection.execute(
            """INSERT INTO family_choices(family_id, chosen_run_id, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(family_id) DO UPDATE SET chosen_run_id=excluded.chosen_run_id, updated_at=excluded.updated_at""",
            (family_id, run_id, now()),
        )
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for("compare_view", left=request.form.get("left", ""), right=request.form.get("right", "")))


@app.get("/settings")
def settings_view():
    connection = initialize_database(database_path())
    try:
        organization = OrganizationService(connection)
        trashed = [RunRepository._receipt_from_row(row) for row in connection.execute("SELECT * FROM runs WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC").fetchall()]
        trash_metadata = {item["run_id"]: organization.metadata(item["run_id"]) for item in trashed}
    finally:
        connection.close()
    return render_template(
        "settings.html",
        models=MODELS,
        library_root=GENERATED_ROOT,
        comfy_url=COMFY_URL,
        trashed=trashed,
        trash_metadata=trash_metadata,
    )


@app.get("/families/<family_id>")
def family_view(family_id: str):
    safe_id(family_id)
    family = next((value for value in family_groups() if value["family_id"] == family_id), None)
    if not family:
        abort(404)
    source_asset = next((item for item in family["runs"] if (item.get("reference_edit") or {}).get("enabled")), None)
    connection = initialize_database(database_path())
    try:
        row = connection.execute("SELECT chosen_run_id FROM family_choices WHERE family_id = ?", (family_id,)).fetchone()
    finally:
        connection.close()
    return render_template(
        "family.html",
        family=family,
        folders=list_library_folders(),
        source_asset=source_asset,
        preferred_run_id=row[0] if row else None,
    )


@app.get("/healthz")
def healthz():
    comfy = False
    try:
        http_json("/object_info", timeout=5)
        comfy = True
    except (URLError, TimeoutError, OSError):
        pass
    return jsonify({"status": "ok", "host": HOST, "port": PORT, "loopback_only": True, "share_enabled": False, "comfyui_reachable": comfy, "queue_depth": queue_depth(database_path()), "available_models": [key for key, value in MODELS.items() if value["status"] == "available"]})


@app.post("/generate")
def generate():
    try:
        key = request_idempotency_key()
        existing = existing_submission(key)
        if existing is not None:
            return redirect(url_for("run_view", run_id=existing["run_id"]))
        run_id = validate_and_create(request.form)
        enqueue_run(run_id, key)
        return redirect(url_for("run_view", run_id=run_id))
    except (ValueError, OSError) as exc:
        return render_template("error.html", message=str(exc)), 400


@app.get("/queue")
def queue_view():
    return render_template("queue.html")


@app.get("/api/jobs")
def jobs_api():
    db = database_path()
    if not db.exists():
        return jsonify({"jobs": [], "poll_after_seconds": 2})
    connection = initialize_database(db)
    try:
        repository = JobRepository(connection)
        jobs = repository.list(limit=100)
        progress_by_job = {
            job["id"]: repository.latest_event_detail(job["id"], "heartbeat").get("progress")
            for job in jobs
        }
    finally:
        connection.close()
    public = []
    for job in jobs:
        public.append({
            "id": job["id"],
            "run_id": job["run_id"],
            "kind": job["kind"],
            "state": job["state"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
            "heartbeat_at": job["heartbeat_at"],
            "attempt_count": job["attempt_count"],
            "progress": progress_by_job[job["id"]],
            "error_type": job["error_type"],
            "status_detail": "Manual review required" if job["state"] == "needs_attention" else None,
        })
    return jsonify({"jobs": public, "poll_after_seconds": 2})


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    safe_id(job_id)
    connection = initialize_database(database_path())
    try:
        repository = JobRepository(connection)
        job = repository.get(job_id)
        if job is None:
            abort(404)
        if job["state"] == "queued" and repository.cancel_queued(job_id):
            return jsonify({"id": job_id, "state": "cancelled"})
        if job["state"] == "running" and job.get("backend_job_id"):
            if recovery_backend().cancel(job["backend_job_id"]):
                repository.confirm_running_cancelled(job_id)
                return jsonify({"id": job_id, "state": "cancelled"})
        return jsonify({"error": "This job cannot be safely cancelled because exact backend ownership is unproven."}), 409
    finally:
        connection.close()


@app.post("/api/jobs/<job_id>/retry")
def retry_job(job_id: str):
    safe_id(job_id)
    connection = initialize_database(database_path())
    try:
        repository = JobRepository(connection)
        original = repository.get(job_id)
        if original is None:
            abort(404)
        if original["state"] not in {"failed", "cancelled", "needs_attention"}:
            return jsonify({"error": "Only failed, cancelled, or recovery-blocked jobs can be retried."}), 409
        parent = read_receipt(original["run_id"])
        parameters = parent.get("parameters") or {}
        form = {
            "action": "repeat",
            "prompt": parent["prompt"],
            "model_id": parent["model_id"],
            "profile": parent.get("profile") or "fast",
            "width": str(parameters.get("width") or ""),
            "height": str(parameters.get("height") or ""),
            "steps": str(parameters.get("steps") or ""),
            "seed": str(parameters.get("seed") if parameters.get("seed") is not None else ""),
            "library_folder": parent.get("library_folder") or "Inbox",
        }
        new_run_id = validate_and_create(form, parent=parent)
        new_job = enqueue_run(new_run_id, str(uuid.uuid4()))
        repository.link_retry(job_id, new_job["id"])
        return jsonify({"job_id": new_job["id"], "run_id": new_run_id}), 201
    finally:
        connection.close()


@app.get("/runs/<run_id>")
def run_view(run_id: str):
    run = read_receipt(run_id)
    family_runs = next((f["runs"] for f in family_groups() if f["family_id"] == run["family_id"]), [])
    siblings = [item for item in family_runs if item["run_id"] != run_id]
    ordered_ids = [item["run_id"] for item in family_runs]
    current_index = ordered_ids.index(run_id) if run_id in ordered_ids else 0
    previous_run_id = ordered_ids[current_index - 1] if current_index > 0 else None
    next_run_id = ordered_ids[current_index + 1] if current_index + 1 < len(ordered_ids) else None
    evidence_files = {
        name: (run_dir(run_id) / name).is_file()
        for name in ("receipt.json", "workflow.json", "comfy-history.json", "archive.json")
    }
    state_labels = {
        "queued": "Waiting in generation queue",
        "submitting": "Submitting to local generator",
        "running": "Generation in progress",
        "succeeded": "Generation complete",
        "failed": "Generation failed",
        "cancelled": "Generation cancelled",
        "needs_attention": "Recovery review required",
    }
    connection = initialize_database(database_path())
    try:
        try:
            metadata = OrganizationService(connection).metadata(run_id)
        except KeyError:
            metadata = {"title": run["title"], "favorite": bool(run.get("favorite")), "deleted_at": run.get("deleted_at"), "revision": 1}
    finally:
        connection.close()
    return render_template(
        "run.html",
        run=run,
        run_id=run_id,
        profiles=PROFILES,
        models=MODELS,
        folders=list_library_folders(),
        siblings=siblings,
        previous_run_id=previous_run_id,
        next_run_id=next_run_id,
        evidence_files=evidence_files,
        metadata=metadata,
        state_label=state_labels.get(run.get("generation_state"), "Generation status unavailable"),
    )


@app.get("/runs/<run_id>/explore")
def explore_view(run_id: str):
    return render_template("explore.html", run=read_receipt(run_id), models=MODELS, profiles=PROFILES, folders=list_library_folders(), mode=request.args.get("mode", ""))


@app.post("/runs/<run_id>/explore")
def explore_submit(run_id: str):
    try:
        key = request_idempotency_key()
        existing = existing_submission(key)
        if existing is not None:
            return redirect(url_for("run_view", run_id=existing["run_id"]))
        parent = read_receipt(run_id)
        if (parent.get("reference_edit") or {}).get("enabled") and request.form.get("action") in {"repeat", "variation", "regenerate_larger"}:
            new_run = create_reference_transform(request.form, None, parent=parent)
        else:
            new_run = validate_and_create(request.form, parent=parent)
        enqueue_run(new_run, key)
        return redirect(url_for("run_view", run_id=new_run))
    except (ValueError, OSError) as exc:
        return render_template("error.html", message=str(exc)), 400


@app.post("/runs/<run_id>/metadata")
def update_run_metadata(run_id: str):
    safe_id(run_id)
    try:
        revision = int(request.form.get("revision", ""))
    except ValueError:
        return render_template("error.html", message="Invalid metadata revision"), 400
    title = request.form.get("title") if "title" in request.form else None
    favorite = request.form.get("favorite") == "1" if "favorite" in request.form else None
    trash_action = request.form.get("trash_action")
    trashed = True if trash_action == "trash" else False if trash_action == "restore" else None
    connection = initialize_database(database_path())
    try:
        OrganizationService(connection).update_metadata(
            run_id, revision=revision, title=title, favorite=favorite, trashed=trashed,
        )
    except MetadataConflict:
        return render_template("error.html", message="This image changed in another tab. Reload it before saving again."), 409
    except (KeyError, ValueError) as exc:
        return render_template("error.html", message=str(exc)), 400
    finally:
        connection.close()
    if trashed is True:
        return redirect(url_for("index"))
    return redirect(url_for("run_view", run_id=run_id))


@app.post("/runs/<run_id>/file")
def file_view(run_id: str):
    try:
        file_run_output(run_id, request.form.get("library_folder"))
        return redirect(url_for("run_view", run_id=run_id))
    except Exception as exc:
        return render_template("error.html", message=f"File operation failed: {exc}"), 400


@app.post("/library/folders")
def create_folder():
    try:
        connection = initialize_database(database_path())
        try:
            OrganizationService(connection, library_root=GENERATED_ROOT).create_collection(request.form.get("folder", ""))
        finally:
            connection.close()
        return redirect(url_for("index"))
    except ValueError as exc:
        return render_template("error.html", message=str(exc)), 400


@app.post("/runs/<run_id>/reveal")
def reveal_in_finder(run_id: str):
    run = read_receipt(run_id)
    subprocess.run(["open", str(library_dir(run.get("library_folder") or "Inbox"))], check=True)
    return redirect(url_for("run_view", run_id=run_id))


@app.post("/runs/<run_id>/archive")
def archive_view(run_id: str):
    try:
        value = read_receipt(run_id)
        generation_state = value.get("generation_state") or ("succeeded" if value.get("status") in {"local_only", "archived", "archive_failed"} else value.get("status"))
        if generation_state != "succeeded":
            raise RuntimeError("Only completed generation evidence can be archived")
        if value.get("archive_state") not in {"queued", "archiving"}:
            value["archive_state"] = "queued"
            write_receipt(run_id, value)
            start_archive_worker()
            archive_queue.put(run_id)
    except Exception as exc:
        return render_template("error.html", message=f"Archive failed: {exc}"), 502
    return redirect(url_for("run_view", run_id=run_id))


@app.get("/media/<run_id>/thumbnail/<int:size>")
def thumbnail(run_id: str, size: int):
    run = read_receipt(run_id)
    output = run.get("output") or {}
    filename = output.get("file")
    digest = output.get("sha256")
    if not isinstance(filename, str) or Path(filename).name != filename or not isinstance(digest, str):
        abort(404)
    try:
        derived = ThumbnailService(THUMBNAIL_ROOT).get_or_create(run_dir(run_id) / filename, digest, size)
    except (FileNotFoundError, ValueError):
        abort(404)
    if request.headers.get("If-None-Match") == derived.etag:
        response = app.response_class(status=304)
    else:
        response = send_file(derived.path, mimetype="image/webp", conditional=False)
    response.headers["ETag"] = derived.etag
    response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    response.headers["X-Image-Width"] = str(derived.width)
    response.headers["X-Image-Height"] = str(derived.height)
    return response


@app.get("/media/<run_id>/reference")
def reference_media(run_id: str):
    run = read_receipt(run_id)
    reference = run.get("reference_edit") or {}
    filename = reference.get("source_file")
    digest = reference.get("original_sha256")
    if not reference.get("enabled") or not isinstance(filename, str) or Path(filename).name != filename or not isinstance(digest, str):
        abort(404)
    path = run_dir(run_id) / filename
    if not path.is_file():
        abort(404)
    response = send_file(path, conditional=True)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-SHA256"] = digest
    return response


@app.get("/media/<run_id>/original")
def original_media(run_id: str):
    run = read_receipt(run_id)
    output = run.get("output") or {}
    filename = output.get("file")
    digest = output.get("sha256")
    if not isinstance(filename, str) or Path(filename).name != filename or not isinstance(digest, str):
        abort(404)
    path = run_dir(run_id) / filename
    if not path.is_file():
        abort(404)
    response = send_file(path, conditional=True)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Content-Disposition"] = f'inline; filename="{Path(filename).name}"'
    response.headers["X-Content-SHA256"] = digest
    return response


@app.get("/runs/<run_id>/export.<format_name>")
def export_image(run_id: str, format_name: str):
    run = read_receipt(run_id)
    output = run.get("output") or {}
    source = run_dir(run_id) / str(output.get("file", ""))
    expected = output.get("sha256")
    if not source.is_file() or not isinstance(expected, str) or sha256(source) != expected:
        abort(404)
    try:
        data = convert_image(source, format_name, background=request.args.get("background"))
    except ExportError as exc:
        return render_template("error.html", message=str(exc)), 400
    formats = {"png": ("image/png", "png"), "jpeg": ("image/jpeg", "jpg"), "webp": ("image/webp", "webp")}
    if format_name not in formats:
        abort(404)
    mimetype, extension = formats[format_name]
    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=f"{slug(run['title'])}-{run_id[:8]}.{extension}")


@app.post("/runs/<run_id>/exports/resized")
def create_resized_export(run_id: str):
    parent = read_receipt(run_id)
    output = parent.get("output") or {}
    source = run_dir(run_id) / str(output.get("file", ""))
    if not source.is_file() or sha256(source) != output.get("sha256"):
        abort(404)
    try:
        width = int(request.form["width"]) if request.form.get("width", "").strip() else None
        height = int(request.form["height"]) if request.form.get("height", "").strip() else None
        child_id = str(uuid.uuid4())
        child_directory = run_dir(child_id)
        child_directory.mkdir(parents=True, exist_ok=False)
        destination = child_directory / "output.png"
        actual_width, actual_height = resize_to_png(source, destination, width=width, height=height)
        child = json.loads(json.dumps(parent))
        child.update({
            "run_id": child_id, "family_id": parent["family_id"], "parent_run_id": run_id,
            "relationship": "resized_export", "title": f"{parent['title']} · {actual_width}×{actual_height} resample",
            "created_at": now(), "completed_at": now(), "generation_state": "succeeded", "archive_state": "local_only",
            "status": "local_only", "elapsed_seconds": 0, "library_copies": [], "library_folder": "Exports/Resized",
            "resample_notice": "Pixel resample only; no new model detail was generated.",
        })
        child["parameters"] = {**(parent.get("parameters") or {}), "width": actual_width, "height": actual_height}
        with Image.open(destination) as resized_image:
            output_mode = resized_image.mode
        child["output"] = {"file": "output.png", "sha256": sha256(destination), "bytes": destination.stat().st_size, "width": actual_width, "height": actual_height, "mode": output_mode}
        for key in ("comfy_prompt_id", "workflow", "error", "deleted_at", "favorite"):
            child.pop(key, None)
        write_receipt(child_id, child)
        file_run_output(child_id, "Exports/Resized")
    except (ExportError, ValueError, KeyError) as exc:
        if "child_directory" in locals():
            shutil.rmtree(child_directory, ignore_errors=True)
        return render_template("error.html", message=str(exc)), 400
    return redirect(url_for("run_view", run_id=child_id))


@app.get("/families/<family_id>/export.zip")
def export_family_zip(family_id: str):
    safe_id(family_id)
    connection = initialize_database(database_path())
    try:
        receipts = RunRepository(connection).list_receipts(family_id=family_id, include_deleted=True)
    finally:
        connection.close()
    if not receipts:
        abort(404)
    try:
        payload = build_family_zip(RUNS, receipts)
    except ExportError as exc:
        return render_template("error.html", message=str(exc)), 400
    return send_file(io.BytesIO(payload), mimetype="application/zip", as_attachment=True, download_name=f"family-{family_id[:8]}-evidence.zip")


@app.get("/runs/<run_id>/download/<name>")
def download(run_id: str, name: str):
    if name not in {"output.png", "receipt.json", "workflow.json", "comfy-history.json", "archive.json"}:
        abort(404)
    p = run_dir(run_id) / name
    if not p.exists():
        abort(404)
    return send_file(p, as_attachment=True)


@app.post("/reference/upload")
def upload_reference():
    return jsonify({
        "error": "Legacy reference storage has been retired; use the validated Transform flow.",
        "transform_url": "/transform",
    }), 410


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

def _save_json_atomic(path: Path, data: Any) -> None:
    content = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.atomic_write_beneath(path.parent, path.name, content)

@app.get("/api/templates")
def list_templates():
    bundled = _load_json(DATA / "templates.json") or []
    user = _load_json(DATA / "user-templates.json") or []
    return jsonify({"bundled": bundled, "user": user})

@app.post("/api/user-templates")
def create_user_template():
    try:
        entry = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    name = str(entry.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Template name is required"}), 400
    tid = f"user-{slug(name)}-{uuid.uuid4().hex[:6]}"
    template = {
        "id": tid,
        "name": name,
        "description": str(entry.get("description") or ""),
        "icon": "🔖",
        "fields": entry.get("fields") or {},
        "exclusions": entry.get("exclusions") or {},
        "profile": entry.get("profile") or "standard",
        "aspect": entry.get("aspect") or "square",
    }
    user = _load_json(DATA / "user-templates.json") or []
    user.append(template)
    _save_json_atomic(DATA / "user-templates.json", user)
    return jsonify(template), 201

@app.delete("/api/user-templates/<template_id>")
def delete_user_template(template_id: str):
    user = _load_json(DATA / "user-templates.json") or []
    before = len(user)
    user = [t for t in user if t.get("id") != template_id]
    if len(user) == before:
        abort(404)
    _save_json_atomic(DATA / "user-templates.json", user)
    return jsonify({"deleted": template_id})

@app.get("/api/snippets")
def get_snippets():
    return jsonify(_load_json(DATA / "snippets.json") or {})

@app.post("/api/snippets")
def save_snippets():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    if not isinstance(data, dict):
        return jsonify({"error": "Snippets must be a JSON object"}), 400
    _save_json_atomic(DATA / "snippets.json", data)
    return jsonify(data)

@app.get("/api/examples")
def list_examples():
    return jsonify(_load_json(DATA / "examples.json") or [])

if __name__ == "__main__":
    if HOST != "127.0.0.1":
        raise RuntimeError("Mac Image Lab must bind loopback only")
    ensure_library()
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)
