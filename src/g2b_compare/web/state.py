"""Project persisted status signals into the finite public UI vocabulary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .types import ViewValue

ALLOWED_STATUSES: Final = frozenset(
    {
        "incompatible-price",
        "insufficient-comparator",
        "no-evidence",
        "partial-attribute",
        "stale",
        "sync-failed-last-good",
    }
)
_STATUS_LIST = TypeAdapter(list[str])


def sanitize_statuses(statuses: Iterable[str]) -> list[str]:
    """Discard forbidden or unknown persisted tokens and sort by ASCII bytes."""
    return sorted(
        {token for token in statuses if token in ALLOWED_STATUSES},
        key=str.encode,
    )


def result_state(default: str, statuses: Iterable[str]) -> str:
    """Apply sync and freshness precedence without emitting two primary states."""
    allowed = frozenset(statuses)
    if "sync-failed-last-good" in allowed:
        return "sync-failed-last-good"
    if "stale" in allowed:
        return "stale"
    return default


def parse_statuses(value: ViewValue) -> list[str]:
    """Parse an untyped template projection into exact status strings."""
    try:
        return _STATUS_LIST.validate_python(value)
    except ValidationError:
        return []
