"""Curated source import adapters."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RelationSourceManifest:
    """Trusted workbook relation grammar emitted by Todo 4."""

    source_sha256: str
    sheet_name: str
    headers: tuple[tuple[str, str], ...]
    parent_coordinate: str
    parent_value: str
    child_coordinates: tuple[str, ...]
    unbound_coordinates: tuple[str, ...]
    curated_relationship_count: int
    unbound_option_count: int
