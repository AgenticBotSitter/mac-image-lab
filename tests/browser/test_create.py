import importlib.util
import threading
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

SPEC = importlib.util.spec_from_file_location("mac_image_lab_create_browser", Path(__file__).parents[2] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


@pytest.fixture()
def live_create(tmp_path, monkeypatch):
    if not CHROME.exists():
        pytest.skip("Installed Chrome is required for browser acceptance")
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "library")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "library-root")
    alternate = dict(lab.MODELS["qwen-image-2.1-local"])
    alternate.update({
        "label": "Test-only alternate",
        "status": "available",
        "guide": {"summary": "Alternate model guidance for the browser contract.", "strengths": ["Test switching"], "avoid": ["Silent prompt rewrites"]},
    })
    monkeypatch.setitem(lab.MODELS, "test-only-alternate", alternate)
    image = tmp_path / "source.png"
    Image.new("RGB", (640, 480), (80, 120, 60)).save(image)
    server = make_server("127.0.0.1", 0, lab.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", image
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_create_preserves_edited_prompt_until_recipe_is_confirmed(live_create):
    base_url, _ = live_create
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.goto(f"{base_url}/create", wait_until="networkidle")
        prompt = page.locator("#prompt")
        assert prompt.input_value()
        prompt.fill("My carefully edited prompt")
        page.locator("#recipe").select_option(index=1)
        page.get_by_role("button", name="Use recipe").click()
        assert prompt.input_value() == "My carefully edited prompt"
        assert page.get_by_text("Press Use recipe again", exact=False).is_visible()
        page.get_by_role("button", name="Use recipe").click()
        assert prompt.input_value() != "My carefully edited prompt"
        browser.close()


def test_quality_and_aspect_are_orthogonal_and_model_guidance_switches(live_create):
    base_url, _ = live_create
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page()
        page.goto(f"{base_url}/create", wait_until="networkidle")
        page.locator("select[name='profile']").select_option("standard")
        page.locator("select[name='aspect']").select_option("portrait")
        assert page.locator("input[name='width']").input_value() == "896"
        assert page.locator("input[name='height']").input_value() == "1152"
        assert "6 minutes" in page.locator("#queue-estimate").inner_text()
        original_prompt = page.locator("#prompt").input_value()
        page.locator("select[name='model_id']").select_option("test-only-alternate")
        assert page.locator("#prompt").input_value() == original_prompt
        assert page.get_by_text("Alternate model guidance", exact=False).is_visible()
        browser.close()


def test_transform_upload_preview_and_submit_guard_work_on_phone(live_create):
    base_url, image = live_create
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        page.goto(f"{base_url}/transform", wait_until="networkidle")
        page.locator("input[name='reference']").set_input_files(str(image))
        assert page.locator("#upload-preview img").is_visible()
        assert "640×480" in page.locator("#upload-metadata").inner_text()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_role("button", name="Remove source image").click()
        assert page.locator("input[name='reference']").input_value() == ""
        submit = page.locator("#generation-submit")
        page.locator("#generation-form").evaluate("form => form.dispatchEvent(new Event('submit', {cancelable: true}))")
        assert submit.is_disabled()
        browser.close()
