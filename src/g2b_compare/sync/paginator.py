"""Fail-closed continuous provider pagination state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final, override

DUPLICATE_WINDOW_PAGE: Final = "duplicate-window-page"
MISSING_WINDOW_PAGE: Final = "missing-window-page"
CHANGING_TOTAL: Final = "changing-total"
PUBLICATION_NOT_VALIDATED: Final = "publication-not-validated"


class SyncInvariantError(ValueError):
    """A provider page or sync transition violates a sanitized invariant."""

    reason: str

    def __init__(self, reason: str) -> None:
        """Initialize one stable caller-visible reason."""
        super().__init__(reason)
        self.reason = reason

    @override
    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class PageMeta:
    """Provider pagination fields and the decoded row count for one page."""

    page_no: int
    num_of_rows: int
    total_count: int
    item_count: int


@dataclass(frozen=True, slots=True)
class PageScope:
    """Operation and inclusive window bound to validated provider pages."""

    operation: str
    window_start: str
    window_end: str


@final
class _ValidationSeal:
    pass


_VALIDATION_SEAL: Final = _ValidationSeal()


@final
class ValidatedPageSet:
    """Opaque publication capability issued only by successful finalization."""

    __slots__ = ("_page_count", "_scope", "_total_count")

    def __init__(
        self,
        scope: PageScope | None,
        total_count: int,
        page_count: int,
        seal: _ValidationSeal,
    ) -> None:
        """Reject construction without the module-private finalization seal."""
        if seal is not _VALIDATION_SEAL:
            raise SyncInvariantError(PUBLICATION_NOT_VALIDATED)
        self._scope = scope
        self._total_count = total_count
        self._page_count = page_count

    @property
    def total_count(self) -> int:
        """Return the validated provider total count."""
        return self._total_count

    @property
    def page_count(self) -> int:
        """Return the continuous page count covered by this capability."""
        return self._page_count

    @property
    def scope(self) -> PageScope | None:
        """Return the exact operation window, or None for non-publication use."""
        return self._scope

    def authorizes(self, scope: PageScope) -> bool:
        """Match this capability to the exact operation window that produced it."""
        return self._scope == scope


@dataclass(frozen=True, slots=True)
class PageSequence:
    """Immutable continuous page sequence for one persisted date window."""

    pages: tuple[PageMeta, ...]
    total_count: int | None
    complete: bool
    scope: PageScope | None

    @classmethod
    def empty(cls, scope: PageScope | None = None) -> PageSequence:
        """Create an unstarted window sequence."""
        return cls(pages=(), total_count=None, complete=False, scope=scope)

    @classmethod
    def resume(
        cls,
        next_page: int,
        num_of_rows: int,
        total_count: int,
        scope: PageScope | None = None,
    ) -> PageSequence:
        """Reconstruct verified metadata preceding a persisted next-page cursor."""
        if next_page <= 1 or num_of_rows < 1 or total_count < 0:
            raise SyncInvariantError(MISSING_WINDOW_PAGE)
        pages = tuple(
            PageMeta(page_no, num_of_rows, total_count, num_of_rows)
            for page_no in range(1, next_page)
        )
        if pages[-1].page_no * num_of_rows >= total_count:
            raise SyncInvariantError(DUPLICATE_WINDOW_PAGE)
        return cls(
            pages=pages,
            total_count=total_count,
            complete=False,
            scope=scope,
        )

    def add(self, page: PageMeta) -> PageSequence:
        """Append exactly the next provider page after validating all metadata."""
        if self.complete:
            raise SyncInvariantError(DUPLICATE_WINDOW_PAGE)
        expected_page = len(self.pages) + 1
        if page.page_no < expected_page:
            raise SyncInvariantError(DUPLICATE_WINDOW_PAGE)
        if page.page_no > expected_page:
            raise SyncInvariantError(MISSING_WINDOW_PAGE)
        if page.num_of_rows < 1 or page.total_count < 0 or page.item_count < 0:
            raise SyncInvariantError(MISSING_WINDOW_PAGE)
        if self.total_count is not None and page.total_count != self.total_count:
            raise SyncInvariantError(CHANGING_TOTAL)
        final_page = page.page_no * page.num_of_rows >= page.total_count
        expected_items = (
            max(0, page.total_count - (page.page_no - 1) * page.num_of_rows)
            if final_page
            else page.num_of_rows
        )
        if page.item_count != min(page.num_of_rows, expected_items):
            raise SyncInvariantError(MISSING_WINDOW_PAGE)
        return PageSequence(
            (*self.pages, page),
            page.total_count,
            final_page,
            self.scope,
        )

    def finalize(self) -> ValidatedPageSet:
        """Issue a scoped publication capability after provider completion."""
        if not self.complete or self.total_count is None:
            raise SyncInvariantError(MISSING_WINDOW_PAGE)
        return ValidatedPageSet(
            self.scope,
            self.total_count,
            len(self.pages),
            _VALIDATION_SEAL,
        )
