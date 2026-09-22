#!/usr/bin/env python3
"""Read-only Mac Image Lab diagnostics and allowlisted local backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import urlopen

SAFE_SOURCE_ROOTS = ("app", "docs", "scripts", "tests", "deploy", "imagelab")
SAFE_TOP_LEVEL = (
    ".gitignore",
    "LICENSE",
    "NOTICE",
    "PROJECT.md",
    "README.md",
    "pytest.ini",
    "requirements.txt",
)
SAFE_RUN_METADATA = {
    "archive.json",
    "comfy-history.json",
    "comfy-submit.json",
    "family.json",
    "receipt.json",
    "workflow.json",
}
SECRET_WORDS = ("secret", "token", "password", "credential", "api_key", "api-key", "access_key", "cookie")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_probe(root: Path) -> dict[str, Any]:
    def run(*args: str, strip: bool = True) -> str:
        output = subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout
        return output.strip() if strip else output.rstrip("\n")

    status = run("status", "--porcelain", strip=False)
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty_paths": [line[3:] for line in status.splitlines() if len(line) > 3],
    }


def _json_probe(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=3) as response:
        payload = json.loads(response.read())
        return {"status": "ok", "http_status": int(response.status), "payload_type": type(payload).__name__}


def _storage_probe(root: Path) -> dict[str, int]:
    usage = shutil.disk_usage(root)
    return {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free}


def _memory_probe() -> dict[str, int | str]:
    result = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout.strip().isdigit():
        return {"physical_bytes": int(result.stdout.strip())}
    return {"status": "unavailable"}


def _queue_probe(url: str) -> dict[str, Any]:
    with urlopen(url.rstrip("/") + "/queue", timeout=3) as response:
        payload = json.loads(response.read())
    return {
        "running_count": len(payload.get("queue_running", [])),
        "pending_count": len(payload.get("queue_pending", [])),
        "running_prompt_ids": _prompt_ids(payload.get("queue_running", [])),
        "pending_prompt_ids": _prompt_ids(payload.get("queue_pending", [])),
    }


def _prompt_ids(entries: list[Any]) -> list[str]:
    ids: list[str] = []
    for entry in entries:
        if isinstance(entry, (list, tuple)) and len(entry) > 1:
            candidate = entry[1]
            if isinstance(candidate, str) and len(candidate) <= 128:
                ids.append(candidate)
        elif isinstance(entry, dict):
            candidate = entry.get("prompt_id")
            if isinstance(candidate, str) and len(candidate) <= 128:
                ids.append(candidate)
    return ids


def _listener_probe(ports: tuple[int, ...]) -> list[dict[str, Any]]:
    roles = {7864: "app", 8188: "comfyui"}
    listeners: list[dict[str, Any]] = []
    for port in ports:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"],
            capture_output=True,
            text=True,
            check=False,
        )
        pid: int | None = None
        for line in result.stdout.splitlines():
            if line.startswith("p") and line[1:].isdigit():
                pid = int(line[1:])
        if pid is not None:
            listeners.append({"role": roles.get(port, "service"), "pid": pid, "port": port})
    return listeners


def _safe_listener_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe = []
    for row in rows:
        safe.append({key: row[key] for key in ("role", "pid", "port") if key in row})
    return safe


def _safe_queue(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "unavailable"}
    if "running_count" in value or "pending_count" in value:
        return {
            "running_count": int(value.get("running_count", 0)),
            "pending_count": int(value.get("pending_count", 0)),
            "running_prompt_ids": [str(v) for v in value.get("running_prompt_ids", [])],
            "pending_prompt_ids": [str(v) for v in value.get("pending_prompt_ids", [])],
        }
    running = value.get("queue_running", [])
    pending = value.get("queue_pending", [])
    return {
        "running_count": len(running) if isinstance(running, list) else 0,
        "pending_count": len(pending) if isinstance(pending, list) else 0,
        "running_prompt_ids": _prompt_ids(running if isinstance(running, list) else []),
        "pending_prompt_ids": _prompt_ids(pending if isinstance(pending, list) else []),
    }


def _dependencies(root: Path) -> list[dict[str, str]]:
    path = root / "requirements.txt"
    if not path.exists():
        return []
    rows = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            name, version = line.split("==", 1)
            rows.append({"name": name, "version": version})
        else:
            rows.append({"name": line, "version": "unparsed"})
    return rows


def collect_diagnostics(
    root: Path,
    *,
    git_probe: Callable[[Path], dict[str, Any]] = _git_probe,
    queue_probe: Callable[[str], dict[str, Any]] = _queue_probe,
    listener_probe: Callable[[tuple[int, ...]], list[dict[str, Any]]] = _listener_probe,
    endpoint_probe: Callable[[str], dict[str, Any]] = _json_probe,
    storage_probe: Callable[[Path], dict[str, Any]] = _storage_probe,
    memory_probe: Callable[[], dict[str, Any]] = _memory_probe,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Collect a secret-minimized snapshot without modifying project/runtime state."""
    root = root.resolve()
    receipts = sorted(root.glob("runs/*/receipt.json"))
    receipt_rows = [
        {
            "run_id": path.parent.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in receipts
    ]
    git = git_probe(root)
    # Environment is accepted for testability but is intentionally never serialized.
    del environ
    try:
        queue = _safe_queue(queue_probe("http://127.0.0.1:8188"))
    except Exception as exc:  # diagnostics must survive unavailable backend
        queue = {"status": "unavailable", "error_type": type(exc).__name__}
    def endpoint_status(url: str) -> dict[str, Any]:
        try:
            value = endpoint_probe(url)
            return {key: value[key] for key in ("status", "http_status", "payload_type") if key in value}
        except Exception as exc:
            return {"status": "unavailable", "error_type": type(exc).__name__}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "git": {
            "commit": git.get("commit", "unknown"),
            "branch": git.get("branch", "unknown"),
            "dirty_paths": [str(path) for path in git.get("dirty_paths", [])],
        },
        "locations": {
            "runs": str(root / "runs"),
            "library": str(Path.home() / "Documents/Mac Image Lab/Generated Images"),
        },
        "receipts": {"count": len(receipt_rows), "items": receipt_rows},
        "queue": queue,
        "health": {
            "liveness": endpoint_status("http://127.0.0.1:7864/healthz"),
            "backend_readiness": endpoint_status("http://127.0.0.1:8188/object_info"),
        },
        "resources": {"storage": storage_probe(root), "memory": memory_probe()},
        "availability": {
            "supervision": "per-user LaunchAgents",
            "login_required_after_reboot": True,
            "filevault_prelogin_available": False,
            "reboot_logout_tested": False,
        },
        "listeners": _safe_listener_rows(listener_probe((7864, 8188))),
        "dependencies": _dependencies(root),
    }


