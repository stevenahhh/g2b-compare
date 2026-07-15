"""Immutable media-neutral raw response storage."""

from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
import zlib
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, final, override

from .models import RawBlobReceipt, StagedRawBlob

_STALE_TEMP_CLEANUP_LIMIT: Final = 16


@final
class RawBlobIntegrityError(Exception):
    """Stored compressed bytes do not reproduce their content address."""

    path: Path

    def __init__(self, path: Path) -> None:
        """Initialize the corrupt raw path receipt."""
        super().__init__(path)
        self.path = path

    @override
    def __str__(self) -> str:
        return f"raw blob failed content-address verification: {self.path}"


@dataclass(frozen=True, slots=True)
class RawBlobStore:
    """Two-phase writer for immutable gzip blobs below one raw root."""

    root: Path

    def stage(self, body: bytes, content_type: str) -> StagedRawBlob:
        """Write and fsync a deterministic gzip without making it visible."""
        body_sha = hashlib.sha256(body).hexdigest()
        destination = self.root / "sha256" / body_sha[:2] / f"{body_sha}.bin.gz"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f"{destination.name}.{os.getpid()}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            with gzip.GzipFile(fileobj=handle, mode="wb", mtime=0) as compressed:
                _ = compressed.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        return StagedRawBlob(
            receipt=RawBlobReceipt(
                body_sha=body_sha,
                path=destination,
                content_type=content_type,
                byte_count=len(body),
            ),
            temporary_path=temporary,
        )

    def publish(self, staged: StagedRawBlob) -> RawBlobReceipt:
        """Atomically expose a staged gzip and verify decompressed bytes."""
        receipt = staged.receipt
        if receipt.path.exists():
            staged.temporary_path.unlink(missing_ok=True)
        else:
            try:
                _ = staged.temporary_path.replace(receipt.path)
            except FileNotFoundError:
                if not receipt.path.exists():
                    raise
        self.verify(receipt)
        self._cleanup_stale_temporaries(receipt.path, staged.temporary_path)
        return receipt

    def put(self, body: bytes, content_type: str) -> RawBlobReceipt:
        """Stage, atomically publish, and verify one raw response."""
        return self.publish(self.stage(body, content_type))

    def verify(self, receipt: RawBlobReceipt) -> None:
        """Reject truncated gzip or decompressed SHA/length mismatch."""
        try:
            body = gzip.decompress(receipt.path.read_bytes())
        except (gzip.BadGzipFile, EOFError, zlib.error) as error:
            raise RawBlobIntegrityError(path=receipt.path) from error
        if (
            hashlib.sha256(body).hexdigest() != receipt.body_sha
            or len(body) != receipt.byte_count
        ):
            raise RawBlobIntegrityError(path=receipt.path)

    @staticmethod
    def _cleanup_stale_temporaries(destination: Path, current: Path) -> None:
        pattern = f"{destination.name}.{os.getpid()}.*.tmp"
        stale = (path for path in destination.parent.glob(pattern) if path != current)
        for index, path in enumerate(stale):
            if index >= _STALE_TEMP_CLEANUP_LIMIT:
                break
            with suppress(FileNotFoundError, PermissionError):
                path.unlink()
