from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING, cast

import httpx
from fastapi import FastAPI
from pydantic import TypeAdapter

from g2b_compare.observability.server import handler

if TYPE_CHECKING:
    from pathlib import Path

JSON_DOCUMENT = TypeAdapter(dict[str, str | bool])


def test_liveness_is_available_before_data_is_ready(tmp_path: Path) -> None:
    # Given: an HTTP server whose database, index, and release are not ready.
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        handler(
            FastAPI(),
            tmp_path / "g2b.sqlite3",
            tmp_path / "search-index.bin",
            tmp_path / "docs" / "api-contract-observed.json",
        ),
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    host, port = cast("tuple[str, int]", server.server_address)

    try:
        # When: the launcher probes process liveness.
        response = httpx.get(f"http://{host}:{port}/livez")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # Then: process liveness succeeds independently from data readiness.
    assert response.status_code == 200
    assert JSON_DOCUMENT.validate_json(response.content) == {
        "ok": True,
        "process": "ok",
        "status": "alive",
    }


def test_mutating_request_is_forwarded_to_fastapi(tmp_path: Path) -> None:
    # Given: the production HTTP adapter fronts a FastAPI PUT endpoint.
    app = FastAPI()

    def put_document(payload: dict[str, str]) -> dict[str, str]:
        return payload

    app.add_api_route("/document", put_document, methods=["PUT"])
    def fail_document() -> None:
        raise RuntimeError

    app.add_api_route("/failure", fail_document, methods=["PUT"])

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        handler(
            app,
            tmp_path / "g2b.sqlite3",
            tmp_path / "search-index.bin",
            tmp_path / "docs" / "api-contract-observed.json",
        ),
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    host, port = cast("tuple[str, int]", server.server_address)

    try:
        # When: the browser saves a document through the adapter.
        response = httpx.put(
            f"http://{host}:{port}/document",
            json={"title": "관급내역"},
        )
        failed_response = httpx.put(f"http://{host}:{port}/failure")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # Then: PUT reaches FastAPI instead of BaseHTTPRequestHandler's 501 response.
    assert response.status_code == 200
    assert response.json() == {"title": "관급내역"}
    assert failed_response.status_code == 500
