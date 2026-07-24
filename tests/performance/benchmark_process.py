"""Manage the owned Uvicorn process and loopback port lifecycle."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Final, override

import httpx

UVICORN_EARLY_EXIT: Final = "uvicorn exited before ready"
UVICORN_TIMEOUT: Final = "uvicorn readiness timeout"
NO_FREE_PORT: Final = "no free loopback benchmark port"
LISTENER_REMAINED: Final = "uvicorn listener remained after cleanup"


@dataclass(frozen=True, slots=True)
class ServerProcessError(Exception):
    """Report a live server lifecycle contract failure."""

    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def free_port() -> int:
    """Reserve the first currently free port in the benchmark range."""
    for port in range(39_100, 40_000):
        with closing(socket.socket()) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise ServerProcessError(NO_FREE_PORT)


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    """Terminate the exact owned process tree and wait for completion."""
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if taskkill is None:
            process.kill()
            _ = process.wait(timeout=10)
            return
        _ = subprocess.run(  # noqa: S603 -- exact PID from owned Popen
            (taskkill, "/PID", str(process.pid), "/T", "/F"),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _ = process.wait(timeout=10)
        return
    process.terminate()
    try:
        _ = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        _ = process.wait(timeout=10)


def wait_ready(base: str, process: subprocess.Popen[bytes]) -> None:
    """Wait until the owned loopback server returns HTTP 200."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ServerProcessError(UVICORN_EARLY_EXIT)
        try:
            response = httpx.get(base, timeout=0.5)
        except httpx.HTTPError:
            time.sleep(0.02)
            continue
        if response.status_code == 200:
            return
    raise ServerProcessError(UVICORN_TIMEOUT)


def wait_port_release(port: int) -> None:
    """Verify that cleanup released the selected loopback port."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with closing(socket.socket()) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                time.sleep(0.02)
                continue
            return
    raise ServerProcessError(LISTENER_REMAINED)
