# ruff: noqa: INP001, C901, PLR0911, D103
"""Provision the local runtime and launch a LAN-accessible server.

Data sync is no longer automatic here: the primary search experience calls
the G2B API live and needs no local snapshot. Use the web UI's "데이터
동기화" page to run the batch sync pipeline manually when you want one.
"""

from __future__ import annotations

import argparse
import http.client
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from http import HTTPStatus
from pathlib import Path
from typing import Final

_PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
_BIND_HOST: Final = "0.0.0.0"  # noqa: S104 - LAN sharing is intentional.
_LOOPBACK_HOST: Final = "127.0.0.1"
_PORT: Final = 8765
_POLL_ATTEMPTS: Final = 50
_POLL_DELAY_SECONDS: Final = 0.1


class _Options(argparse.Namespace):
    home: str = ".g2b"
    provision_only: bool = False
    no_browser: bool = False


def _environment(project_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    if environment.get("G2B_SERVICE_KEY", "").strip():
        return environment
    dotenv = project_root / ".env"
    if not dotenv.is_file():
        return environment
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        if not line.startswith("G2B_SERVICE_KEY="):
            continue
        service_key = line[len("G2B_SERVICE_KEY=") :]
        if len(service_key) > 1 and service_key[:1] + service_key[-1:] in {"''", '""'}:
            service_key = service_key[1:-1]
        if service_key.strip():
            environment["G2B_SERVICE_KEY"] = service_key
        return environment
    return environment


def _is_live() -> bool:
    connection = http.client.HTTPConnection(
        _LOOPBACK_HOST, _PORT, timeout=_POLL_DELAY_SECONDS
    )
    try:
        connection.request("GET", "/livez")
        response = connection.getresponse()
        _ = response.read()
    except (http.client.HTTPException, OSError):
        return False
    else:
        return response.status == HTTPStatus.OK
    finally:
        connection.close()


def _report(code: str) -> None:
    _ = sys.stderr.write(f"{code}\n")


def main(arguments: list[str] | None = None) -> int:
    try:
        parser = argparse.ArgumentParser()
        _ = parser.add_argument("--home", default=".g2b")
        _ = parser.add_argument("--provision-only", action="store_true")
        _ = parser.add_argument("--no-browser", action="store_true")
        options = _Options()
        _ = parser.parse_args(sys.argv[1:] if arguments is None else arguments, options)
        environment = _environment(_PROJECT_ROOT)
        home = Path(options.home)
        executable = shutil.which("g2b-compare", path=environment.get("PATH"))

        def run(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            command_line = (executable or "g2b-compare", "--home", str(home), *command)
            try:
                return subprocess.run(  # noqa: S603
                    command_line,
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
            except OSError:
                return subprocess.CompletedProcess(command_line, 1, "", "")

        def checked(command: tuple[str, ...], failure_code: str) -> bool:
            if run(command).returncode == 0:
                return True
            _report(failure_code)
            return False

        if not checked(("init-db",), "migration-failed"):
            return 1
        if not checked(
            ("verify-secrets", "--all-storage"), "secret-verification-failed"
        ):
            return 1
        if options.provision_only:
            return 0
        command_line = (
            executable or "g2b-compare",
            "--home",
            str(home),
            "serve",
            "--host",
            _BIND_HOST,
            "--port",
            str(_PORT),
        )
        try:
            server = subprocess.Popen(  # noqa: S603
                command_line,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                env=environment,
            )
        except OSError:
            _report("server-start-failed")
            return 1
        try:
            live = False
            for _ in range(_POLL_ATTEMPTS):
                if server.poll() is not None:
                    break
                if _is_live():
                    live = True
                    break
                time.sleep(_POLL_DELAY_SECONDS)
            if not live:
                _report(
                    "server-stopped-before-ready"
                    if server.poll() is not None
                    else "server-start-timeout"
                )
                return 1
            _report(f"server-ready:http://{_LOOPBACK_HOST}:{_PORT}/")
            _report(f"lan-url:http://{socket.gethostname()}:{_PORT}/")
            if not options.no_browser:
                _ = webbrowser.open(f"http://{_LOOPBACK_HOST}:{_PORT}/")
            _ = server.wait()
            return 0
        finally:
            if server.poll() is None:
                server.terminate()
                _ = server.wait()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
