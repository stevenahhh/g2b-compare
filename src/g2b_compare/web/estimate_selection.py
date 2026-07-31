"""Stable public facade for estimate selection and comparisons."""

from .estimate_models import COMPARISON_SLOT_COUNT, ComparisonView
from .estimate_resolution import resolve_selection
from .estimate_seeding import (
    seed_comparisons,
    seed_comparisons_in_transaction,
    seed_document_comparisons_in_transaction,
)
from .estimate_views import comparison_views

__all__ = [
    "COMPARISON_SLOT_COUNT",
    "ComparisonView",
    "comparison_views",
    "resolve_selection",
    "seed_comparisons",
    "seed_comparisons_in_transaction",
    "seed_document_comparisons_in_transaction",
]
