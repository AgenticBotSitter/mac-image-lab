import importlib.util
import json
from pathlib import Path

from jinja2 import FileSystemLoader

SPEC = importlib.util.spec_from_file_location("mac_image_lab_routes", Path(__file__).parents[1] / "app" / "app.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(lab, "GENERATED_ROOT", tmp_path / "library")
    monkeypatch.setattr(lab, "LIBRARY_ROOT", tmp_path / "library-root")
    monkeypatch.setattr(lab.app, "jinja_loader", FileSystemLoader(Path(__file__).parents[1] / "app" / "templates"))
    return lab.app.test_client()


def test_library_is_landing_page_and_create_has_generation_form(tmp_path, monkeypatch):
    browser = client(tmp_path, monkeypatch)

    library = browser.get("/")
    create = browser.get("/create")

    assert library.status_code == 200
    assert b"Image Library" in library.data
    assert b'action="/generate"' not in library.data
    assert create.status_code == 200
    assert b'action="/generate"' in create.data


def test_gallery_redirects_to_library_and_primary_routes_exist(tmp_path, monkeypatch):
    browser = client(tmp_path, monkeypatch)

    gallery = browser.get("/gallery")

    assert gallery.status_code == 302
    assert gallery.headers["Location"].endswith("/")
    for route in ["/create", "/transform", "/compare", "/queue", "/settings", "/styles"]:
        response = browser.get(route)
        assert response.status_code == 200, route
        assert b"Mac Image Lab" in response.data


def test_shared_shell_labels_navigation_consistently(tmp_path, monkeypatch):
    browser = client(tmp_path, monkeypatch)

    for route in ["/", "/create", "/compare", "/queue", "/settings"]:
        page = browser.get(route).get_data(as_text=True)
        for label in ["Library", "Create", "Compare", "Queue", "Settings"]:
            assert label in page


def test_untrusted_referrer_is_not_used_for_folder_redirect(tmp_path, monkeypatch):
    browser = client(tmp_path, monkeypatch)

    response = browser.post(
        "/library/folders",
        data={"folder": "Collections/Test"},
        headers={"Referer": "https://attacker.example/phish"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert "attacker.example" not in response.headers["Location"]


def test_run_detail_uses_actual_output_dimensions(tmp_path, monkeypatch):
    browser = client(tmp_path, monkeypatch)
    run_id = "12345678-1234-1234-1234-123456789abc"
    directory = lab.RUNS / run_id
    directory.mkdir(parents=True)
    receipt = {
        "run_id": run_id,
        "family_id": run_id,
        "status": "local_only",
        "generation_state": "succeeded",
        "title": "Output size",
        "model_id": "qwen-image-2.1-local",
        "prompt": "test",
        "parameters": {"width": 768, "height": 768, "steps": 8, "seed": 1},
        "output": {"file": "output.png", "width": 1024, "height": 896},
    }
    (directory / "receipt.json").write_text(json.dumps(receipt))
    monkeypatch.setattr(lab, "family_groups", lambda: [{"family_id": run_id, "runs": [receipt]}])
    monkeypatch.setattr(lab, "list_library_folders", lambda: ["Inbox"])

    response = browser.get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert "1024×896" in response.get_data(as_text=True)


def test_rendered_pages_contain_no_inline_script(tmp_path, monkeypatch):
    browser = client(tmp_path, monkeypatch)

    for route in ["/", "/create", "/transform", "/queue", "/settings"]:
        page = browser.get(route).get_data(as_text=True)
        assert "<script>" not in page
