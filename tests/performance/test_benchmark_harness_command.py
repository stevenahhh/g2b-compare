"""Pinned Uvicorn benchmark command regression."""

from __future__ import annotations

from tests.performance.benchmark_harness import server_command


def test_server_command_uses_project_uvicorn_and_one_worker() -> None:
    command = server_command("C:/project/python.exe", 39_100)

    assert command[:4] == (
        "C:/project/python.exe",
        "-m",
        "uvicorn",
        "tests.performance.serve_perf_app:app",
    )
    assert command[-4:] == ("--workers", "1", "--log-level", "warning")
