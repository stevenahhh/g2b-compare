"""Typed facade over sqlite3's dynamically typed cursor stubs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, final, override

from pydantic import ConfigDict, TypeAdapter, ValidationError

if TYPE_CHECKING:
    import sqlite3

type SqlValue = str | int | float | bytes | None
type SqlParameters = tuple[SqlValue, ...]
type SqlRow = tuple[SqlValue, ...]

INT_ADAPTER: Final = TypeAdapter(int, config=ConfigDict(strict=True))
TEXT_ADAPTER: Final = TypeAdapter(str, config=ConfigDict(strict=True))


@final
class SqlTypeError(Exception):
    """A SQLite cell does not match the repository's expected scalar type."""

    expected: str

    def __init__(self, expected: str) -> None:
        """Initialize one rejected SQLite cell type."""
        super().__init__(expected)
        self.expected = expected

    @override
    def __str__(self) -> str:
        return f"SQLite cell is not {self.expected}"


class ResultCursor(Protocol):
    """The sqlite cursor capabilities consumed by repositories."""

    @property
    def lastrowid(self) -> int | None:
        """Return the most recently inserted integer key."""
        ...

    @property
    def rowcount(self) -> int:
        """Return affected rows for compare-and-swap statements."""
        ...

    def fetchone(self) -> SqlRow | None:
        """Return one typed SQLite row."""
        ...

    def fetchall(self) -> list[SqlRow]:
        """Return all typed SQLite rows."""
        ...


def query(
    connection: sqlite3.Connection,
    statement: str,
    parameters: SqlParameters = (),
) -> ResultCursor:
    """Execute parameterized SQL behind one typed adapter seam."""
    return connection.execute(statement, parameters)


def as_int(value: SqlValue) -> int:
    """Parse a SQLite scalar as a required integer."""
    try:
        return INT_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise SqlTypeError(expected="an integer") from error


def as_text(value: SqlValue) -> str:
    """Parse a SQLite scalar as required UTF-8 text."""
    try:
        return TEXT_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise SqlTypeError(expected="text") from error
