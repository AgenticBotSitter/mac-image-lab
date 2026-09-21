#!/usr/bin/env python3
"""Fail-closed Waitress entry point for Mac Image Lab."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from imagelab.config import secure_secret_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve Mac Image Lab with Waitress")
    parser.add_argument("--secret-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7864)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        parser.error("Mac Image Lab production web must bind to 127.0.0.1")
    try:
        secret = secure_secret_file(args.secret_file)
    except (OSError, RuntimeError) as exc:
        parser.error(f"secure session secret unavailable: {exc}")
    os.environ["MAC_IMAGE_LAB_ENV"] = "production"
    os.environ["MAC_IMAGE_LAB_PORT"] = str(args.port)
    os.environ["MAC_IMAGE_LAB_SESSION_KEY"] = secret
    from app.app import app
    if app.config.get("ENVIRONMENT") != "production" or not app.config.get("SESSION_COOKIE_SECURE"):
        parser.error("production application configuration is invalid")
    if args.check:
        print("production configuration valid; loopback bind enforced")
        return 0
    from waitress import serve
    serve(app, host=args.host, port=args.port, threads=8, clear_untrusted_proxy_headers=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
