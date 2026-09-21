#!/usr/bin/env python3
"""Loopback-only, model-aware control plane for local image generation."""
from __future__ import annotations

import hashlib
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
from imagelab import storage
from imagelab.db import connect_database, initialize_database
from imagelab.models.registry import registry
from imagelab.repositories.runs import RunRepository
from imagelab.services.archive import archive_evidence
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
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}

MODELS: dict[str, dict[str, Any]] = registry.legacy_view()
PROFILES = {key: dict(value) for key, value in registry.get("qwen-image-2.1-local").profiles.items()}

app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES, SECRET_KEY=os.environ.get("MAC_IMAGE_LAB_SESSION_KEY", "local-only-no-auth"))
work_queue: queue.Queue[str] = queue.Queue()
worker_started = False
worker_lock = threading.Lock()
archive_queue: queue.Queue[str] = queue.Queue()
archive_worker_started = False
archive_worker_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    ensure_library()
    values = ["Inbox", "Favorites", "Collections", "Exports/Upscaled", "Exports/Print Size"]
    for p in GENERATED_ROOT.rglob("*"):
        if p.is_dir() and not p.name.startswith("."):
            values.append(p.relative_to(GENERATED_ROOT).as_posix())
    return sorted(set(values), key=lambda x: (x.lower() != "inbox", x.lower()))


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


def create_reference_transform(form: dict[str, str], upload: Any) -> str:
    normalized = normalize_generation_request(
        {**form, "action": "reference_transform"},
        profiles=PROFILES,
        available_models={key for key, value in MODELS.items() if value["status"] == "available"},
    )
    if not upload:
        raise ValueError("Upload a PNG, JPEG, or WebP image")
    ingested = storage.ingest_reference(upload.read(), upload.mimetype or "")
    folder = safe_library_rel(form.get("library_folder") or "Inbox")

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
            "family_id": run_id,
            "parent_run_id": None,
            "relationship": "reference_transform",
            "library_folder": folder,
            "library_copies": [],
            "archive_state": "local_only",
            "reference_edit": {
                "enabled": True,
                "experimental": True,
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


def worker() -> None:
    while True:
        run_id = work_queue.get()
        try:
            execute_run(run_id)
        except Exception as exc:
            r = read_receipt(run_id)
            r.update(status="error", generation_state="failed", completed_at=now(), error=str(exc))
            write_receipt(run_id, r)
        finally:
            work_queue.task_done()


def start_worker() -> None:
    global worker_started
    with worker_lock:
        if not worker_started:
            threading.Thread(target=worker, name="mac-image-lab-worker", daemon=True).start()
            worker_started = True


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


@app.get("/")
def index():
    return render_template("index.html", models=MODELS, profiles=PROFILES, runs=list_runs(limit=40), folders=list_library_folders(), comfy_url=COMFY_URL, model_notes=load_model_notes())


@app.get("/styles")
def styles():
    return render_template("styles.html")


@app.post("/models/<model_id>/notes")
def model_notes_view(model_id: str):
    try:
        save_model_note(model_id, request.form.get("note", ""))
        return redirect(url_for("index"))
    except ValueError as exc:
        return render_template("error.html", message=str(exc)), 400


@app.get("/transform")
def transform_view():
    return render_template("transform.html", profiles=PROFILES, folders=list_library_folders())


@app.post("/transform")
def transform_submit():
    try:
        run_id = create_reference_transform(request.form, request.files.get("reference"))
        start_worker()
        work_queue.put(run_id)
        return redirect(url_for("run_view", run_id=run_id))
    except (ValueError, OSError, Image.UnidentifiedImageError) as exc:
        return render_template("error.html", message=str(exc)), 400


@app.get("/gallery")
def gallery():
    return render_template("gallery.html", runs=list_runs(), families=family_groups(), folders=list_library_folders(), models=MODELS)


@app.get("/families/<family_id>")
def family_view(family_id: str):
    safe_id(family_id)
    family = next((value for value in family_groups() if value["family_id"] == family_id), None)
    if not family:
        abort(404)
    return render_template("family.html", family=family, folders=list_library_folders())


@app.get("/healthz")
def healthz():
    comfy = False
    try:
        http_json("/object_info", timeout=5)
        comfy = True
    except (URLError, TimeoutError, OSError):
        pass
    return jsonify({"status": "ok", "host": HOST, "port": PORT, "loopback_only": True, "share_enabled": False, "comfyui_reachable": comfy, "queue_depth": work_queue.qsize(), "available_models": [key for key, value in MODELS.items() if value["status"] == "available"]})


@app.post("/generate")
def generate():
    try:
        run_id = validate_and_create(request.form)
        start_worker()
        work_queue.put(run_id)
        return redirect(url_for("run_view", run_id=run_id))
    except (ValueError, OSError) as exc:
        return render_template("error.html", message=str(exc)), 400


@app.get("/runs/<run_id>")
def run_view(run_id: str):
    run = read_receipt(run_id)
    siblings = [r for r in next((f["runs"] for f in family_groups() if f["family_id"] == run["family_id"]), []) if r["run_id"] != run_id]
    return render_template("run.html", run=run, run_id=run_id, profiles=PROFILES, models=MODELS, folders=list_library_folders(), siblings=siblings)


@app.get("/runs/<run_id>/explore")
def explore_view(run_id: str):
    return render_template("explore.html", run=read_receipt(run_id), models=MODELS, profiles=PROFILES, folders=list_library_folders(), mode=request.args.get("mode", ""))


@app.post("/runs/<run_id>/explore")
def explore_submit(run_id: str):
    try:
        parent = read_receipt(run_id)
        new_run = validate_and_create(request.form, parent=parent)
        start_worker()
        work_queue.put(new_run)
        return redirect(url_for("run_view", run_id=new_run))
    except (ValueError, OSError) as exc:
        return render_template("error.html", message=str(exc)), 400


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
        relative = safe_library_rel(request.form.get("folder"))
        library_dir(relative).mkdir(parents=True, exist_ok=True)
        return redirect(request.referrer or url_for("gallery"))
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


if __name__ == "__main__":
    if HOST != "127.0.0.1":
        raise RuntimeError("Mac Image Lab must bind loopback only")
    ensure_library()
    start_worker()
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
