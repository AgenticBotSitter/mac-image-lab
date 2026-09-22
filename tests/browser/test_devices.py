import importlib.util
import json
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

SPEC = importlib.util.spec_from_file_location("mac_image_lab_devices_browser", Path(__file__).parents[2] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


@pytest.fixture()
def live_devices(tmp_path, monkeypatch):
    if not CHROME.exists():
        pytest.skip("Installed Chrome is required for browser acceptance")
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "library")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "library-root")
    monkeypatch.setenv("MAC_IMAGE_LAB_DATABASE", str(tmp_path / "library.sqlite3"))
    server = make_server("127.0.0.1", 0, lab.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_manifest_worker_and_install_metadata_are_private_safe(live_devices):
    base_url = live_devices
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        page.goto(f"{base_url}/", wait_until="networkidle")
        assert page.locator('link[rel="manifest"]').get_attribute("href") == "/static/manifest.webmanifest"
        manifest = page.request.get(f"{base_url}/static/manifest.webmanifest")
        assert manifest.ok
        payload = json.loads(manifest.text())
        assert payload["display"] == "standalone"
        assert {icon["sizes"] for icon in payload["icons"]} == {"192x192", "512x512"}
        worker = page.request.get(f"{base_url}/service-worker.js")
        assert worker.ok
        assert worker.headers["service-worker-allowed"] == "/"
        source = worker.text()
        assert "Private images, runs, APIs, exports, and navigations are never cached" in source
        assert 'SHELL.includes(url.pathname)' in source
        browser.close()


def test_unsent_prompt_survives_reload_and_offline_state_is_explicit(live_devices):
    base_url = live_devices
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        page = context.new_page()
        page.goto(f"{base_url}/create", wait_until="networkidle")
        page.locator("#prompt").fill("Unsent cross-device draft")
        page.reload(wait_until="networkidle")
        assert page.locator("#prompt").input_value() == "Unsent cross-device draft"
        context.set_offline(True)
        page.evaluate("window.dispatchEvent(new Event('offline'))")
        assert page.locator("#connection-banner").is_visible()
        assert "unsent text" in page.locator("#connection-banner").inner_text().lower()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        browser.close()
