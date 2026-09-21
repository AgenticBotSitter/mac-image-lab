import pytest

from imagelab import create_app


def configured_app(**overrides):
    config = {
        "TESTING": False,
        "ENVIRONMENT": "development",
        "SECRET_KEY": "test-secret-with-enough-entropy-123456",
        "ALLOWED_HOSTS": {"127.0.0.1", "localhost", "lab.tailnet.test"},
        "ALLOWED_ORIGINS": {
            "http://127.0.0.1:7864",
            "https://lab.tailnet.test",
        },
        "SESSION_COOKIE_SECURE": True,
    }
    config.update(overrides)
    app = create_app("security-test", config=config)

    @app.get("/probe")
    def probe_get():
        return "ok"

    @app.post("/probe")
    def probe_post():
        return "changed"

    return app


def csrf_headers(client, *, origin="https://lab.tailnet.test"):
    with client.session_transaction(base_url="https://lab.tailnet.test") as session:
        session["_csrf_token"] = "known-csrf-token"
    return {"Origin": origin, "X-CSRF-Token": "known-csrf-token"}


def test_production_startup_requires_explicit_session_secret():
    with pytest.raises(RuntimeError, match="session secret"):
        create_app(
            "production-security-test",
            config={
                "ENVIRONMENT": "production",
                "SECRET_KEY": None,
                "ALLOWED_HOSTS": {"lab.tailnet.test"},
                "ALLOWED_ORIGINS": {"https://lab.tailnet.test"},
            },
        )


def test_untrusted_host_is_rejected():
    client = configured_app().test_client()

    response = client.get("/probe", headers={"Host": "attacker.example"})

    assert response.status_code == 400


def test_mutation_requires_csrf_token_and_allowed_origin():
    client = configured_app().test_client()

    missing = client.post("/probe", base_url="https://lab.tailnet.test")
    wrong_origin = client.post(
        "/probe",
        base_url="https://lab.tailnet.test",
        headers=csrf_headers(client, origin="https://attacker.example"),
    )
    accepted = client.post(
        "/probe",
        base_url="https://lab.tailnet.test",
        headers=csrf_headers(client),
    )

    assert missing.status_code == 400
    assert wrong_origin.status_code == 403
    assert accepted.status_code == 200


def test_spoofed_proxy_headers_from_non_loopback_are_rejected():
    client = configured_app().test_client()

    response = client.get(
        "/probe",
        base_url="https://lab.tailnet.test",
        headers={"X-Forwarded-For": "127.0.0.1"},
        environ_overrides={"REMOTE_ADDR": "100.64.0.9"},
    )

    assert response.status_code == 400


def test_security_headers_and_secure_cookie_policy_are_enabled():
    app = configured_app()
    client = app.test_client()

    response = client.get("/probe", base_url="https://lab.tailnet.test")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_testing_mode_bypasses_browser_csrf_without_disabling_host_checks():
    app = configured_app(TESTING=True)
    client = app.test_client()

    assert client.post("/probe", base_url="http://127.0.0.1").status_code == 200
    assert client.get("/probe", headers={"Host": "attacker.example"}).status_code == 400
