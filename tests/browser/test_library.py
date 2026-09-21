import hashlib
import importlib.util
import json
import threading
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

SPEC = importlib.util.spec_from_file_location("mac_image_lab_browser", Path(__file__).parents[2] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def seed_run(root: Path, index: int, size: tuple[int, int]):
    run_id = f"10000000-0000-0000-0000-{index:012d}"
    directory = root / run_id
    directory.mkdir(parents=True)
    output = directory / "output.png"
    Image.new("RGB", size, (30 + index * 15, 80, 45 + index * 8)).save(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    receipt = {
        "run_id": run_id,
        "family_id": run_id if index < 5 else "10000000-0000-0000-0000-000000000001",
        "relationship": "original" if index < 5 else "variation",
        "model_id": "qwen-image-2.1-local",
        "title": f"Botanical Study {index}",
        "prompt": f"botanical still life number {index}",
        "profile": "fast",
        "parameters": {"width": size[0], "height": size[1], "steps": 8, "seed": index},
        "created_at": f"2026-09-21T12:{index:02d}:00Z",
        "generation_state": "succeeded",
        "archive_state": "local_only",
        "favorite": index in {1, 3},
        "library_folder": "Collections/Botanical" if index % 2 else "Inbox",
        "output": {"file": "output.png", "sha256": digest, "width": size[0], "height": size[1]},
    }
    (directory / "receipt.json").write_text(json.dumps(receipt))
    lab.write_receipt(run_id, receipt)


@pytest.fixture()
def live_library(tmp_path, monkeypatch):
    if not CHROME.exists():
        pytest.skip("Installed Chrome is required for browser acceptance")
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "THUMBNAIL_ROOT", tmp_path / "thumbnails")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "library")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "library-root")
    sizes = [(1200, 800), (800, 1200), (900, 900), (1400, 700), (700, 1400), (1024, 768), (768, 1024), (1200, 900)]
    for index, size in enumerate(sizes, 1):
        seed_run(lab.RUNS, index, size)
    server = make_server("127.0.0.1", 0, lab.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_library_is_image_first_and_has_no_horizontal_overflow(live_library):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        requested = []
        page.on("request", lambda request: requested.append(request.url))
        page.goto(live_library, wait_until="networkidle")
        assert page.locator(".image-tile").count() == 8
        assert not any("/download/output.png" in url for url in requested)
        assert page.locator(".image-tile").first.bounding_box()["y"] < 500
        assert page.locator(".image-tile img").evaluate_all("els => els.every(el => el.loading === 'lazy' && el.src.includes('/thumbnail/'))")
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        browser.close()


def test_density_layout_and_filter_controls_are_accessible_and_persist(live_library):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(live_library, wait_until="networkidle")
        panel = page.locator("#filter-panel")
        assert panel.evaluate("el => getComputedStyle(el).display") == "none"
        page.get_by_role("button", name="Filters").click()
        assert panel.evaluate("el => getComputedStyle(el).display") != "none"
        page.get_by_role("button", name="Compact density").click()
        page.get_by_role("button", name="Cropped layout").click()
        assert "compact" in page.locator("#image-grid").get_attribute("class")
        assert "cropped" in page.locator("#image-grid").get_attribute("class")
        page.reload(wait_until="networkidle")
        assert "compact" in page.locator("#image-grid").get_attribute("class")
        assert "cropped" in page.locator("#image-grid").get_attribute("class")
        browser.close()
