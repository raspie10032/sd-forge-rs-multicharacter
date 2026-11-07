import importlib
import sys
from types import ModuleType, SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def editor_client(monkeypatch, tmp_path):
    # Only the WebUI app callback/path registry is replaced; the editor APIs,
    # FastAPI router, asset files, pose importer, and rasterizer are real.
    modules = ModuleType("modules")
    modules.script_callbacks = SimpleNamespace(
        on_app_started=lambda callback: None, on_ui_settings=lambda callback: None
    )
    paths = ModuleType("modules.paths")
    paths.models_path = str(tmp_path)
    monkeypatch.setitem(sys.modules, "modules", modules)
    monkeypatch.setitem(sys.modules, "modules.paths", paths)
    sys.modules.pop("rs_forge_mc.api", None)
    api = importlib.import_module("rs_forge_mc.api")
    app = FastAPI()
    api.register_app(None, app)
    return TestClient(app), api


def test_original_editor_assets_and_mask_api(monkeypatch, tmp_path):
    client, api = editor_client(monkeypatch, tmp_path)
    response = client.get("/rs_mc_forge/assets/web/pose3d/index.html")
    assert response.status_code == 200
    assert "editor.bundle.mjs" in response.text
    assert "/forge-assets/pose-adapter.js" in response.text
    assert client.get("/rs_mc_forge/forge-assets/pose-adapter.js").status_code == 200
    assert client.get("/rs_mc_forge/forge-assets/missing.js").status_code == 404
    assert (
        client.get("/rs_mc_forge/assets/web/pose3d/editor.bundle.mjs")
        .headers["content-type"]
        .startswith("text/javascript")
    )
    scene = client.get("/rs_mc_forge/default-scene").json()
    response = client.post(api.POSE_API + "/preview", json=scene)
    assert response.status_code == 200
    assert response.json()["masks"][0]["number"] == 1
    assert sum(response.json()["masks"][0]["data"]) > 0
    assert client.post(api.POSE_API + "/preview", content=b"x" * 100_001).status_code == 400
    assert client.get("/rs_mc_forge/assets/web/pose3d/missing.mjs").status_code == 404


def test_persistent_pose_library(monkeypatch, tmp_path):
    client, api = editor_client(monkeypatch, tmp_path)
    response = client.post(
        api.POSE_API + "/library",
        json={"id": "test-pose", "name": "Test", "joints": {"left_shoulder": [20, 0, 0]}, "floor_y": 0},
    )
    assert response.status_code == 200, response.text
    response = client.get(api.POSE_API + "/library")
    assert response.status_code == 200
    assert response.json()["poses"][0]["name"] == "Test"
    assert (tmp_path / "rs_pose3d/user-library.json").exists()
