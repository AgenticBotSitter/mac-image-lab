import hashlib
import importlib.util
import json
import threading
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

SPEC = importlib.util.spec_from_file_location("mac_image_lab_compare_browser", Path(__file__).parents[2] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def seed(root, index, size, *, transformed=False):
    run_id = f"30000000-0000-0000-0000-{index:012d}"
    family = "30000000-0000-0000-0000-000000000001"
    directory = root / run_id
    directory.mkdir(parents=True)
    output = directory / "output.png"
    Image.new("RGB", size, (40 * index, 60, 100)).save(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    reference = {"enabled": False}
    if transformed:
        source = directory / "reference-original.png"
        Image.new("RGB", (900, 900), (20, 100, 60)).save(source)
        reference = {"enabled": True, "source_file": source.name, "original_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "source_run_id": None}
    receipt = {
        "run_id": run_id, "family_id": family, "parent_run_id": None if index == 1 else f"30000000-0000-0000-0000-{index-1:012d}",
        "relationship": "reference_transform" if transformed else "original" if index == 1 else "variation",
        "model_id": "qwen-image-2.1-local", "title": f"Compare Study {index}", "prompt": f"prompt version {index}", "profile": "fast",
        "parameters": {"width": size[0], "height": size[1], "steps": 8 + index, "seed": index},
        "created_at": f"2026-09-21T14:{index:02d}:00Z", "generation_state": "succeeded", "archive_state": "local_only",
        "output": {"file": "output.png", "sha256": digest, "width": size[0], "height": size[1]}, "reference_edit": reference,
    }
    (directory / "receipt.json").write_text(json.dumps(receipt))
    lab.write_receipt(run_id, receipt)
    return run_id


@pytest.fixture()
def live_compare(tmp_path, monkeypatch):
    if not CHROME.exists(): pytest.skip("Installed Chrome is required")
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "THUMBNAIL_ROOT", tmp_path / "thumbs")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "library")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "library-root")
    ids = [seed(lab.RUNS, 1, (1200, 800)), seed(lab.RUNS, 2, (1200, 800)), seed(lab.RUNS, 3, (700, 1200), transformed=True)]
    server = make_server("127.0.0.1", 0, lab.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{server.server_port}", ids
    finally: server.shutdown(); thread.join(timeout=5)


def test_compare_side_by_side_slider_diff_and_no_generation(live_compare):
    base, ids = live_compare
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        posts = []
        page.on("request", lambda req: posts.append(req.url) if req.method == "POST" else None)
        page.goto(f"{base}/compare?left={ids[0]}&right={ids[1]}", wait_until="networkidle")
        assert page.locator("#compare-side-by-side .compare-image").count() == 2
        assert page.locator(".settings-diff").is_visible()
        assert page.get_by_text("Seed", exact=True).is_visible()
        assert page.locator("#sync-zoom").is_enabled()
        page.get_by_role("button", name="Slider view").click()
        assert page.locator("#compare-slider-view").is_visible()
        page.locator("#compare-position").fill("35")
        assert "35%" in page.locator("#compare-overlay").get_attribute("style")
        assert not posts
        browser.close()


def test_compare_warns_on_aspect_mismatch_and_exposes_exact_source(live_compare):
    base, ids = live_compare
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"{base}/compare?left={ids[0]}&right={ids[2]}", wait_until="networkidle")
        assert page.get_by_text("Aspect ratios differ", exact=False).is_visible()
        assert page.locator("#sync-zoom").is_disabled()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.locator("select[name='right']").select_option(f"source:{ids[2]}")
        page.get_by_role("button", name="Compare selected").click()
        page.wait_for_load_state("networkidle")
        assert page.locator("#compare-side-by-side figcaption b").filter(has_text="Exact source").is_visible()
        assert page.get_by_text("Exact source asset · 900×900", exact=True).is_visible()
        assert f"/media/{ids[2]}/reference" in page.locator("#compare-right").get_attribute("src")
        browser.close()


def test_preferred_version_action_is_persisted(live_compare):
    base, ids = live_compare
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page()
        page.goto(f"{base}/compare?left={ids[0]}&right={ids[1]}", wait_until="networkidle")
        page.get_by_role("button", name="Prefer right version").click()
        page.wait_for_load_state("networkidle")
        assert page.get_by_text("Preferred version", exact=False).is_visible()
        browser.close()
