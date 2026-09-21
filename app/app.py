#!/usr/bin/env python3
"""Loopback-only Mac Image Lab control plane for local ComfyUI/Qwen runs."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import queue
import shutil
import socket
import threading
import time
import uuid
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
RUNS = ROOT / "runs"
WORKFLOWS = ROOT / "workflows"
LOGS = ROOT / "logs"
COMFY_ROOT = Path.home() / "hermes-data/Marvin/Projects/Local Image Generation/Qwen-Image-2.1/ComfyUI"
COMFY_URL = os.environ.get("MAC_IMAGE_LAB_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
HOST = "127.0.0.1"
PORT = int(os.environ.get("MAC_IMAGE_LAB_PORT", "7864"))
R2_BUCKET = "hermes-data"
R2_PREFIX = "Marvin/Mac Image Lab/runs"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}

PROFILES = {
    "fast": {"label": "Fast preview", "width": 768, "height": 768, "steps": 8, "resolution": 768, "expected": "about 2 minutes after warm-up"},
    "standard": {"label": "Standard", "width": 1024, "height": 1024, "steps": 20, "resolution": 1024, "expected": "about 6 minutes after warm-up"},
    "maximum": {"label": "Maximum native 2K", "width": 1696, "height": 2528, "steps": 25, "resolution": 2048, "expected": "about 35 minutes on MPS; submit intentionally"},
}

app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES, SECRET_KEY=os.environ.get("MAC_IMAGE_LAB_SESSION_KEY", "local-only-no-auth"))
work_queue: queue.Queue[str] = queue.Queue()
worker_started = False
worker_lock = threading.Lock()


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


def read_receipt(run_id: str) -> dict[str, Any]:
    p = receipt_path(run_id)
    if not p.exists():
        abort(404)
    return json.loads(p.read_text())


def write_receipt(run_id: str, value: dict[str, Any]) -> None:
    p = receipt_path(run_id)
    p.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def list_runs() -> list[dict[str, Any]]:
    values = []
    for p in RUNS.glob("*/receipt.json"):
        try:
            r = json.loads(p.read_text())
            r["run_id"] = p.parent.name
            values.append(r)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(values, key=lambda x: x.get("created_at", ""), reverse=True)


def build_workflow(prompt: str, width: int, height: int, steps: int, seed: int, resolution: int, prefix: str) -> dict[str, Any]:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["2", 0], "prompt": prompt, "negative_prompt": "", "resolution": resolution}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["4", 1], "latent_image": ["5", 0], "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    }


def http_json(path: str, method: str = "GET", data: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    payload = json.dumps(data).encode() if data is not None else None
    req = Request(COMFY_URL + path, data=payload, method=method, headers={"Content-Type": "application/json"} if payload else {})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def worker() -> None:
    while True:
        run_id = work_queue.get()
        try:
            execute_run(run_id)
        except Exception as e:  # receipt must reflect actual failure
            r = read_receipt(run_id)
            r.update(status="error", completed_at=now(), error=str(e))
            write_receipt(run_id, r)
        finally:
            work_queue.task_done()


def start_worker() -> None:
    global worker_started
    with worker_lock:
        if not worker_started:
            threading.Thread(target=worker, name="mac-image-lab-worker", daemon=True).start()
            worker_started = True


def execute_run(run_id: str) -> None:
    r = read_receipt(run_id)
    r.update(status="running", started_at=now())
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
    with Image.open(dest) as im:
        r["output"] = {"file": "output.png", "width": im.width, "height": im.height, "mode": im.mode, "sha256": sha256(dest), "bytes": dest.stat().st_size}
    r.update(status="local_only", completed_at=now(), elapsed_seconds=round(time.monotonic() - start, 3))
    write_receipt(run_id, r)


def r2_client():
    for env in [Path.home() / ".hermes/.env", Path.home() / "hermes-data/.env"]:
        if env.exists():
            for line in env.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    endpoint = os.environ.get("R2_ENDPOINT") or os.environ.get("AWS_ENDPOINT_URL")
    key = os.environ.get("R2_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not all([endpoint, key, secret]):
        raise RuntimeError("R2 credentials unavailable in approved local environment configuration")
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=key, aws_secret_access_key=secret, region_name="auto", config=Config(signature_version="s3v4"))


def archive_run(run_id: str) -> dict[str, Any]:
    r = read_receipt(run_id)
    if r.get("status") not in {"local_only", "archive_failed", "archived"}:
        raise RuntimeError("Only completed runs can be archived")
    r["status"] = "archiving"; write_receipt(run_id, r)
    required = ["output.png", "workflow.json", "receipt.json", "comfy-history.json", "comfy-submit.json"]
    client = r2_client(); result = {"run_id": run_id, "started_at": now(), "objects": []}
    try:
        for name in required:
            p = run_dir(run_id) / name
            if not p.exists(): raise FileNotFoundError(name)
            digest = sha256(p); key = f"{R2_PREFIX}/{run_id}/{name}"; body = p.read_bytes()
            client.put_object(Bucket=R2_BUCKET, Key=key, Body=body, ContentType=mimetypes.guess_type(str(p))[0] or "application/octet-stream", Metadata={"sha256": digest})
            head = client.head_object(Bucket=R2_BUCKET, Key=key)
            if head["ContentLength"] != len(body) or head.get("Metadata", {}).get("sha256") != digest: raise RuntimeError(f"head_object mismatch: {key}")
            result["objects"].append({"key": key, "bytes": len(body), "sha256": digest, "verified_at": now()})
        result["status"] = "ok"; result["completed_at"] = now()
        (run_dir(run_id) / "archive.json").write_text(json.dumps(result, indent=2) + "\n")
        # archive receipt is rewritten after status update then verified independently
        r["status"] = "archived"; r["archive"] = result; write_receipt(run_id, r)
        for name in ["archive.json", "receipt.json"]:
            p = run_dir(run_id) / name; digest = sha256(p); key = f"{R2_PREFIX}/{run_id}/{name}"; body=p.read_bytes()
            client.put_object(Bucket=R2_BUCKET, Key=key, Body=body, ContentType="application/json", Metadata={"sha256": digest})
            h=client.head_object(Bucket=R2_BUCKET, Key=key)
            if h["ContentLength"] != len(body) or h.get("Metadata",{}).get("sha256") != digest: raise RuntimeError(f"head_object mismatch: {key}")
        return r
    except Exception as e:
        r["status"] = "archive_failed"; r["archive_error"] = str(e); write_receipt(run_id, r); raise


def validate_and_create(form: dict[str, str]) -> str:
    prompt = form.get("prompt", "").strip()
    if not prompt or len(prompt) > 4000: raise ValueError("Prompt must be 1–4000 characters")
    profile = form.get("profile", "fast")
    if profile not in PROFILES: raise ValueError("Unknown profile")
    p = PROFILES[profile]
    width = int(form.get("width") or p["width"]); height = int(form.get("height") or p["height"])
    steps = int(form.get("steps") or p["steps"]); seed = int(form.get("seed") or int.from_bytes(os.urandom(4), "big"))
    if width < 512 or height < 512 or width > 2752 or height > 2752 or width % 32 or height % 32: raise ValueError("Dimensions must be 512–2752 and multiples of 32")
    if not 1 <= steps <= 80: raise ValueError("Steps must be 1–80")
    if not 0 <= seed <= 2**63 - 1: raise ValueError("Seed out of range")
    run_id = str(uuid.uuid4()); d = RUNS / run_id; d.mkdir(parents=True, exist_ok=False)
    workflow = build_workflow(prompt, width, height, steps, seed, p["resolution"], f"mac-image-lab-{run_id}")
    (d / "workflow.json").write_text(json.dumps(workflow, indent=2) + "\n")
    receipt = {"schema_version": 1, "run_id": run_id, "created_at": now(), "status": "queued", "profile": profile, "prompt": prompt, "parameters": {"width": width, "height": height, "steps": steps, "seed": seed, "sampler": "euler", "scheduler": "simple", "cfg": 1.0, "resolution": p["resolution"]}, "workflow": workflow, "models": {"unet": "qwen_image_2.1_int8_convrot.safetensors", "text_encoder": "qwen3vl_8b_int8_convrot.safetensors", "vae": "qwen_image_2.1_vae_bf16.safetensors"}, "archive_state": "local_only", "reference_edit": {"enabled": False, "reason": "No tested Qwen reference/edit graph is installed."}}
    write_receipt(run_id, receipt); return run_id

@app.get("/")
def index():
    return render_template("index.html", profiles=PROFILES, runs=list_runs(), comfy_url=COMFY_URL)

@app.get("/healthz")
def healthz():
    comfy = False
    try: http_json("/object_info", timeout=5); comfy = True
    except (URLError, TimeoutError, OSError): pass
    return jsonify({"status": "ok", "host": HOST, "port": PORT, "loopback_only": True, "share_enabled": False, "comfyui_reachable": comfy, "queue_depth": work_queue.qsize()})

@app.post("/generate")
def generate():
    try:
        run_id=validate_and_create(request.form); start_worker(); work_queue.put(run_id)
        return redirect(url_for("run_view", run_id=run_id))
    except (ValueError, OSError) as e:
        return render_template("error.html", message=str(e)), 400

@app.get("/runs/<run_id>")
def run_view(run_id: str):
    return render_template("run.html", run=read_receipt(run_id), run_id=run_id, profiles=PROFILES)

@app.post("/runs/<run_id>/archive")
def archive_view(run_id: str):
    try: archive_run(run_id)
    except Exception as e: return render_template("error.html", message=f"Archive failed: {e}"), 502
    return redirect(url_for("run_view", run_id=run_id))

@app.get("/runs/<run_id>/download/<name>")
def download(run_id: str, name: str):
    if name not in {"output.png", "receipt.json", "workflow.json", "comfy-history.json", "archive.json"}: abort(404)
    p=run_dir(run_id)/name
    if not p.exists(): abort(404)
    return send_file(p, as_attachment=True)

@app.post("/reference/upload")
def upload_reference():
    # Stored but intentionally not connected to inference until a tested official edit graph is installed.
    f=request.files.get("reference")
    if not f or f.mimetype not in IMAGE_TYPES: return jsonify({"error":"PNG, JPEG, or WebP only"}), 400
    data=f.read()
    if len(data)>MAX_UPLOAD_BYTES: return jsonify({"error":"Reference exceeds 20 MiB"}),400
    digest=hashlib.sha256(data).hexdigest(); suffix={"image/png":".png","image/jpeg":".jpg","image/webp":".webp"}[f.mimetype]
    target=ROOT/"references"; target.mkdir(exist_ok=True); p=target/(digest+suffix)
    if not p.exists(): p.write_bytes(data)
    return jsonify({"status":"stored_not_used_for_inference","sha256":digest,"file":p.name,"reason":"Reference editing remains disabled pending a tested Qwen edit workflow."})

if __name__ == "__main__":
    if HOST != "127.0.0.1": raise RuntimeError("Mac Image Lab must bind loopback only")
    start_worker()
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
