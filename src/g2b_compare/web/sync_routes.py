"""Trigger and report the existing CLI sync pipeline from the web UI."""

from __future__ import annotations

import shutil
import subprocess
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Final, Literal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

    from jinja2 import Environment

STATUS_FILENAME: Final = "manual-sync-status.json"
_STAGES: Final = (
    ("sync", "full"),
    ("import-relations",),
    ("materialize",),
    ("rebuild-index",),
    ("precompute",),
)
_lock = threading.Lock()


class SyncStatus(BaseModel):
    """Persisted manual-sync progress read back by the status page."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    state: Literal["idle", "running", "complete", "failed"] = "idle"
    stage: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


_IDLE_STATUS: Final = SyncStatus()


def build_sync_router(home: Path, templates: Environment) -> APIRouter:
    """Bind the manual-sync status and trigger routes to one local home."""
    router = APIRouter()
    home.mkdir(parents=True, exist_ok=True)
    status_path = home / STATUS_FILENAME

    def get_endpoint(request: Request) -> HTMLResponse:
        template = templates.get_template("sync.html")
        html = template.render(request=request, status=_read_status(status_path))
        return HTMLResponse(html)

    def post_endpoint(request: Request) -> RedirectResponse:
        del request
        _start_background_sync(home, status_path)
        return RedirectResponse("/sync", status_code=303)

    router.add_api_route(
        "/sync", get_endpoint, methods=["GET"], response_class=HTMLResponse
    )
    router.add_api_route(
        "/sync",
        post_endpoint,
        methods=["POST"],
        response_class=RedirectResponse,
        response_model=None,
    )
    return router


def _read_status(status_path: Path) -> SyncStatus:
    if not status_path.is_file():
        return _IDLE_STATUS
    try:
        return SyncStatus.model_validate_json(status_path.read_bytes())
    except ValidationError:
        return _IDLE_STATUS


def _write_status(status_path: Path, status: SyncStatus) -> None:
    _ = status_path.write_text(status.model_dump_json() + "\n", encoding="utf-8")


def _start_background_sync(home: Path, status_path: Path) -> None:
    with _lock:
        if _read_status(status_path).state == "running":
            return
        started_at = datetime.now(UTC).isoformat()
        _write_status(
            status_path,
            SyncStatus(state="running", stage=_STAGES[0][0], started_at=started_at),
        )
    thread = threading.Thread(
        target=_run_pipeline,
        args=(home, status_path, started_at),
        daemon=True,
    )
    thread.start()


def _run_pipeline(home: Path, status_path: Path, started_at: str) -> None:
    executable = shutil.which("g2b-compare") or "g2b-compare"
    for stage in _STAGES:
        completed = subprocess.run(  # noqa: S603
            (executable, "--home", str(home), *stage),
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            _write_status(
                status_path,
                SyncStatus(
                    state="failed",
                    stage=stage[0],
                    started_at=started_at,
                    finished_at=datetime.now(UTC).isoformat(),
                    error=(completed.stderr or completed.stdout or "").strip()[:500],
                ),
            )
            return
    _write_status(
        status_path,
        SyncStatus(
            state="complete",
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
        ),
    )
