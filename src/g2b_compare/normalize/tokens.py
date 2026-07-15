"""Define the protected-quantity and lexical token grammar."""

from __future__ import annotations

import re
from typing import Final

from .numbers import NUMBER_WITH_MAN
from .units import ALIASES

TOKENIZER_VERSION: Final = "v1"
_DOMAIN_LATIN: Final = (r"[Mm][Pp]", r"[Pp][Xx]", r"[Ff][Pp][Ss]")
_LITERAL_ALIASES: Final = tuple(
    re.escape(alias) for alias in ALIASES if alias not in {"MP", "PX", "FPS"}
)
UNIT_PATTERN: Final = "(?:" + "|".join((*_DOMAIN_LATIN, *_LITERAL_ALIASES)) + ")"
QUANTITY_PATTERN: Final = rf"{NUMBER_WITH_MAN}{UNIT_PATTERN}"
DIMENSION_PATTERN: Final = (
    rf"{NUMBER_WITH_MAN}\s*[xX\u00d7]\s*{NUMBER_WITH_MAN}"
    rf"(?:\s*{UNIT_PATTERN})?"
)
RANGE_PATTERN: Final = (
    rf"(?:{NUMBER_WITH_MAN}(?:{UNIT_PATTERN})?\s*[~-]\s*"
    rf"{NUMBER_WITH_MAN}{UNIT_PATTERN}|{NUMBER_WITH_MAN}{UNIT_PATTERN}\s*[~-]\s*"
    rf"{NUMBER_WITH_MAN})"
)
RELATION_PATTERN: Final = rf"{QUANTITY_PATTERN}\s*(?:이상|이하|초과|미만|>=|<=|>|<)"
_RELATION_SUFFIX: Final = r"(?:이상|이하|초과|미만|>=|<=|>|<)"
_LEFT_BOUNDARY: Final = r"(?<![\d.,A-Za-z/\u00d7~<>=-])"
_COMPOUND_END: Final = r"(?![\d.A-Za-z/\u00d7~<>=-]|,\d)"
_STRUCTURED_END: Final = rf"{_COMPOUND_END}(?![가-힣])"
_UNSUPPORTED_COMPOUND_TOKEN: Final = "".join(
    (
        _LEFT_BOUNDARY,
        rf"{NUMBER_WITH_MAN}\s*[xX\u00d7]\s*{NUMBER_WITH_MAN}\s*",
        rf"[xX\u00d7]\s*{NUMBER_WITH_MAN}(?:\s*{UNIT_PATTERN})?",
        rf"{_STRUCTURED_END}(?!\s*[xX\u00d7]\s*{NUMBER_WITH_MAN})",
    ),
)
_PROTECTED_TOKEN: Final = "".join(
    (
        _LEFT_BOUNDARY,
        rf"(?:(?:{DIMENSION_PATTERN}|{RANGE_PATTERN}|{RELATION_PATTERN})",
        rf"{_STRUCTURED_END}|{QUANTITY_PATTERN}(?!\s*{_RELATION_SUFFIX})",
        rf"{_COMPOUND_END})",
    ),
)
UNSUPPORTED_COMPOUND_PATTERN: Final = re.compile(_UNSUPPORTED_COMPOUND_TOKEN)
PROTECTED_PATTERN: Final = re.compile(_PROTECTED_TOKEN)
TOKEN_PATTERN: Final = re.compile(
    "".join(
        (
            rf"{_UNSUPPORTED_COMPOUND_TOKEN}|{_PROTECTED_TOKEN}|",
            r"[가-힣]+|[a-z0-9]+(?:[-_.][a-z0-9]+)*",
        ),
    ),
)


def tokenize(derived: str) -> tuple[str, ...]:
    """Return protected quantities and lexical tokens in source order."""
    return tuple(match.group(0) for match in TOKEN_PATTERN.finditer(derived))
