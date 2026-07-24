"""Production Uvicorn runtime dependency regression."""

from __future__ import annotations

import uvicorn


def test_project_environment_provides_uvicorn_runtime() -> None:
    assert uvicorn.__version__
