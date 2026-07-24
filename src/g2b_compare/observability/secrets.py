"""Fail-closed streaming secret verification for source and runtime storage."""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, final, override

from g2b_compare.db.connection import connect_read_only
from g2b_compare.db.sql import as_int, as_text, query

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

CANARY: Final = b"G2B_TEST_" + b"SECRET_CANARY"
CHUNK_SIZE: Final = 64 * 1024
SHA256_HEX_LENGTH: Final = 64
SQLITE_HEADER: Final = b"SQLite format 3\x00"
GIT_UNAVAILABLE: Final = "git-unavailable"
GIT_FAILED: Final = "git-ls-files-failed"
STORAGE_ENUMERATION_FAILED: Final = "storage-enumeration-failed"
STORAGE_READ_FAILED: Final = "storage-read-failed"
STORAGE_CHANGED: Final = "storage-changed-during-scan"
SQLITE_SCAN_FAILED: Final = "sqlite-scan-failed"


class ReadStream(Protocol):
    """Minimal binary stream capability used by the scanner."""

    def read(self, size: int = -1, /) -> bytes:
        """Read at most size bytes."""
        ...


@dataclass(frozen=True, slots=True)
class SecretLeak:
    """One sanitized leak location."""

    path: Path
    marker: str


@final
class SecretScanError(Exception):
    """Stable fail-closed scan failure."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Initialize a stable sanitized failure."""
        super().__init__(reason)
        self.reason = reason

    @override
    def __str__(self) -> str:
        return self.reason


def secret_markers(secret: str | None, canary: bytes = CANARY) -> tuple[bytes, ...]:
    """Return the runtime value, digest, and deterministic test canary."""
    markers = [canary]
    if secret:
        raw = secret.encode()
        markers.extend((raw, hashlib.sha256(raw).hexdigest().encode()))
    return tuple(markers)


def scan_stream(stream: ReadStream, markers: tuple[bytes, ...]) -> str | None:
    """Scan a stream while retaining only cross-chunk overlap."""
    return _scan_chunks(iter(lambda: stream.read(CHUNK_SIZE), b""), markers)


def tracked_files(root: Path) -> tuple[Path, ...]:
    """Enumerate Git-tracked paths without shell interpolation."""
    executable = shutil.which("git")
    if executable is None:
        raise SecretScanError(GIT_UNAVAILABLE)
    result = subprocess.run(  # noqa: S603
        (executable, "-C", str(root), "ls-files", "-z"),
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise SecretScanError(GIT_FAILED)
    return tuple(
        root / name.decode("utf-8", errors="surrogateescape")
        for name in result.stdout.split(b"\0")
        if name
    )


def runtime_files(root: Path) -> tuple[Path, ...]:
    """Recursively enumerate runtime regular files and fail on any I/O error."""
    found: list[Path] = []
    pending = [root]
    try:
        while pending:
            current = pending.pop()
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        found.append(Path(entry.path))
    except OSError:
        raise SecretScanError(STORAGE_ENUMERATION_FAILED) from None
    return tuple(found)


def verify_secrets(
    root: Path,
    *,
    secret: str | None = None,
    paths: tuple[Path, ...] = (),
    runtime_root: Path | None = None,
    all_storage: bool = False,
) -> tuple[SecretLeak, ...]:
    """Scan tracked files and optionally every recursively discovered runtime file."""
    markers = secret_markers(secret)
    runtime = runtime_files(runtime_root) if all_storage and runtime_root else ()
    candidates = dict.fromkeys((*tracked_files(root), *runtime, *paths))
    leaks: list[SecretLeak] = []
    for path in candidates:
        try:
            _ = path.stat()
        except FileNotFoundError:
            continue
        except OSError:
            raise SecretScanError(STORAGE_READ_FAILED) from None
        marker, is_sqlite = _scan_file(path, markers)
        if marker is not None:
            leaks.append(SecretLeak(path, marker))
            continue
        if is_sqlite and (sqlite_marker := _scan_sqlite(path, markers)) is not None:
            leaks.append(SecretLeak(path, sqlite_marker))
    return tuple(leaks)


def _scan_file(
    path: Path,
    markers: tuple[bytes, ...],
) -> tuple[str | None, bool]:
    try:
        before = path.stat()
        with path.open("rb") as raw:
            header = raw.read(len(SQLITE_HEADER))
        opener = gzip.open if path.suffix.casefold() == ".gz" else Path.open
        with opener(path, "rb") as stream:
            marker = scan_stream(stream, markers)
        after = path.stat()
    except (OSError, EOFError):
        raise SecretScanError(STORAGE_READ_FAILED) from None
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        raise SecretScanError(STORAGE_CHANGED)
    return marker, header == SQLITE_HEADER


def _scan_sqlite(path: Path, markers: tuple[bytes, ...]) -> str | None:
    try:
        with connect_read_only(path) as connection:
            _ = connection.execute("BEGIN")
            tables = query(
                connection,
                """SELECT name FROM sqlite_schema
                   WHERE type='table' AND name NOT LIKE 'sqlite_%'
                   ORDER BY name""",
            ).fetchall()
            for table_row in tables:
                table = as_text(table_row[0])
                columns = query(
                    connection, f"PRAGMA table_info({_quote(table)})"
                ).fetchall()
                for column in (as_text(row[1]) for row in columns):
                    marker = _scan_sqlite_column(connection, table, column, markers)
                    if marker is not None:
                        return marker
            _ = connection.execute("COMMIT")
    except (OSError, sqlite3.DatabaseError):
        raise SecretScanError(SQLITE_SCAN_FAILED) from None
    return None


def _scan_sqlite_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    markers: tuple[bytes, ...],
) -> str | None:
    rows = query(
        connection,
        f"""SELECT rowid,typeof({_quote(column)})
            FROM {_quote(table)}
            WHERE typeof({_quote(column)}) IN ('text','blob')""",  # noqa: S608
    )
    for rowid, storage_type in rows.fetchall():
        concrete_rowid = as_int(rowid)
        if as_text(storage_type) == "blob":
            with connection.blobopen(
                table,
                column,
                concrete_rowid,
                readonly=True,
            ) as blob:
                marker = scan_stream(blob, markers)
        else:
            marker = _scan_chunks(
                _text_chunks(connection, table, column, concrete_rowid),
                markers,
            )
        if marker is not None:
            return marker
    return None


def _text_chunks(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    rowid: int,
) -> Iterator[bytes]:
    offset = 1
    while True:
        row = query(
            connection,
            f"""SELECT CAST(substr({_quote(column)}, ?, ?) AS BLOB)
                FROM {_quote(table)} WHERE rowid=?""",  # noqa: S608
            (offset, CHUNK_SIZE, rowid),
        ).fetchone()
        value = None if row is None else row[0]
        if value is None:
            chunk = b""
        elif isinstance(value, bytes):
            chunk = value
        else:
            raise SecretScanError(SQLITE_SCAN_FAILED)
        if not chunk:
            return
        yield chunk
        offset += CHUNK_SIZE


def _scan_chunks(
    chunks: Iterable[bytes],
    markers: tuple[bytes, ...],
) -> str | None:
    overlap = max((len(item) for item in markers), default=1) - 1
    tail = b""
    for chunk in chunks:
        data = tail + chunk
        for marker in markers:
            if marker and marker in data:
                return "key-sha256" if len(marker) == SHA256_HEX_LENGTH else "secret"
        tail = data[-overlap:] if overlap else b""
    return None


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
