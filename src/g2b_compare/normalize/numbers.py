"""Parse the supported v1 Arabic-number grammar."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Final


class NumberParseError(ValueError):
    """Base error for deterministic numeric parsing failures."""


class AmbiguousNumberError(NumberParseError):
    """Report comma placement outside the supported thousands grouping."""

    raw: str

    def __init__(self, raw: str) -> None:
        """Build an error for one malformed grouped number."""
        super().__init__(f"ambiguous number rejected: {raw}")
        self.raw = raw


class UnsupportedNumberError(NumberParseError):
    """Report a numeral form outside the Arabic and Arabic-plus-man grammar."""

    raw: str
    pure_korean: bool

    def __init__(self, raw: str, *, pure_korean: bool = False) -> None:
        """Build an error for one unsupported numeral form."""
        message = (
            f"pure Korean numeral unsupported: {raw}"
            if pure_korean
            else f"unsupported Arabic number: {raw}"
        )
        super().__init__(message)
        self.raw = raw
        self.pure_korean = pure_korean


class InvalidQuantityError(NumberParseError):
    """Report a zero or negative quantity at the parser boundary."""

    raw: str
    value: Decimal
    negative: bool

    def __init__(
        self,
        raw: str,
        value: Decimal,
        *,
        negative: bool = False,
    ) -> None:
        """Build an error for one non-positive quantity."""
        message = (
            f"negative quantity rejected: {raw}"
            if negative or value < 0
            else f"quantity must be greater than zero: {raw}"
        )
        super().__init__(message)
        self.raw = raw
        self.value = value
        self.negative = negative


ARABIC_NUMBER: Final = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
NUMBER_WITH_MAN: Final = rf"{ARABIC_NUMBER}(?:만)?"
NUMBER_PATTERN: Final = re.compile(rf"^(?P<number>{ARABIC_NUMBER})(?P<man>만)?$")


def parse_number(raw: str) -> Decimal:
    """Return a Decimal for an Arabic number with an optional 만 multiplier."""
    match = NUMBER_PATTERN.fullmatch(raw)
    if match is None:
        if "," in raw:
            raise AmbiguousNumberError(raw)
        raise UnsupportedNumberError(raw)
    value = Decimal(match.group("number").replace(",", ""))
    if match.group("man") is not None:
        value *= Decimal(10_000)
    return value


def require_positive(
    value: Decimal,
    *,
    raw: str,
    negative: bool = False,
) -> Decimal:
    """Return a positive quantity or raise its typed boundary error."""
    if negative or value < 0:
        raise InvalidQuantityError(raw, value, negative=True)
    if value == 0:
        raise InvalidQuantityError(raw, value)
    return value
