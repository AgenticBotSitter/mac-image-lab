"""Request-boundary protections for the trusted-device web application."""
from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlsplit

from flask import Flask, abort, current_app, request, session

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_PROXY_HEADERS = {
    "Forwarded",
    "X-Forwarded-For",
    "X-Forwarded-Host",
    "X-Forwarded-Proto",
    "X-Forwarded-Port",
    "X-Real-Ip",
    "Tailscale-User-Login",
    "Tailscale-User-Name",
}


def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _request_host() -> str:
    return (request.host or "").partition(":")[0].strip("[]").lower()


def _origin_allowed(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    canonical = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    return canonical in current_app.config["ALLOWED_ORIGINS"]


def _has_untrusted_proxy_headers() -> bool:
    if not any(header in request.headers for header in _PROXY_HEADERS):
        return False
    return (request.remote_addr or "") not in current_app.config["TRUSTED_PROXY_ADDRESSES"]


def init_security(app: Flask) -> None:
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def enforce_request_boundary():
        if _request_host() not in app.config["ALLOWED_HOSTS"]:
            abort(400, description="Untrusted request host")
        if _has_untrusted_proxy_headers():
            abort(400, description="Untrusted proxy headers")
        if request.method not in _MUTATING_METHODS or app.config.get("TESTING"):
            return None
        origin = request.headers.get("Origin", "")
        if not origin:
            abort(400, description="Mutation requires an Origin header")
        if not _origin_allowed(origin):
            abort(403, description="Untrusted request origin")
        if not app.config.get("CSRF_ENABLED", True):
            return None
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("_csrf_token", "")
        expected = session.get("_csrf_token", "")
        if not supplied or not expected or not hmac.compare_digest(str(supplied), str(expected)):
            abort(400, description="Invalid CSRF token")
        return None

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers.setdefault("Cache-Control", "no-store")
        return response
