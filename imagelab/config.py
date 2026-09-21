"""Validated application configuration for Mac Image Lab."""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, Mapping

DEFAULT_TAILNET_HOST = "alastairs-mac-mini.tail97e4dc.ts.net"


def default_config() -> dict[str, Any]:
    environment = os.environ.get("MAC_IMAGE_LAB_ENV", "development").strip().lower()
    port = int(os.environ.get("MAC_IMAGE_LAB_PORT", "7864"))
    tailnet_host = os.environ.get("MAC_IMAGE_LAB_TAILNET_HOST", DEFAULT_TAILNET_HOST).strip().lower()
    secret = os.environ.get("MAC_IMAGE_LAB_SESSION_KEY")
    if environment != "production" and not secret:
        secret = secrets.token_hex(32)
    return {
        "ENVIRONMENT": environment,
        "TESTING": environment == "test",
        "SECRET_KEY": secret,
        "MAX_CONTENT_LENGTH": 20 * 1024 * 1024,
        "ALLOWED_HOSTS": {"127.0.0.1", "localhost", tailnet_host},
        "ALLOWED_ORIGINS": {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
            f"https://{tailnet_host}",
        },
        "TRUSTED_PROXY_ADDRESSES": {"127.0.0.1", "::1"},
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": environment == "production",
        "CSRF_ENABLED": True,
    }


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("ENVIRONMENT") == "production" and not config.get("SECRET_KEY"):
        raise RuntimeError("Production startup requires an explicit session secret")
    if not config.get("ALLOWED_HOSTS"):
        raise RuntimeError("At least one trusted host is required")
    if not config.get("ALLOWED_ORIGINS"):
        raise RuntimeError("At least one trusted origin is required")


def secure_secret_file(path: Path) -> str:
    """Read a local secret only when its owner-only permissions are safe."""
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise RuntimeError("Session secret file must be owner-readable only")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise RuntimeError("Session secret is too short")
    return value