def _backup_candidates(root: Path) -> list[Path]:
    paths: set[Path] = set()
    for name in SAFE_TOP_LEVEL:
        path = root / name
        if path.is_file():
            paths.add(path)
    for name in SAFE_SOURCE_ROOTS:
        directory = root / name
        if directory.is_dir():
            for path in directory.rglob("*"):
                if path.is_file() and not any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
                    if path.suffix not in {".pyc", ".zip", ".png", ".jpg", ".jpeg", ".webp", ".safetensors", ".gguf"}:
                        paths.add(path)
    runs = root / "runs"
    if runs.is_dir():
        for path in runs.glob("*/*"):
            if path.is_file() and path.name in SAFE_RUN_METADATA:
                paths.add(path)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def create_backup(root: Path, backup_root: Path, *, commit: str, timestamp: str | None = None) -> Path:
    """Copy an explicit source/metadata allowlist into a timestamped local backup."""
    root = root.resolve()
    backup_root = backup_root.resolve()
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_root / f"gold-baseline-{stamp}"
    if destination.exists():
        raise FileExistsError(destination)
    files_root = destination / "files"
    entries: list[dict[str, Any]] = []
    for source in _backup_candidates(root):
        relative = source.relative_to(root)
        target = files_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        entries.append({
            "path": relative.as_posix(),
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
        })
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root),
        "source_commit": commit,
        "files": entries,
        "excluded": ["credentials", "environment files", "virtual environments", "model weights", "generated images", "validation evidence", "logs", "release archives"],
        "restore": [
            "Stop before restoring if new production runs exist; reconcile them first.",
            "Copy selected paths from files/ back to source_root after verifying SHA-256 values.",
            "Do not replace the entire project tree and do not restore runtime services blindly.",
        ],
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--backup", action="store_true", help="create an allowlisted local backup")
    args = parser.parse_args(argv)
    report = collect_diagnostics(args.root)
    if args.backup:
        destination = create_backup(
            args.root,
            args.root / "backups",
            commit=str(report["git"]["commit"]),
        )
        report["backup"] = str(destination)
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
