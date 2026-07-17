from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from g2b_compare.db.connection import connect
from g2b_compare.db.sql import query
from tests.services.release_support import ReleaseFixture, release_database

if TYPE_CHECKING:
    from pathlib import Path
    from sqlite3 import Connection

PRODUCT_IDS: Final = ("A", "B", "C", "D")
PRICES: Final = (1_000_000, 1_100_000, 1_200_000, 2_000_000)
RESOLUTIONS: Final = ("800만화소", "800만화소", "800만화소", "400만화소")
FRAME_RATES: Final = ("30fps", "30fps", "15fps", "30fps")


@dataclass(frozen=True, slots=True)
class SearchFixture:
    release: ReleaseFixture


def search_database(path: Path) -> SearchFixture:
    release = release_database(path, PRODUCT_IDS)
    with connect(path) as connection:
        _ = query(
            connection,
            """INSERT INTO source_snapshots VALUES(
               90,'getDlvrReqDtlInfoList',NULL,'full','2026-07-01',
               '2026-07-16','complete','complete','2026-07-16T00:00:00Z')""",
        )
        for index, product_id in enumerate(PRODUCT_IDS):
            _seed_product(connection, index, product_id)
    return SearchFixture(release)


def _seed_product(connection: Connection, index: int, product_id: str) -> None:
    _ = query(
        connection,
        """INSERT INTO catalog_offers VALUES(
           10,'getMASCntrctPrdctInfoList',?,?,?,'대','대',1,
           '2026-07-16T00:00:00Z')""",
        (f"offer-{product_id}", product_id, PRICES[index]),
    )
    for ordinal, (key, name, value) in enumerate(
        (
            ("resolution", "화소", RESOLUTIONS[index]),
            ("frame-rate", "프레임", FRAME_RATES[index]),
        )
    ):
        _ = query(
            connection,
            """INSERT INTO product_attributes VALUES(
               10,?,?,?,?,?,?,?,NULL,NULL,'raw')""",
            (product_id, key, ordinal, 10, f"attr-{product_id}-{ordinal}", name, value),
        )
    _ = query(
        connection,
        """INSERT INTO option_role_observations VALUES(
           10,90,?,?, 'delivery-1',1,0,'추가선택','2026-07-16T00:00:00Z')""",
        (f"role-{product_id}", product_id),
    )
    _ = query(
        connection,
        """INSERT INTO curated_relations VALUES(
           10,?,?,?,'workbook',?,'품목',?)""",
        (
            f"relation-{product_id}",
            product_id,
            f"extra-{product_id}",
            "f" * 64,
            index + 1,
        ),
    )
