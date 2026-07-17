"""Synthetic frozen-release inputs for Todo 12 E0 export tests."""

from __future__ import annotations

from g2b_compare.evaluation.e0_export import (
    E0Product,
    FrozenE0Release,
    ParserSource,
    ReleaseIdentity,
)

STRATA_TEXT = (
    (0, "옵션 없음"),
    (1, "가격 누락 8MP"),
    (2, "MODEL-A1 8MP"),
    (3, "카메라 Camera"),
    (4, "카메라 화소"),
)


def release_fixture(*, groups: int = 10, pool_size: int = 20) -> FrozenE0Release:
    products = tuple(
        _product(group, ordinal, pool_size)
        for group in range(groups)
        for ordinal in range(pool_size)
    )
    return FrozenE0Release(_identity(), products, _parser_sources(products))


def _product(group: int, ordinal: int, pool_size: int) -> E0Product:
    stratum_index = min(ordinal // max(pool_size // 5, 1), 4)
    attribute_count, text = STRATA_TEXT[stratum_index]
    price = None if stratum_index == 1 else 100_000 + ordinal * 1_000
    return E0Product(
        product_id=f"P-{group:02d}-{ordinal:03d}",
        category_no=f"C-{group:02d}",
        detail_category_no=f"D-{group:02d}",
        product_name_key="영상감시장치",
        option_text=text,
        active=True,
        attribute_count=attribute_count,
        price_won=price,
        price_unit="대" if price is not None else None,
    )


def _identity() -> ReleaseIdentity:
    return ReleaseIdentity(
        bundle_id=7,
        release_bundle_sha="a" * 64,
        materialization_id=11,
        materialization_sha="b" * 64,
        index_artifact_sha="c" * 64,
        index_manifest_sha="d" * 64,
        word_idf_sha="e" * 64,
        char_idf_sha="f" * 64,
        relation_snapshot_sha="1" * 64,
        ranking_version="v1",
        created_at_utc="2026-07-14T00:00:00Z",
    )


def _parser_sources(products: tuple[E0Product, ...]) -> tuple[ParserSource, ...]:
    examples = (
        "전압 12V",
        "용량 1,024GB",
        "수량 2만 화소",
        "전압 10V 이하",
        "범위 10~20V",
        "해상도 3840\u00d72160 화소",
        "속도 30fps",
        "주파수 10MHz",
        "지원값 -1V",
        "해상도 8MP 저장 2TB",
    )
    sources: list[ParserSource] = []
    for stratum_index, text in enumerate(examples):
        for ordinal in range(50):
            product = products[(stratum_index * 50 + ordinal) % len(products)]
            sources.append(
                ParserSource(
                    product_id=product.product_id,
                    field_kind="raw_value",
                    source_key=f"S-{stratum_index:02d}-{ordinal:03d}",
                    ordinal=ordinal,
                    text=f"{text} #{ordinal:03d}",
                )
            )
    return tuple(sources)
