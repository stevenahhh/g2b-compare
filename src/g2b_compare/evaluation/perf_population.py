"""Build deterministic perf-v1 products and SQLite storage rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from g2b_compare.db.hashes import JsonValue, canonical_json
from g2b_compare.search.models import IndexProduct

from .perf_storage import PerfStorageRow

if TYPE_CHECKING:
    from pathlib import Path

POOL_SIZES: Final = (20, 40, 60, 80, 100, 120, 140, 160, 180, 100)
POOL_COUNT: Final = 500
STRUCTURED_REMAINDER: Final = 7
MISSING_PRICE_REMAINDER: Final = 7
MIXED_UNIT_REMAINDER: Final = 19


@dataclass(frozen=True, slots=True)
class ProductCoordinates:
    """Identify one product and its deterministic distribution flags."""

    pool_index: int
    ordinal: int
    global_ordinal: int
    structured: bool
    missing_price: bool
    mixed_unit: bool


def write_corpus(path: Path) -> tuple[int, int, int, int]:
    """Write exact corpus rows and return the four distribution counts."""
    product_count = 0
    structured_count = 0
    missing_price_count = 0
    mixed_unit_count = 0
    global_ordinal = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for pool_index in range(POOL_COUNT):
            size = POOL_SIZES[pool_index % len(POOL_SIZES)]
            for ordinal in range(size):
                coordinates = _coordinates(pool_index, ordinal, global_ordinal)
                _ = stream.write(canonical_json(product_row(coordinates)) + "\n")
                product_count += 1
                structured_count += coordinates.structured
                missing_price_count += coordinates.missing_price
                mixed_unit_count += coordinates.mixed_unit
                global_ordinal += 1
    return product_count, structured_count, missing_price_count, mixed_unit_count


def product_row(source: ProductCoordinates) -> dict[str, JsonValue]:
    """Build one canonical product payload."""
    pool_index = source.pool_index
    ordinal = source.ordinal
    global_ordinal = source.global_ordinal
    megapixels = 2 + (global_ordinal % 15)
    frames = 15 + (5 * (global_ordinal % 10))
    storage = 1 + (global_ordinal % 16)
    price = 100_000 + ((global_ordinal % 1_000) * 1_000)
    attributes: list[JsonValue] = []
    if source.structured:
        attributes = [
            {"key": "resolution", "unit": "MP", "value": str(megapixels)},
            {"key": "frame-rate", "unit": "fps", "value": str(frames)},
            {"key": "storage", "unit": "TB", "value": str(storage)},
        ]
    return {
        "active": True,
        "attributes": attributes,
        "category_no": f"PERF-CAT-{pool_index % 25:02d}",
        "detail_category_no": f"PERF-DETAIL-{pool_index:03d}",
        "model": f"PERF-{global_ordinal:05d}",
        "option_text": (
            f"해상도 {megapixels}MP | {frames}fps | 저장 {storage}TB | "
            f"모델 PERF-{global_ordinal:05d}"
        ),
        "ordinal": ordinal,
        "price_unit": (
            None if source.missing_price else ("식" if source.mixed_unit else "대")
        ),
        "price_won": None if source.missing_price else price,
        "product_id": f"PERF-{pool_index:03d}-{ordinal:03d}",
        "product_name": f"영상감시장치-{pool_index:03d}",
    }


def pool_offsets() -> tuple[int, ...]:
    """Return each pool's zero-based global offset."""
    offsets: list[int] = []
    total = 0
    for pool_index in range(POOL_COUNT):
        offsets.append(total)
        total += POOL_SIZES[pool_index % len(POOL_SIZES)]
    return tuple(offsets)


def storage_rows() -> tuple[PerfStorageRow, ...]:
    """Build the SQLite projection of the exact product population."""
    rows: list[PerfStorageRow] = []
    global_ordinal = 0
    for pool_index in range(POOL_COUNT):
        size = POOL_SIZES[pool_index % len(POOL_SIZES)]
        for ordinal in range(size):
            coordinates = _coordinates(pool_index, ordinal, global_ordinal)
            rows.append(
                PerfStorageRow(
                    f"PERF-{pool_index:03d}-{ordinal:03d}",
                    f"PERF-CAT-{pool_index % 25:02d}",
                    f"PERF-DETAIL-{pool_index:03d}",
                    f"영상감시장치-{pool_index:03d}",
                    canonical_json(product_row(coordinates)),
                )
            )
            global_ordinal += 1
    return tuple(rows)


def index_products() -> tuple[IndexProduct, ...]:
    """Build the exact active candidate population fitted by production TF-IDF."""
    products: list[IndexProduct] = []
    global_ordinal = 0
    for pool_index in range(POOL_COUNT):
        size = POOL_SIZES[pool_index % len(POOL_SIZES)]
        for ordinal in range(size):
            source = _coordinates(pool_index, ordinal, global_ordinal)
            row = product_row(source)
            name = f"영상감시장치-{pool_index:03d}"
            products.append(
                IndexProduct(
                    f"PERF-{pool_index:03d}-{ordinal:03d}",
                    (
                        f"PERF-CAT-{pool_index % 25:02d}",
                        f"PERF-DETAIL-{pool_index:03d}",
                    ),
                    name,
                    name,
                    str(row["option_text"]),
                    active=True,
                )
            )
            global_ordinal += 1
    return tuple(products)


def _coordinates(
    pool_index: int,
    ordinal: int,
    global_ordinal: int,
) -> ProductCoordinates:
    return ProductCoordinates(
        pool_index,
        ordinal,
        global_ordinal,
        global_ordinal % 10 < STRUCTURED_REMAINDER,
        global_ordinal % 10 == MISSING_PRICE_REMAINDER,
        global_ordinal % 20 == MIXED_UNIT_REMAINDER,
    )
