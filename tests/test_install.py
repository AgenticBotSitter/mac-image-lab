import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "verify_install.py"
SPEC = importlib.util.spec_from_file_location("verify_install", MODULE_PATH)
verify_install = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_install)


def test_diagnostics_redact_secrets_and_do_not_modify_source(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    receipt = root / "runs" / "abc" / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"status":"completed"}\n')
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    fake_secret = "super-secret-r2-value"
    report = verify_install.collect_diagnostics(
        root,
        git_probe=lambda _root: {"commit": "abc123", "branch": "gold-workspace", "dirty_paths": ["validation/"]},
        queue_probe=lambda _url: {"queue_running": [{"token": fake_secret}], "queue_pending": []},
        listener_probe=lambda _ports: [{"role": "app", "pid": 123, "port": 7864, "command": f"python --api-key {fake_secret}"}],
        environ={"R2_SECRET_ACCESS_KEY": fake_secret, "SAFE_FLAG": "okay"},
    )

    rendered = json.dumps(report)
    assert fake_secret not in rendered
    assert "R2_SECRET_ACCESS_KEY" not in rendered
    assert report["receipts"]["count"] == 1
    assert report["listeners"] == [{"role": "app", "pid": 123, "port": 7864}]
    after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert after == before


def test_backup_uses_allowlist_and_manifest_hashes(tmp_path):
    root = tmp_path / "lab"
    (root / "app").mkdir(parents=True)
    (root / "docs" / "plans").mkdir(parents=True)
    (root / "runs" / "run-1").mkdir(parents=True)
    (root / "validation").mkdir()
    (root / ".venv").mkdir()
    (root / "models").mkdir()
    (root / "app" / "app.py").write_text("APP = True\n")
    (root / "requirements.txt").write_text("flask==3.1.2\n")
    (root / "docs" / "plans" / "GOLD-BUILD-PLAN.md").write_text("plan\n")
    (root / "runs" / "run-1" / "receipt.json").write_text('{"run_id":"run-1"}\n')
    (root / "runs" / "run-1" / "workflow.json").write_text('{"workflow":true}\n')
    (root / "runs" / "run-1" / "output.png").write_bytes(b"private image")
    (root / ".env").write_text("PASSWORD=do-not-copy\n")
    (root / ".venv" / "secret.txt").write_text("venv\n")
    (root / "validation" / "REPORT.md").write_text("private validation\n")
    (root / "models" / "weights.safetensors").write_bytes(b"weights")
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    backup = verify_install.create_backup(root, root / "backups", commit="abc123", timestamp="20260921T120000Z")
    manifest = json.loads((backup / "manifest.json").read_text())
    paths = {entry["path"] for entry in manifest["files"]}

    assert "app/app.py" in paths
    assert "requirements.txt" in paths
    assert "docs/plans/GOLD-BUILD-PLAN.md" in paths
    assert "runs/run-1/receipt.json" in paths
    assert "runs/run-1/workflow.json" in paths
    assert "runs/run-1/output.png" not in paths
    assert ".env" not in paths
    assert ".venv/secret.txt" not in paths
    assert "validation/REPORT.md" not in paths
    assert "models/weights.safetensors" not in paths
    for entry in manifest["files"]:
        copied = backup / "files" / entry["path"]
        assert copied.exists()
        assert entry["sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()
    assert manifest["source_commit"] == "abc123"
    assert "restore" in manifest and manifest["restore"]

    after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file() and "backups/" not in p.relative_to(root).as_posix()}
    assert after == before


def test_git_probe_preserves_leading_dot_in_dirty_path(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "seed.txt").write_text("seed\n")
    (tmp_path / ".gitignore").write_text("first-cache/\n")
    subprocess.run(["git", "add", "seed.txt", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("second-cache/\n")

    report = verify_install._git_probe(tmp_path)

    assert report["dirty_paths"] == [".gitignore"]
