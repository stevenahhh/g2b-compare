"""Configure the local-only FastAPI application."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from g2b_compare.contracts.wire import HttpxRequester
from g2b_compare.db.migrate import migrate
from g2b_compare.priority_catalog import warm_catalog_index
from g2b_compare.priority_store import PriorityStore
from g2b_compare.sources.shopping_mall import ShoppingMallAdapter
from g2b_compare.sources.transport import HttpTransport

from .catalog_api import build_catalog_api_router
from .catalog_routes import build_catalog_router
from .data_api import build_data_api_router
from .data_routes import build_data_router
from .estimate_api import build_estimate_api_router
from .estimate_routes import build_estimate_router
from .links import load_product_links
from .live_routes import build_live_router
from .priority_web import build_priority_router
from .routes import build_router
from .sync_routes import build_sync_router

if TYPE_CHECKING:
    from g2b_compare.services.search_models import SearchReader

DEFAULT_LINK_MANIFEST: Final = Path("docs/api-contract-observed.json")
FRONTEND_DIST: Final = Path(__file__).parent / "frontend_dist"
CORE_SPA_PATHS: Final = frozenset(
    {"/", "/data", "/estimates", "/estimates/{estimate_id}"}
)


def _boot_assets(index: Path) -> None:
    asset_paths = {
        Path(match.split("?", maxsplit=1)[0].lstrip("/"))
        for match in re.findall(
            r"""(?:src|href)=["']([^"']+\.(?:js|css)(?:\?[^"']*)?)["']""",
            index.read_text(encoding="utf-8"),
        )
    }
    assets = FRONTEND_DIST / "assets"
    if not asset_paths:
        msg = f"Production SPA build has no boot assets: {index}"
        raise RuntimeError(msg)
    missing = [
        asset
        for asset in asset_paths
        if not (FRONTEND_DIST / asset).resolve().is_relative_to(assets.resolve())
        or not (FRONTEND_DIST / asset).is_file()
    ]
    if missing:
        listed = ", ".join(map(str, missing))
        msg = f"Production SPA build is missing boot assets: {listed}"
        raise RuntimeError(msg)


def _mount_frontend(app: FastAPI) -> None:
    index = FRONTEND_DIST / "index.html"
    worker = FRONTEND_DIST / "sw.js"
    assets = FRONTEND_DIST / "assets"
    if not index.is_file():
        msg = f"Production SPA build is missing: {index}"
        raise RuntimeError(msg)
    if not worker.is_file():
        msg = f"Production SPA build is missing: {worker}"
        raise RuntimeError(msg)
    if not assets.is_dir():
        msg = f"Production SPA build is missing: {assets}"
        raise RuntimeError(msg)
    _boot_assets(index)

    app.mount("/assets", StaticFiles(directory=assets), name="assets")

    def spa_page() -> FileResponse:
        return FileResponse(index, media_type="text/html")

    def service_worker() -> FileResponse:
        return FileResponse(worker, media_type="application/javascript")

    app.add_api_route("/sw.js", service_worker, methods=["GET"])
    for path in CORE_SPA_PATHS:
        app.add_api_route(path, spa_page, methods=["GET"])


@dataclass(frozen=True, slots=True)
class LiveSearchOverrides:
    """Test-only overrides for the live-search HTTP dependencies."""

    adapter: ShoppingMallAdapter | None = None
    service_key: str | None = None


def create_app(
    reader: SearchReader | None = None,
    *,
    database: Path | None = None,
    link_manifest: Path | None = None,
    live: LiveSearchOverrides | None = None,
    home: Path | None = None,
) -> FastAPI:
    """Create the app; production defaults to SPA and injected apps to legacy."""
    resolved_live = live or LiveSearchOverrides()
    root = Path(__file__).parent
    spa_mode = os.environ.get("G2B_SERVE_SPA")
    resolved_serve_spa = (
        spa_mode == "1"
        if spa_mode is not None
        else database is None and reader is None
    )
    app = FastAPI(title="나라장터 유사물품 비교")
    resolved_database = (
        Path("data/g2b-compare.sqlite3") if database is None else database
    )
    resolved_database.parent.mkdir(parents=True, exist_ok=True)
    _ = PriorityStore(resolved_database)
    migrate(resolved_database)
    if reader is None:
        warm_catalog_index(resolved_database)
    templates = Environment(
        loader=FileSystemLoader(root / "templates"),
        autoescape=select_autoescape(("html", "xml")),
    )
    app.mount("/static", StaticFiles(directory=root / "static"), name="static")
    if resolved_serve_spa:
        _mount_frontend(app)
    if reader is None:
        app.include_router(build_catalog_router(resolved_database, templates))
    else:
        app.include_router(
            build_router(
                reader,
                templates,
                load_product_links(link_manifest or DEFAULT_LINK_MANIFEST),
            )
        )
    app.include_router(build_priority_router(resolved_database, templates))
    app.include_router(build_data_router(resolved_database, templates))
    app.include_router(build_estimate_router(resolved_database, templates))
    app.include_router(build_catalog_api_router(resolved_database))
    app.include_router(build_estimate_api_router(resolved_database))
    app.include_router(build_data_api_router(resolved_database))

    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    def ready() -> JSONResponse:
        status = PriorityStore(resolved_database).status()
        is_ready = status.product_count > 0
        code = 200 if is_ready else 503
        return JSONResponse({"ready": is_ready}, status_code=code)

    app.add_api_route("/healthz", health, methods=["GET"])
    app.add_api_route("/livez", health, methods=["GET"])
    app.add_api_route("/readyz", ready, methods=["GET"])
    adapter = resolved_live.adapter or ShoppingMallAdapter(
        HttpTransport(HttpxRequester(httpx.Client(trust_env=False)))
    )
    service_key = (
        resolved_live.service_key
        if resolved_live.service_key is not None
        else os.environ.get("G2B_SERVICE_KEY", "")
    )
    app.include_router(build_live_router(adapter, service_key, templates))
    app.include_router(
        build_sync_router(resolved_database.parent if home is None else home, templates)
    )
    return app


app = create_app()
