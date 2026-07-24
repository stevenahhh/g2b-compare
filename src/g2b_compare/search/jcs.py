"""Validate canonical JSON members after typed boundary parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from g2b_compare.db.hashes import JsonValue, canonical_json

if TYPE_CHECKING:
    from .models import IndexManifest, IndexSettings, ProductRow


@dataclass(frozen=True, slots=True)
class JcsInputs:
    """Bind typed parsed JSON values to their original member bytes."""

    member_map: dict[str, bytes]
    manifest: bytes
    parsed_manifest: IndexManifest
    settings: IndexSettings
    rows: tuple[ProductRow, ...]
    word_vocab: dict[str, int]
    char_vocab: dict[str, int]


def jcs_members_valid(inputs: JcsInputs) -> bool:
    """Return whether every JSON member is its exact RFC8785 subset encoding."""
    values: tuple[tuple[bytes, JsonValue], ...] = (
        (inputs.manifest, inputs.parsed_manifest.model_dump(mode="json")),
        (inputs.member_map["settings.json"], inputs.settings.model_dump(mode="json")),
        (
            inputs.member_map["product-rows.json"],
            [row.model_dump(mode="json") for row in inputs.rows],
        ),
        (inputs.member_map["word-vocabulary.json"], dict(inputs.word_vocab)),
        (inputs.member_map["char-vocabulary.json"], dict(inputs.char_vocab)),
    )
    return all(
        canonical_json(value).encode("utf-8") == payload for payload, value in values
    )
