# SPDX-License-Identifier: GPL-3.0-only
"""Local FastAPI adapters for the unchanged standalone 3D editor."""

import json
from pathlib import Path

from modules import script_callbacks

from . import __version__

LAST_AUDIT = {}

ASSETS = Path(__file__).parent / "shared/web/pose3d"
FORGE_ASSETS = Path(__file__).parent / "web"
PREFIX = "/rs_mc_forge"
POSE_API = PREFIX + "/rs_mc/pose3d"


def library_directory():
    from modules.paths import models_path

    return Path(models_path) / "rs_pose3d"


def register_app(demo, app):
    @app.get("/rs_mc_forge/last-audit")
    async def last_audit():
        return LAST_AUDIT

    from fastapi import Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from starlette.concurrency import run_in_threadpool

    async def bounded(request, limit):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > limit:
                raise ValueError("Request is too large.")
        return bytes(body)

    async def execute(request, function, limit=100_000):
        try:
            raw = await bounded(request, limit)
            return await run_in_threadpool(function, raw)
        except (ValueError, TypeError, KeyError, UnicodeError, OSError, RuntimeError) as error:
            return JSONResponse({"error": str(error)}, status_code=400)

    @app.post(PREFIX + "/reference")
    async def reference(request: Request):
        from .assets import save_image

        return await execute(request, save_image, 32_000_000)

    @app.get(PREFIX + "/reference/{key}")
    def reference_image(key: str):
        from .assets import asset_path

        try:
            return FileResponse(asset_path(key))
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=404)

    @app.post(PREFIX + "/openpose")
    async def openpose(request: Request, filename: str = "pose.json"):
        import io
        import numpy as np
        from PIL import Image
        from .shared.pose_image import decode_pose_image

        def convert(raw):
            data = (
                json.loads(raw)
                if filename.lower().endswith(".json")
                else decode_pose_image(np.asarray(Image.open(io.BytesIO(raw)).convert("RGB")))
            )
            from .shared.pose_parts import compile_semantic_parts

            compile_semantic_parts(data, len(data["people"]))
            return data

        return await execute(request, convert, 32_000_000)

    @app.post(PREFIX + "/image-pose")
    async def image_pose(request: Request, character: int = 1, scene: str = ""):
        from .image_pose import estimate
        from .assets import read_image

        if not 1 <= character <= 10:
            return JSONResponse({"error": "Choose character 1–10."}, status_code=400)

        def infer(raw):
            from modules.call_queue import queue_lock
            from modules import shared

            with queue_lock:
                shared.state.begin("RS image to 3D")
                try:
                    return estimate(read_image(raw), character, scene)
                finally:
                    shared.state.end()

        return await execute(request, infer, 20_000_000)

    @app.post(PREFIX + "/detail-folder")
    async def detail_folder(request: Request):
        from .folder_detail import run

        return await execute(request, run, 4_000_000)

    @app.get(PREFIX + "/detectors")
    def detectors():
        from .detail import detector_files

        return detector_files()

    @app.post(PREFIX + "/import-settings")
    async def import_settings(request: Request, filename: str = "settings.json"):
        from .assets import import_record

        return await execute(request, lambda raw: import_record(raw, filename), 32_000_000)

    @app.post(PREFIX + "/nai-export")
    async def nai_export(request: Request):
        from .assets import nai_record
        from .config import Config

        def convert(raw):
            value = json.loads(raw)
            return nai_record(
                Config.from_json(json.dumps(value.get("config", value))),
                value.get("prompt", ""),
                value.get("negative", ""),
            )

        return await execute(request, convert, 4_000_000)

    @app.post(PREFIX + "/tag")
    async def tag(request: Request, model: str = "WD ViT v3"):
        def analyze(raw):
            from .assets import read_image
            from .host import models_dir
            from .shared.wd_tagger import WDTagger

            if model not in ("WD ViT v3", "WD EVA02 Large v3", "PixAI Tagger v1.0"):
                raise ValueError("Unknown tagger.")
            from .runtime import RUNTIME_LOCK

            with RUNTIME_LOCK:
                scores = WDTagger(models_dir() / "rs_wd_tagger", device="cpu", model_name=model).score(
                    [read_image(raw)]
                )[0]
            return {"tags": {k: float(v) for k, v in scores.items() if v >= 0.35}}

        return await execute(request, analyze, 32_000_000)

    @app.get(PREFIX + "/assets/web/pose3d/{filename}")
    def asset(filename: str):
        path = (ASSETS / filename).resolve()
        if path.parent != ASSETS.resolve() or not path.is_file():
            return JSONResponse({"error": "Unknown editor asset."}, status_code=404)
        if filename == "index.html":
            html = path.read_text(encoding="utf-8").replace(
                '<script type="module"',
                f'<link rel="stylesheet" href="/rs_mc_forge/forge-assets/pose-adapter.css?v={__version__}">'
                f'<script src="/rs_mc_forge/forge-assets/pose-adapter.js?v={__version__}"></script>'
                '<script type="module"',
            )
            return HTMLResponse(html, headers={"Cache-Control": "no-store"})
        media = "text/javascript" if path.suffix == ".mjs" else None
        return FileResponse(path, media_type=media)

    @app.get(PREFIX + "/forge-assets/{filename}")
    def forge_asset(filename: str):
        path = (FORGE_ASSETS / filename).resolve()
        if path.parent != FORGE_ASSETS.resolve() or not path.is_file():
            return JSONResponse({"error": "Unknown Forge editor asset."}, status_code=404)
        return FileResponse(path)

    @app.get(PREFIX + "/default-scene")
    def default_scene():
        from .shared.mhr import default_scene

        return default_scene()

    @app.post(POSE_API + "/preview")
    async def preview(request: Request):
        from .pose import preview_payload

        return await execute(request, lambda raw: preview_payload(raw.decode()))

    @app.get(POSE_API + "/library")
    def library():
        from .shared.pose_library import read_library

        return read_library([library_directory()])

    @app.post(POSE_API + "/library")
    async def save(request: Request):
        from .shared.pose_library import save_pose

        return await execute(request, lambda raw: {"pose": save_pose(json.loads(raw), library_directory())})

    @app.post(POSE_API + "/library/batch")
    async def batch(request: Request):
        from .shared.pose_library import save_poses

        return await execute(
            request,
            lambda raw: {"poses": save_poses(json.loads(raw)["poses"], library_directory())},
            32_000_000,
        )

    @app.post(POSE_API + "/import")
    async def import_pose(request: Request, filename: str = "pose.json", frame: int = 0):
        from .shared.pose_import import import_file

        return await execute(request, lambda raw: import_file(raw, filename, frame=frame), 32_000_000)


script_callbacks.on_app_started(register_app)


def register_settings():
    import gradio as gr
    from modules import shared

    shared.opts.add_option(
        "rs_mc_model_roots",
        shared.OptionInfo(
            "",
            "RS additional model directories (separate with " + __import__("os").pathsep + ")",
            gr.Textbox,
            section=("rs_multicharacter", "RS MultiCharacter"),
        ),
    )


script_callbacks.on_ui_settings(register_settings)
