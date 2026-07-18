"""Typed page-attempt contracts shared by runtime sources and the runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from g2b_compare.contracts.quota import Operation
    from g2b_compare.sync.paginator import PageMeta
    from g2b_compare.sync.planner import DateWindow


@dataclass(frozen=True, slots=True)
class PageSourceError(Exception):
    """A typed provider failure with retry policy and observed HTTP status."""

    status_code: int
    retryable: bool


class AttemptGate(Protocol):
    """Persist and finish one quota reservation around every outbound attempt."""

    def reserve(self, operation: Operation) -> int:
        """Reserve one non-refundable call immediately before dispatch."""
        ...

    def finish(
        self,
        reservation_id: int,
        status_code: int,
        operation: Operation,
        window: int,
        page: int,
    ) -> None:
        """Persist the returned status without refunding the attempt."""
        ...


class PageSource(Protocol):
    """Fetch one already-authorized operation page through an existing adapter."""

    def fetch(
        self,
        operation: Operation,
        window: DateWindow,
        page_no: int,
    ) -> AttemptPage:
        """Return parsed metadata without duplicating HTTP or envelope logic."""
        ...


@dataclass(frozen=True, slots=True)
class AttemptPage:
    """One adapter outcome used by retry and pagination policy."""

    status_code: int
    metadata: PageMeta | None
    retryable: bool
