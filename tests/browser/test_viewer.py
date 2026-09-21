import hashlib
import importlib.util
import json
import threading
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

SPEC = importlib.util.spec_from_file_location("mac_image_lab_viewer_browser", Path(__file__).parents[2] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def seed_run(root: Path, index: int, size: tuple[int, int], *, family_id: str, state: str = "succeeded") -> str:
    run_id = f"20000000-0000-0000-0000-{index:012d}"
    directory = root / run_id
    directory.mkdir(parents=True)
    output_record = None
    if state == "succeeded":
        output = directory / "output.png"
        Image.new("RGB", size, (25 + index * 30, 65, 95)).save(output)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        output_record = {"file": "output.png", "sha256": digest, "width": size[0], "height": size[1]}
    receipt = {
        "run_id": run_id,
        "family_id": family_id,
        "relationship": "original" if index == 1 else "variation",
        "model_id": "qwen-image-2.1-local",
        "title": f"Viewer Study {index}",
        "prompt": ("A deliberately long botanical prompt with precise texture, directional light, muted material notes, and composition instructions. " * 12).strip(),
        "profile": "fast",
        "parameters": {"width": size[0], "height": size[1], "steps": 8, "seed": index},
        "created_at": f"2026-09-21T13:{index:02d}:00Z",
        "generation_state": state,
        "archive_state": "verified" if index == 1 else "local_only",
        "library_folder": "Collections/Viewer",
        "output": output_record,
        "error": "Backend disconnected during generation" if state == "failed" else None,
    }
    (directory / "receipt.json").write_text(json.dumps(receipt))
    lab.write_receipt(run_id, receipt)
    return run_id


@pytest.fixture()
def live_viewer(tmp_path, monkeypatch):
    if not CHROME.exists():
        pytest.skip("Installed Chrome is required for browser acceptance")
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "THUMBNAIL_ROOT", tmp_path / "thumbnails")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "library")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "library-root")
    family_id = "20000000-0000-0000-0000-000000000001"
    run_ids = [
        seed_run(lab.RUNS, 1, (1600, 900), family_id=family_id),
        seed_run(lab.RUNS, 2, (700, 1500), family_id=family_id),
        seed_run(lab.RUNS, 3, (1500, 700), family_id=family_id),
        seed_run(lab.RUNS, 4, (768, 768), family_id="20000000-0000-0000-0000-000000000004", state="failed"),
    ]
    server = make_server("127.0.0.1", 0, lab.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", run_ids
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_original_loads_only_after_opening_accessible_viewer(live_viewer):
    base_url, run_ids = live_viewer
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        requested = []
        page.on("request", lambda request: requested.append(request.url))
        page.goto(f"{base_url}/runs/{run_ids[0]}", wait_until="networkidle")
        assert "/thumbnail/960" in page.locator("#detail-preview").get_attribute("src")
        assert not any("/media/" in url and "/original" in url for url in requested)
        opener = page.get_by_role("button", name="Open fullscreen viewer")
        opener.click()
        dialog = page.locator("#image-viewer")
        assert dialog.evaluate("dialog => dialog.open")
        assert page.locator("#viewer-close").evaluate("el => document.activeElement === el")
        assert page.locator("#viewer-image").get_attribute("src").endswith("/original")
        assert any("/media/" in url and "/original" in url for url in requested)
        page.get_by_role("button", name="Show image details").click()
        assert page.locator("#viewer-metadata").get_attribute("aria-hidden") == "false"
        page.locator("#viewer-stage").focus()
        page.keyboard.press("Tab")
        assert page.locator("#image-viewer").evaluate("dialog => dialog.contains(document.activeElement)")
        page.keyboard.press("Escape")
        assert not dialog.evaluate("dialog => dialog.open")
        assert opener.evaluate("el => document.activeElement === el")
        browser.close()


def test_viewer_supports_zoom_pan_and_family_keyboard_navigation(live_viewer):
    base_url, run_ids = live_viewer
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1000, "height": 800})
        page.goto(f"{base_url}/runs/{run_ids[0]}", wait_until="networkidle")
        page.get_by_role("button", name="Open fullscreen viewer").click()
        page.get_by_role("button", name="Zoom in").click()
        assert float(page.locator("#viewer-stage").get_attribute("data-scale")) > 1
        page.get_by_role("button", name="Reset zoom").click()
        assert page.locator("#viewer-stage").get_attribute("data-scale") == "1"
        page.keyboard.press("ArrowRight")
        page.wait_for_url(f"**/runs/{run_ids[1]}")
        assert page.get_by_role("heading", name="Viewer Study 2").is_visible()
        browser.close()


def test_detail_is_responsive_reduced_motion_and_handles_failed_runs(live_viewer):
    base_url, run_ids = live_viewer
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        page.goto(f"{base_url}/runs/{run_ids[1]}", wait_until="networkidle")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_role("button", name="Open fullscreen viewer").click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert float(page.locator("#viewer-stage").evaluate("el => parseFloat(getComputedStyle(el).transitionDuration)")) <= 0.001
        page.goto(f"{base_url}/runs/{run_ids[3]}", wait_until="networkidle")
        assert page.get_by_role("heading", name="Generation failed").is_visible()
        assert page.get_by_text("Backend disconnected", exact=False).is_visible()
        assert page.locator("#image-viewer").count() == 0
        browser.close()


def test_detail_links_only_to_evidence_files_that_exist(live_viewer):
    base_url, run_ids = live_viewer
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page()
        page.goto(f"{base_url}/runs/{run_ids[0]}", wait_until="networkidle")
        assert page.locator('a[href$="/download/receipt.json"]').count() == 1
        assert page.locator('a[href$="/download/workflow.json"]').count() == 0
        assert page.locator('a[href$="/download/comfy-history.json"]').count() == 0
        browser.close()
