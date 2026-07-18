"""Loopback HTTP adapter for the Todo 13 FastAPI application and probes."""

from __future__ import annotations

import errno
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from typing import TYPE_CHECKING, Final, Protocol, override, runtime_checkable

import anyio
import httpx

from g2b_compare.observability.health import Probe, health, readiness

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

    from g2b_compare.contracts.redact import JsonScalar

JSON_TYPE: Final = "application/json"
LOOPBACK: Final = "127.0.0.1"


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
    """Map loopback policy and listener conflicts to stable CLI outcomes."""
    if host != LOOPBACK:
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
        app = module.create_app(database=database, link_manifest=contract)
        server.RequestHandlerClass = handler(app, database, index, contract)
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def handler(
    app: FastAPI,
    database: Path,
    index: Path,
    contract: Path,
) -> type[BaseHTTPRequestHandler]:
    """Build the loopback HTTP handler for UI and readiness traffic."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._send_probe(health(database, index))
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
            response = anyio.run(
                _fetch,
                app,
                self.path,
                {
                    key: value
                    for key, value in self.headers.items()
                    if key.casefold() != "host"
                },
            )
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.casefold() not in {"content-length", "transfer-encoding"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            _ = self.wfile.write(response.content)

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


async def _fetch(
    app: FastAPI,
    path: str,
    headers: dict[str, str],
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
    ) as client:
        return await client.get(path, headers=headers)
