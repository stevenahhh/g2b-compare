"""Configure the local-only FastAPI application."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .links import load_product_links
from .routes import build_router
from .sqlite_reader import WebSqliteSearchReader

if TYPE_CHECKING:
    from g2b_compare.services.search_models import SearchReader

DEFAULT_LINK_MANIFEST: Final = Path("docs/api-contract-observed.json")


def create_app(
    reader: SearchReader | None = None,
    *,
    database: Path | None = None,
    link_manifest: Path | None = None,
) -> FastAPI:
    """Create an application with an injectable read-only search reader."""
    root = Path(__file__).parent
    app = FastAPI(title="나라장터 유사물품 비교")
    selected_reader = reader or WebSqliteSearchReader(
        Path("data/g2b-compare.sqlite3") if database is None else database
    )
    templates = Environment(
        loader=FileSystemLoader(root / "templates"),
        autoescape=select_autoescape(("html", "xml")),
    )
    app.mount("/static", StaticFiles(directory=root / "static"), name="static")
    app.include_router(
        build_router(
            selected_reader,
            templates,
            load_product_links(link_manifest or DEFAULT_LINK_MANIFEST),
        )
    )
    return app


app = create_app()
