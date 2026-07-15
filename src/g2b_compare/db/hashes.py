"""Deterministic canonical JSON hashes used by database identities."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CanonicalSourceRecord, RequestInput

type JsonValue = str | int | bool | None | list[JsonValue] | dict[str, JsonValue]


def canonical_json(value: JsonValue) -> str:
    """Encode the plan's string-and-integer JCS subset deterministically."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_text(value: str) -> str:
    """Return the lowercase SHA-256 of UTF-8 text."""
    return hashlib.sha256(value.encode()).hexdigest()


def canonical_record_sha(record: CanonicalSourceRecord) -> str:
    """Hash normalized typed content while excluding price and timestamps."""
    fields: dict[str, JsonValue] = {
        "active": record.active,
        "category": _normalize(record.category),
        "characteristic": _normalize(record.characteristic),
        "detail": _normalize(record.detail),
        "detail_category": _normalize(record.detail_category),
        "operation": _normalize(record.operation),
        "product_id": _normalize(record.product_id),
        "product_name": _normalize(record.product_name),
        "spec_name": _normalize(record.spec_name),
        "stable_source_key": _normalize(record.stable_source_key),
        "unit_basis": _normalize(record.unit_basis),
    }
    return sha256_text(canonical_json(fields))


def catalog_source_identity(source_ids: tuple[tuple[str, int], ...]) -> tuple[str, str]:
    """Return canonical five-source JSON and its content hash."""
    ordered = sorted(source_ids, key=lambda item: item[0].encode())
    value: dict[str, JsonValue] = dict(ordered)
    encoded = canonical_json(value)
    return encoded, sha256_text(encoded)


def materialization_source_sha(
    catalog_generation_id: int,
    source_ids: tuple[int, ...],
    attribute_snapshot_id: int,
) -> str:
    """Hash the exact catalog, ordered sources, and attribute successor."""
    encoded = canonical_json(
        {
            "attribute_snapshot_id": attribute_snapshot_id,
            "catalog_generation_id": catalog_generation_id,
            "five_source_ids": list(source_ids),
        }
    )
    return sha256_text(encoded)


def request_identity(request: RequestInput) -> tuple[str, str, str]:
    """Return keyless params JSON, params SHA, and full request fingerprint."""
    params: dict[str, JsonValue] = {
        key: _normalize(value) for key, value in request.params
    }
    params_json = canonical_json(params)
    fingerprint_value: dict[str, JsonValue] = {
        "keyless_allowlisted_params": params,
        "method": request.method,
        "official_path": request.official_path,
        "operation": request.operation,
    }
    fingerprint = canonical_json(fingerprint_value)
    return params_json, sha256_text(params_json), sha256_text(fingerprint)


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value.replace("\r\n", "\n"))
