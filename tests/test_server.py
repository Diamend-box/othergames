"""End-to-end checks against a real server on a real socket."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from satplanner.config import Settings
from satplanner.service import PlannerService
from satplanner.web.server import make_server


@pytest.fixture
def server(docs, plan, state, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))  # keep the saved plan out of the real profile
    settings = Settings(save_dir=None, docs_json=None, modeler_dir=None)
    service = PlannerService(settings)
    service.docs = docs
    service.plan = plan
    service.state = state

    httpd = make_server(service, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, service
    finally:
        httpd.shutdown()
        httpd.server_close()


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return json.loads(response.read())


def post(base, path, payload):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def test_the_page_is_served(server):
    base, _ = server
    with urllib.request.urlopen(base + "/", timeout=5) as response:
        body = response.read().decode()
    assert "Satisfactory Build Planner" in body
    assert response.headers["Content-Type"] == "text/html"


def test_static_assets_are_served(server):
    base, _ = server
    for name, content_type in [("app.js", "text/javascript"), ("style.css", "text/css")]:
        with urllib.request.urlopen(f"{base}/static/{name}", timeout=5) as response:
            assert response.status == 200
            assert content_type in response.headers["Content-Type"]


def test_the_report_reaches_the_browser_intact(server):
    base, _ = server
    report = get(base, "/api/report")
    assert report["ok"]
    assert report["progress"]["machines_missing"] == 5
    assert report["power_mw"] == 40.0
    assert any(row["missing"] == 2 for row in report["rows"])
    assert report["build_order"][0]["blocks"] == ["Iron smelting"]


def test_the_grid_payload_carries_world_coordinates(server):
    base, _ = server
    grid = get(base, "/api/grid")
    assert grid["ok"]
    assert grid["anchor"]["cell_uu"] == 800.0
    assert len(grid["built"]) == 5
    assert len(grid["suggested"]) == 5
    assert all("world_x" in s for s in grid["suggested"])


def test_a_plan_can_be_saved_and_read_back(server):
    base, service = server
    new_plan = {
        "name": "Rods",
        "blocks": [{"id": "rods", "name": "Rods", "machines": [
            {"building_class": "Build_ConstructorMk1_C", "recipe_class": "Recipe_IronRod_C", "count": 3}
        ]}],
    }
    assert post(base, "/api/plan", {"plan": new_plan})["ok"]
    assert get(base, "/api/plan")["plan"]["name"] == "Rods"
    assert service.plan_path.is_file()


def test_a_nonsense_plan_is_rejected_with_a_message(server):
    base, _ = server
    result = post(base, "/api/plan", {"plan": {"blocks": [{"machines": [{"nope": 1}]}]}})
    assert not result["ok"]
    assert "did not make sense" in result["error"]


def test_status_reports_what_was_and_was_not_found(server):
    base, _ = server
    status = get(base, "/api/status")
    assert status["ok"]
    assert status["docs_loaded"]
    assert status["plan"]["machines"] == 10


def test_selecting_a_save_that_does_not_exist_fails_politely(server):
    base, _ = server
    result = post(base, "/api/select-save", {"path": "/definitely/not/here.sav"})
    assert not result["ok"]
    assert "No such save file" in result["error"]


def test_scanning_modeler_without_a_folder_explains_itself(server):
    base, _ = server
    result = get(base, "/api/modeler/scan")
    assert not result["ok"]
    assert "Modeler" in result["error"]


def test_unknown_routes_return_404(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(base, "/api/nope")
    assert exc.value.code == 404


def test_static_paths_cannot_escape_the_static_folder(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(base + "/static/../../config.py", timeout=5)
    assert exc.value.code == 404
