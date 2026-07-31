"""Build a compact application database without collection-only payloads."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final, override

from g2b_compare.db.migrate import MIGRATION_DIRECTORY
from g2b_compare.db.sql import as_text, query

if TYPE_CHECKING:
    from pathlib import Path

COMPACT_PRODUCTS: Final = """
UPDATE priority_products
SET raw_json = CASE
    WHEN json_valid(raw_json) THEN json_object(
        'pdctAtrbNm', COALESCE(json_extract(raw_json, '$.pdctAtrbNm'), ''),
        'pdctAtrbCdDtlNm',
            COALESCE(json_extract(raw_json, '$.pdctAtrbCdDtlNm'), ''),
        'snymNm', COALESCE(json_extract(raw_json, '$.snymNm'), ''),
        'ctrtItemMngNo',
            COALESCE(json_extract(raw_json, '$.ctrtItemMngNo'), ''),
        'ctrtNo', COALESCE(json_extract(raw_json, '$.ctrtNo'), ''),
        'ctrtChgOrd', COALESCE(json_extract(raw_json, '$.ctrtChgOrd'), '')
    )
    ELSE '{}'
END
"""


@dataclass(frozen=True, slots=True)
class RuntimeDatabaseBuild:
    """Sizes and destination of one compact database build."""

    destination: Path
    source_bytes: int
    runtime_bytes: int


@final
class RuntimeDatabasePathError(Exception):
    """Raised when source and destination resolve to the same file."""

    path: Path

    def __init__(self, path: Path) -> None:
        """Initialize the rejected identical path."""
        super().__init__(path)
        self.path = path

    @override
    def __str__(self) -> str:
        return f"runtime database destination must differ from source: {self.path}"


def build_runtime_database(
    source: Path,
    destination: Path,
) -> RuntimeDatabaseBuild:
    """Copy the live database and retain only JSON fields used by the app."""
    resolved_source = source.resolve()
    resolved_destination = destination.resolve()
    if resolved_source == resolved_destination:
        raise RuntimeDatabasePathError(resolved_source)

    resolved_destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved_destination.with_suffix(
        f"{resolved_destination.suffix}.tmp"
    )
    temporary.unlink(missing_ok=True)

    source_uri = f"{resolved_source.as_uri()}?mode=ro"
    with (
        closing(sqlite3.connect(source_uri, uri=True)) as source_connection,
        closing(sqlite3.connect(temporary)) as destination_connection,
    ):
        source_connection.backup(destination_connection)

    with closing(sqlite3.connect(temporary, isolation_level=None)) as connection:
        _ = connection.execute("BEGIN IMMEDIATE")
        _ = connection.execute(COMPACT_PRODUCTS)
        _ = connection.execute(
            "UPDATE priority_product_offers SET raw_json = '{}'"
        )
        _ = connection.execute(
            "UPDATE priority_company_quarantine SET raw_json = '{}'"
        )
        _ = connection.execute("COMMIT")
        _compact_product_descriptions(connection)
        _ = connection.execute("VACUUM")
        _ = query(connection, "PRAGMA journal_mode = DELETE").fetchone()

    renamed_destination = temporary.replace(resolved_destination)
    return RuntimeDatabaseBuild(
        destination=renamed_destination,
        source_bytes=resolved_source.stat().st_size,
        runtime_bytes=renamed_destination.stat().st_size,
    )


def _compact_product_descriptions(connection: sqlite3.Connection) -> None:
    raw_rows = query(
        connection,
        """
        SELECT DISTINCT response_body_sha256
        FROM priority_product_description_observations
        WHERE response_body_sha256 IS NOT NULL
        """
    ).fetchall()
    body_shas = tuple(as_text(row[0]) for row in raw_rows)
    _ = connection.execute("DROP TABLE priority_product_description_state")
    _ = connection.execute(
        "DROP TABLE priority_product_description_observations"
    )
    for body_sha in body_shas:
        _ = query(
            connection,
            """
            DELETE FROM raw_blobs
            WHERE body_sha = ?
              AND body_sha NOT IN (SELECT body_sha FROM sync_pages)
            """,
            (body_sha,),
        )
    migration = (
        MIGRATION_DIRECTORY / "0006_priority_product_descriptions.sql"
    ).read_text(encoding="utf-8")
    _ = connection.executescript(migration)
