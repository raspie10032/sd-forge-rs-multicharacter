# SPDX-License-Identifier: GPL-3.0-only
"""Local FastAPI adapters for the unchanged standalone 3D editor."""
import json
from pathlib import Path

from modules import script_callbacks

from . import __version__

ASSETS = Path(__file__).parent / 'shared/web/pose3d'
FORGE_ASSETS = Path(__file__).parent / 'web'
PREFIX = '/rs_mc_forge'
POSE_API = PREFIX + '/rs_mc/pose3d'


def library_directory():
    from modules.paths import models_path
    return Path(models_path) / 'rs_pose3d'


def register_app(demo, app):
    from fastapi import Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from starlette.concurrency import run_in_threadpool

    async def bounded(request, limit):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > limit:
                raise ValueError('Request is too large.')
        return bytes(body)

    async def execute(request, function, limit=100_000):
        try:
            raw = await bounded(request, limit)
            return await run_in_threadpool(function, raw)
        except (ValueError, TypeError, KeyError, UnicodeError, OSError) as error:
            return JSONResponse({'error': str(error)}, status_code=400)

    @app.get(PREFIX + '/assets/web/pose3d/{filename}')
    def asset(filename: str):
        path = (ASSETS / filename).resolve()
        if path.parent != ASSETS.resolve() or not path.is_file():
            return JSONResponse({'error': 'Unknown editor asset.'}, status_code=404)
        if filename == 'index.html':
            html = path.read_text(encoding='utf-8').replace('<script type="module"',
                f'<link rel="stylesheet" href="/rs_mc_forge/forge-assets/pose-adapter.css?v={__version__}">'
                f'<script src="/rs_mc_forge/forge-assets/pose-adapter.js?v={__version__}"></script>'
                '<script type="module"')
            return HTMLResponse(html, headers={'Cache-Control': 'no-store'})
        media = 'text/javascript' if path.suffix == '.mjs' else None
        return FileResponse(path, media_type=media)

    @app.get(PREFIX + '/forge-assets/{filename}')
    def forge_asset(filename: str):
        path = (FORGE_ASSETS / filename).resolve()
        if path.parent != FORGE_ASSETS.resolve() or not path.is_file():
            return JSONResponse({'error': 'Unknown Forge editor asset.'}, status_code=404)
        return FileResponse(path)

    @app.get(PREFIX + '/default-scene')
    def default_scene():
        from .shared.mhr import default_scene
        return default_scene()

    @app.post(POSE_API + '/preview')
    async def preview(request: Request):
        from .pose import preview_payload
        return await execute(request, lambda raw: preview_payload(raw.decode()))

    @app.get(POSE_API + '/library')
    def library():
        from .shared.pose_library import read_library
        return read_library([library_directory()])

    @app.post(POSE_API + '/library')
    async def save(request: Request):
        from .shared.pose_library import save_pose
        return await execute(request, lambda raw: {'pose': save_pose(json.loads(raw), library_directory())})

    @app.post(POSE_API + '/library/batch')
    async def batch(request: Request):
        from .shared.pose_library import save_poses
        return await execute(request, lambda raw: {'poses': save_poses(json.loads(raw)['poses'], library_directory())}, 32_000_000)

    @app.post(POSE_API + '/import')
    async def import_pose(request: Request, filename: str = 'pose.json', frame: int = 0):
        from .shared.pose_import import import_file
        return await execute(request, lambda raw: import_file(raw, filename, frame=frame), 32_000_000)


script_callbacks.on_app_started(register_app)
