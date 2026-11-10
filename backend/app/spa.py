"""Serve the built React SPA (`frontend/dist`) from FastAPI (#22).

Only active when `STATIC_DIR` points to a directory with an `index.html` (the Docker image sets
it). In dev and tests it is unset and the app serves the API only.

- `/assets/*` are the hashed Vite bundles (served as static files).
- Any other non-`/api` GET returns a real file from the directory if one exists (for example
  `/favicon.svg`), otherwise `index.html` so client-side routes such as `/projects/<id>` work.
- `/api` and `/api/*` never fall back to `index.html`: unknown API paths stay a JSON 404.
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.errors import NotFoundError

logger = logging.getLogger(__name__)

API_PREFIX = "api"
INDEX_FILE = "index.html"
# index.html must be revalidated so a deploy is picked up; hashed assets are cached by the browser.
_INDEX_HEADERS = {"Cache-Control": "no-cache"}


def _is_api_path(path: str) -> bool:
    return path == API_PREFIX or path.startswith(f"{API_PREFIX}/")


def mount_spa(app: FastAPI, static_dir: Path | None) -> bool:
    """Register the SPA routes. Call it after every API router (the catch-all must be last).

    Returns True when the SPA is served, False when `static_dir` is unset or has no index.html.
    """
    if static_dir is None:
        return False
    root = static_dir.resolve()
    index = root / INDEX_FILE
    if not index.is_file():
        logger.warning("static dir has no index.html; serving the API only")
        return False

    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if _is_api_path(full_path):
            raise NotFoundError("Not Found")
        if full_path:
            candidate = (root / full_path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index, headers=_INDEX_HEADERS)

    return True
