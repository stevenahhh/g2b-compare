"""Append-only persistence for observed G2B product descriptions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final, final

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import as_int, as_text, query
from g2b_compare.priority_store import PriorityStore

from .priority_description import (
    PARSER_VERSION,
    ProductDetailObservation,
    ProductDetailTarget,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from g2b_compare.db.models import RawBlobReceipt

ERROR_CODE_PATTERN: Final = re.compile(r"[a-z0-9_]{1,64}")
SHA256_HEX_LENGTH: Final = 64


@final
class ProductDescriptionStoreError(Exception):
    """An internal append-only store invariant was not satisfied."""


@final
class ProductDescriptionStore:
    """Own immutable observations and one atomic latest pointer per product."""

    def __init__(self, database: Path) -> None:
        """Open description persistence over one migrated priority database."""
        self.database = database
        _ = PriorityStore(database)

    def pending_targets(
        self,
        *,
        retry_missing: bool = False,
        force: bool = False,
        limit: int | None = None,
    ) -> tuple[ProductDetailTarget, ...]:
        """Return targets eligible under deterministic resume semantics."""
        if limit is not None and limit <= 0:
            raise ValueError(limit)
        with connect(self.database) as connection:
            rows = query(
                connection,
                """
                SELECT product.product_id, product.detail_url,
                observation.contract_item_management_number,
                observation.page_url, observation.outcome
                FROM priority_products AS product
                LEFT JOIN priority_product_description_state AS state
                ON state.product_id = product.product_id
                LEFT JOIN priority_product_description_observations AS observation
                ON observation.id = state.latest_observation_id
                ORDER BY product.product_id
                """,
            ).fetchall()
        result: list[ProductDetailTarget] = []
        for row in rows:
            target = ProductDetailTarget.from_product(
                as_text(row[0]),
                as_text(row[1]),
            )
            latest_matches = (
                row[2] is not None
                and as_text(row[2]) == target.contract_item_management_number
                and as_text(row[3]) == target.source_url
            )
            outcome = None if row[4] is None else as_text(row[4])
            if (
                force
                or not latest_matches
                or outcome == "failed"
                or (retry_missing and outcome == "missing")
            ):
                result.append(target)
                if limit is not None and len(result) == limit:
                    break
        return tuple(result)

    def record(self, observation: ProductDetailObservation) -> int:
        """Append one observation and atomically advance its product pointer."""
        _validate_observation(observation)
        with connect(self.database) as connection:
            _ = connection.execute("BEGIN IMMEDIATE")
            if observation.response_receipt is not None:
                _insert_raw_blob(
                    connection,
                    observation.response_receipt,
                    observation.observed_at,
                )
            content = observation.content
            cursor = query(
                connection,
                """
                INSERT INTO priority_product_description_observations
                (product_id, contract_item_management_number, page_url,
                endpoint_url, request_fingerprint, response_body_sha256,
                outcome, detail_html_sha256, decoded_html, detail_text,
                parser_version, http_status, error_code, observed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.target.product_id,
                    observation.target.contract_item_management_number,
                    observation.target.source_url,
                    observation.endpoint_url,
                    observation.request_fingerprint,
                    (
                        None
                        if observation.response_receipt is None
                        else observation.response_receipt.body_sha
                    ),
                    observation.outcome,
                    None if content is None else content.detail_html_sha256,
                    None if content is None else content.decoded_html,
                    None if content is None else content.detail_text,
                    PARSER_VERSION if content is None else content.parser_version,
                    observation.http_status,
                    observation.error_code,
                    observation.observed_at,
                ),
            )
            observation_id = cursor.lastrowid
            if observation_id is None:
                raise ProductDescriptionStoreError
            _ = query(
                connection,
                """
                INSERT INTO priority_product_description_state
                (product_id, latest_observation_id) VALUES (?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                latest_observation_id = excluded.latest_observation_id
                """,
                (observation.target.product_id, observation_id),
            )
            _ = connection.commit()
        return observation_id

    def outcome_counts(self) -> dict[str, int]:
        """Count latest current-state outcomes for reconciliation."""
        with connect(self.database) as connection:
            rows = query(
                connection,
                """
                SELECT observation.outcome, COUNT(*)
                FROM priority_product_description_state AS state
                JOIN priority_product_description_observations AS observation
                ON observation.id = state.latest_observation_id
                GROUP BY observation.outcome ORDER BY observation.outcome
                """,
            ).fetchall()
        return {as_text(row[0]): as_int(row[1]) for row in rows}


def _validate_observation(observation: ProductDetailObservation) -> None:
    content = observation.content
    receipt = observation.response_receipt
    if len(observation.request_fingerprint) != SHA256_HEX_LENGTH:
        raise ValueError(observation.request_fingerprint)
    if observation.outcome == "stored":
        if receipt is None or content is None or observation.error_code is not None:
            raise ValueError(observation.outcome)
    elif observation.outcome == "missing":
        if receipt is None or content is not None or observation.error_code is not None:
            raise ValueError(observation.outcome)
    elif (
        content is not None
        or observation.error_code is None
        or ERROR_CODE_PATTERN.fullmatch(observation.error_code) is None
    ):
        raise ValueError(observation.outcome)


def _insert_raw_blob(
    connection: sqlite3.Connection,
    receipt: RawBlobReceipt,
    created_at: str,
) -> None:
    _ = query(
        connection,
        """
        INSERT OR IGNORE INTO raw_blobs
        (body_sha, raw_path, content_type, byte_count, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            receipt.body_sha,
            str(receipt.path),
            receipt.content_type,
            receipt.byte_count,
            created_at,
        ),
    )
