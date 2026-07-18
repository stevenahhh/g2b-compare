"""Secret-free structured operation logging."""

from __future__ import annotations

import json
import logging
from typing import Final

ALLOWED_FIELDS: Final = frozenset({"operation", "run", "window", "page", "status"})


def operation_log(
    logger: logging.Logger,
    *,
    operation: str,
    status: str,
    context: dict[str, int | str] | None = None,
) -> None:
    """Write one compact JSON event containing only approved identifiers."""
    values: dict[str, int | str] = {"operation": operation, "status": status}
    values.update(
        {
            key: value
            for key, value in (context or {}).items()
            if key in ALLOWED_FIELDS and key not in values
        }
    )
    logger.info(json.dumps(values, sort_keys=True, separators=(",", ":")))


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the local command logger without request or secret fields."""
    logger = logging.getLogger("g2b_compare")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
