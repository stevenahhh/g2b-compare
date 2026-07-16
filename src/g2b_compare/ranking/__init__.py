"""Deterministic ranking of exact-pool procurement products."""

from .topk import ComparisonSlot, RankableProduct, top_three

__all__ = ["ComparisonSlot", "RankableProduct", "top_three"]
