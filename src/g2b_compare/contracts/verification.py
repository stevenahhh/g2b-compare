"""Pure schema and stable-identity verification predicates."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from g2b_compare.contracts.redact import JsonScalar
    from g2b_compare.contracts.wire import ObservedPage

type SchemaFailure = Literal[
    "schema-changed-at-verification",
    "stable-key-missing",
    "stable-key-duplicate",
]


def has_stable_keys(
    rows: tuple[dict[str, JsonScalar], ...],
    keys: tuple[str, ...],
) -> bool:
    """Require every composite identity to be complete and unique."""
    return stable_key_failure(rows, keys) is None


def stable_key_failure(
    rows: tuple[dict[str, JsonScalar], ...],
    keys: tuple[str, ...],
) -> Literal["stable-key-missing", "stable-key-duplicate"] | None:
    """Return the exact within-page stable identity failure."""
    identities = tuple(tuple(row.get(key) for key in keys) for row in rows)
    if any(any(value in {None, ""} for value in identity) for identity in identities):
        return "stable-key-missing"
    if len(identities) != len(set(identities)):
        return "stable-key-duplicate"
    return None


def schema_failure(
    first: ObservedPage,
    current: ObservedPage,
    keys: tuple[str, ...],
) -> SchemaFailure | None:
    """Return the strict field or stable-identity verification failure."""
    if not schema_fields_match(first, current):
        return "schema-changed-at-verification"
    return stable_key_failure(current.rows, keys)


def schema_fields_match(first: ObservedPage, current: ObservedPage) -> bool:
    """Require the verification page to preserve the discovered field set."""
    return (
        bool(first.fields)
        and first.fields == current.fields
        and all(tuple(sorted(row)) == first.fields for row in first.rows)
        and all(tuple(sorted(row)) == current.fields for row in current.rows)
    )
