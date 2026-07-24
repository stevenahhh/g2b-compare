from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from g2b_compare.cli import main, parser

if TYPE_CHECKING:
    import pytest

RECEIPT = TypeAdapter(dict[str, str])


def test_all_commands_expose_help() -> None:
    help_text = parser().format_help()
    commands = {
        "init-db",
        "capture-contract",
        "sync",
        "import-relations",
        "rebuild-index",
        "precompute",
        "verify",
        "verify-secrets",
        "prune-raw",
        "serve",
    }
    assert all(command in help_text for command in commands)


def test_init_db_and_dry_run(tmp_path: Path) -> None:
    assert main(("--home", str(tmp_path), "init-db")) == 0
    assert (tmp_path / "g2b.sqlite3").is_file()
    assert main(("--home", str(tmp_path), "sync", "full", "--dry-run")) == 0


def test_import_relations_creates_empty_snapshot_without_workbook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an initialized runtime without a curated relation workbook.
    assert main(("--home", str(tmp_path), "init-db")) == 0
    monkeypatch.delenv("G2B_RELATIONS_WORKBOOK", raising=False)

    # When: the optional relation import stage runs.
    status = main(("--home", str(tmp_path), "import-relations"))

    # Then: release preparation has a complete empty relation snapshot.
    assert status == 0
    with sqlite3.connect(tmp_path / "g2b.sqlite3") as connection:
        assert connection.execute(
            "SELECT status FROM relation_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone() == ("complete",)
        assert connection.execute(
            "SELECT count(*) FROM curated_relations"
        ).fetchone() == (0,)


def test_public_bind_fails_closed() -> None:
    public_host = "0.0.0.0"  # noqa: S104
    assert main(("serve", "--host", public_host)) == 2


def test_quota_ceiling_returns_resume_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: one operation has consumed its observed rolling quota.
    assert main(("--home", str(tmp_path), "init-db")) == 0
    _ = capsys.readouterr()
    contract = tmp_path / "docs" / "api-contract-observed.json"
    contract.parent.mkdir()
    _ = contract.write_bytes(Path("docs/api-contract-observed.json").read_bytes())
    attempted_at = datetime.now(UTC)
    with sqlite3.connect(tmp_path / "g2b.sqlite3") as connection:
        _ = connection.executemany(
            """INSERT INTO api_call_ledger(
               operation,attempted_at_utc,kst_date,status_code,reservation_state
               ) VALUES(?,?,?,?,?)""",
            (
                (
                    "getMASCntrctPrdctInfoList",
                    attempted_at.isoformat(),
                    attempted_at.date().isoformat(),
                    200,
                    "succeeded",
                )
                for _index in range(1000)
            ),
        )
    monkeypatch.setenv("G2B_SERVICE_KEY", "fixture-key")

    # When: full sync tries to reserve the next provider call.
    status = main(("--home", str(tmp_path), "sync", "full"))

    # Then: the CLI reports a sanitized retry time without a traceback.
    assert status == 2
    receipt = RECEIPT.validate_json(capsys.readouterr().err)
    assert receipt == {
        "error": "quota-ceiling-exhausted",
        "operation": "getMASCntrctPrdctInfoList",
        "resume_not_before": (attempted_at + timedelta(hours=24)).isoformat(),
        "status": "blocked",
    }
