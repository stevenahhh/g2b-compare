"""Loopback HTTP adapter for the Todo 13 FastAPI application and probes."""

from __future__ import annotations

import errno
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from queue import Empty
from typing import TYPE_CHECKING, Final, Protocol, cast, override, runtime_checkable

import anyio
import httpx

from g2b_compare.observability.health import Probe, readiness
from g2b_compare.web.estimate_events import ESTIMATE_EVENTS

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

    from g2b_compare.contracts.redact import JsonScalar

JSON_TYPE: Final = "application/json"
LOOPBACK: Final = "127.0.0.1"
LAN_BIND: Final = "0.0.0.0"  # noqa: S104 - LAN sharing is intentional.


@runtime_checkable
class _AppModule(Protocol):
    def create_app(
        self,
        *,
        database: Path,
        link_manifest: Path,
    ) -> FastAPI: ...


class _AppContractError(TypeError):
    pass


def serve_loopback(
    database: Path,
    index: Path,
    contract: Path,
    host: str,
    port: int,
) -> tuple[int, str | None]:
    """Map approved local binds and listener conflicts to stable CLI outcomes."""
    if host not in {LOOPBACK, LAN_BIND}:
        return 2, "public-bind-refused"
    try:
        return run_server(database, index, contract, host, port), None
    except OSError as error:
        windows_error = getattr(error, "winerror", None)
        if error.errno == errno.EADDRINUSE or windows_error in {10013, 10048}:
            return 2, "port-occupied"
        raise


def run_server(
    database: Path,
    index: Path,
    contract: Path,
    host: str,
    port: int,
) -> int:
    """Serve the read-only UI and readiness probes until interrupted."""
    server = ThreadingHTTPServer((host, port), BaseHTTPRequestHandler)
    try:
        module = import_module("g2b_compare.web.app")
        if not isinstance(module, _AppModule):
            raise _AppContractError
        previous_spa_mode = os.environ.get("G2B_SERVE_SPA")
        os.environ["G2B_SERVE_SPA"] = "1"
        try:
            app = module.create_app(database=database, link_manifest=contract)
        finally:
            if previous_spa_mode is None:
                _ = os.environ.pop("G2B_SERVE_SPA", None)
            else:
                os.environ["G2B_SERVE_SPA"] = previous_spa_mode
        server.RequestHandlerClass = handler(app, database, index, contract)
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def handler(  # noqa: C901 - handler factory owns HTTP verbs
    app: FastAPI,
    database: Path,
    index: Path,
    contract: Path,
) -> type[BaseHTTPRequestHandler]:
    """Build the loopback HTTP handler for UI and readiness traffic."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/api/estimates/events":
                self._send_estimate_events()
                return
            if self.path in {"/livez", "/healthz"}:
                self._send_probe(
                    Probe(ok=True, status="alive", detail={"process": "ok"})
                )
                return
            if self.path == "/readyz" and _priority_ready(database):
                self._send_probe(
                    Probe(
                        ok=True,
                        status="ready-priority-catalog",
                        detail={"database": "ok", "priority_catalog": "ok"},
                    )
                )
                return
            if self.path in {"/readyz", "/data-status"}:
                self._send_probe(
                    readiness(
                        database,
                        root=contract.parent.parent,
                        index_path=index,
                        contract_path=contract,
                    )
                )
                return
            self._proxy("GET")

        def do_POST(self) -> None:
            self._proxy("POST")

        def do_PUT(self) -> None:
            self._proxy("PUT")

        def do_PATCH(self) -> None:
            self._proxy("PATCH")

        def do_DELETE(self) -> None:
            self._proxy("DELETE")

        def do_OPTIONS(self) -> None:
            self._proxy("OPTIONS")

        def _proxy(self, method: str) -> None:
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length) if length else b""
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.casefold() != "host"
            }
            response = anyio.run(_fetch, app, self.path, headers, method, body)
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.casefold() not in {"content-length", "transfer-encoding"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            _ = self.wfile.write(response.content)

        def _send_estimate_events(self) -> None:
            subscriber = ESTIMATE_EVENTS.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                _ = self.wfile.write(b"event: ready\ndata: {}\n\n")
                self.wfile.flush()
                while True:
                    try:
                        payload = subscriber.get(timeout=15).as_sse().encode()
                    except Empty:
                        payload = b": keep-alive\n\n"
                    _ = self.wfile.write(payload)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return
            finally:
                ESTIMATE_EVENTS.unsubscribe(subscriber)

        def _send_probe(self, probe: Probe) -> None:
            body = json.dumps(
                {"ok": probe.ok, "status": probe.status, **probe.detail},
                sort_keys=True,
            ).encode()
            self.send_response(200 if probe.ok else 503)
            self.send_header("Content-Type", JSON_TYPE)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _ = self.wfile.write(body)

        @override
        def log_message(self, format: str, *args: JsonScalar) -> None:
            _ = (format, args)

    return Handler


def _priority_ready(database: Path) -> bool:
    try:
        with sqlite3.connect(database) as connection:
            row = cast(
                "tuple[int] | None",
                connection.execute("SELECT COUNT(*) FROM priority_products").fetchone(),
            )
    except sqlite3.Error:
        return False
    return row is not None and int(row[0]) > 0


async def _fetch(
    app: FastAPI,
    path: str,
    headers: dict[str, str],
    method: str = "GET",
    body: bytes = b"",
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
    ) as client:
        return await client.request(method, path, headers=headers, content=body)
