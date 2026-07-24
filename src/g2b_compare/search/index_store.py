"""Persist inactive candidate indices and expose local read-only search."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Final, Self, final

from g2b_compare.db.sql import SqlValue, as_int, as_text, query
from g2b_compare.normalize.text import normalize_text

from .capabilities import fts5_available, require_fts5
from .index_format import IndexFormatError, validate_bundle
from .query import (
    ExactMatchGroup,
    IndexMembershipError,
    ScoreHit,
    SearchProduct,
    resolve_exact,
    score_members,
)
from .store_guards import materialization_is_active

if TYPE_CHECKING:
    from .index_builder import IndexBuildRequest, IndexBundle

ACTIVE_MATERIALIZATION: Final = "active-materialization"
EMPTY_DATABASE: Final = "empty-db"
HASH_FRAMING: Final = "hash-framing"
BUNDLE_OWNERSHIP_MISMATCH: Final = "bundle-ownership-mismatch"


@final
class IndexStore:
    """Own candidate index publication and read-only local query operations."""

    __slots__ = ("_baseline_changes", "_connection", "_materialization_id")

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Take ownership of one initialized SQLite connection."""
        self._connection = connection
        self._baseline_changes = connection.total_changes
        self._materialization_id: int | None = None

    @staticmethod
    def fts5_available() -> bool:
        """Return whether the runtime was compiled with ENABLE_FTS5."""
        return fts5_available()

    @classmethod
    def create(cls, path: Path) -> Self:
        """Initialize the local schema only after the mandatory FTS5 check."""
        require_fts5(available=cls.fts5_available())
        connection = sqlite3.connect(path, isolation_level=None)
        _ = query(connection, "PRAGMA foreign_keys = ON")
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        _ = connection.executescript(schema)
        return cls(connection)

    @property
    def total_changes(self) -> int:
        """Expose query-side changes since the most recent publication."""
        return self._connection.total_changes - self._baseline_changes

    @property
    def query_only_enabled(self) -> bool:
        """Return whether SQLite currently rejects every write statement."""
        row = query(self._connection, "PRAGMA query_only").fetchone()
        return row == (1,)

    def enforce_query_only(self) -> None:
        """Switch the owned connection to SQLite-enforced read-only queries."""
        _ = query(self._connection, "PRAGMA query_only = ON")

    def publish(self, request: IndexBuildRequest, bundle: IndexBundle) -> None:
        """Atomically attach one complete index to an inactive materialization."""
        validated = validate_bundle(bundle.members, bundle.manifest)
        active_ids = tuple(
            item.product_id
            for item in sorted(
                (product for product in request.products if product.active),
                key=lambda product: product.product_id.encode("utf-8"),
            )
        )
        if validated.product_ids != active_ids:
            raise IndexFormatError(HASH_FRAMING)
        request_identity = (
            request.materialization_id,
            request.normalization_version,
            request.tokenizer_version,
            request.index_version,
        )
        bundle_identity = (
            validated.identity.materialization_id,
            validated.identity.normalization_version,
            validated.identity.tokenizer_version,
            validated.identity.index_version,
        )
        if request_identity != bundle_identity:
            raise IndexFormatError(BUNDLE_OWNERSHIP_MISMATCH)
        if materialization_is_active(self._connection, request.materialization_id):
            raise IndexFormatError(ACTIVE_MATERIALIZATION)
        connection = self._connection
        _ = query(connection, "BEGIN IMMEDIATE")
        try:
            _ = query(
                connection,
                """
                INSERT INTO index_versions(
                    materialization_id, index_artifact_sha, index_manifest_sha,
                    status, created_at
                ) VALUES (?, ?, ?, 'building', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (
                    request.materialization_id,
                    bundle.artifact_sha256,
                    bundle.manifest_sha256,
                ),
            )
            self._write_rows(request)
            self._write_members(request.materialization_id, bundle)
            _ = query(
                connection,
                """
                UPDATE index_versions SET status = 'complete'
                WHERE materialization_id = ? AND index_artifact_sha = ?
                  AND index_manifest_sha = ?
                """,
                (
                    request.materialization_id,
                    bundle.artifact_sha256,
                    bundle.manifest_sha256,
                ),
            )
            _ = query(connection, "COMMIT")
        except sqlite3.DatabaseError:
            _ = query(connection, "ROLLBACK")
            raise
        self._materialization_id = request.materialization_id
        self._baseline_changes = connection.total_changes

    def resolve_exact(
        self, raw_name: str, category_key: tuple[str, str] | None = None
    ) -> tuple[ExactMatchGroup, ...]:
        """Return exact-name groups from B-tree membership only."""
        materialization_id = self._require_index()
        return resolve_exact(
            self._connection,
            materialization_id,
            raw_name,
            category_key,
        )

    def recall(self, raw_query: str) -> tuple[SearchProduct, ...]:
        """Use FTS5 only for autocomplete and lexical recall."""
        materialization_id = self._require_index()
        tokens = normalize_text(raw_query).tokens
        if not tokens:
            return ()
        expression = " AND ".join(
            f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens
        )
        rows = query(
            self._connection,
            """
            SELECT membership.product_id, membership.category_no,
                   membership.detail_category_no, membership.product_name_raw,
                   membership.product_name_key
            FROM search_fts
            JOIN search_membership AS membership
              ON membership.materialization_id = search_fts.materialization_id
             AND membership.product_id = search_fts.product_id
            WHERE search_fts MATCH ? AND membership.materialization_id = ?
              AND membership.active = 1
            ORDER BY membership.product_id
            """,
            (expression, materialization_id),
        ).fetchall()
        return tuple(
            SearchProduct(
                as_text(row[0]),
                (as_text(row[1]), as_text(row[2])),
                as_text(row[3]),
                as_text(row[4]),
            )
            for row in rows
        )

    def score(self, raw_query: str) -> tuple[ScoreHit, ...]:
        """Score global active rows without changing exact membership."""
        materialization_id = self._require_index()
        rows = query(
            self._connection,
            """
            SELECT member_name, member_bytes FROM search_index_members
            WHERE materialization_id = ? ORDER BY member_name
            """,
            (materialization_id,),
        ).fetchall()
        members = {as_text(name): _as_bytes(value) for name, value in rows}
        return score_members(members, raw_query)

    def close(self) -> None:
        """Release the owned SQLite connection."""
        self._connection.close()

    def _require_index(self) -> int:
        if self._materialization_id is None:
            row = query(
                self._connection,
                """
                SELECT materialization_id FROM index_versions
                WHERE status = 'complete' ORDER BY id DESC LIMIT 1
                """,
            ).fetchone()
            if row is None:
                raise IndexMembershipError(EMPTY_DATABASE)
            self._materialization_id = as_int(row[0])
        return self._materialization_id

    def _write_rows(self, request: IndexBuildRequest) -> None:
        for product in request.products:
            _ = query(
                self._connection,
                """
                INSERT INTO search_membership VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.materialization_id,
                    product.product_id,
                    product.category_key[0],
                    product.category_key[1],
                    product.product_name_raw,
                    product.product_name_key,
                    product.option_text,
                    int(product.active),
                ),
            )
            if product.active:
                _ = query(
                    self._connection,
                    "INSERT INTO search_fts VALUES (?, ?, ?, ?)",
                    (
                        request.materialization_id,
                        product.product_id,
                        product.product_name_key,
                        product.product_name_raw,
                    ),
                )

    def _write_members(self, materialization_id: int, bundle: IndexBundle) -> None:
        for name, value in bundle.members:
            _ = query(
                self._connection,
                "INSERT INTO search_index_members VALUES (?, ?, ?)",
                (materialization_id, name, value),
            )


def _as_bytes(value: SqlValue) -> bytes:
    if isinstance(value, bytes):
        return value
    raise IndexFormatError(HASH_FRAMING)
