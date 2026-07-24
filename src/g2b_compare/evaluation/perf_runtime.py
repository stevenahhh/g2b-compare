"""Lock deterministic thread settings before perf vector libraries import."""

from __future__ import annotations

import os
from typing import Final

LOCKED_THREAD_ENV: Final = (
    ("PYTHONHASHSEED", "0"),
    ("OMP_NUM_THREADS", "1"),
    ("MKL_NUM_THREADS", "1"),
    ("OPENBLAS_NUM_THREADS", "1"),
)


def configure_perf_runtime() -> None:
    """Apply the exact perf-v1 process settings recorded by the manifest."""
    for name, value in LOCKED_THREAD_ENV:
        os.environ[name] = value
