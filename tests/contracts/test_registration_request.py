from datetime import date

from g2b_compare.contracts.quota import Operation
from g2b_compare.contracts.wire import candidates


def test_registration_candidates_use_official_date_query_contract() -> None:
    # Given: the day after the last complete provider date.
    today = date(2026, 7, 16)

    # When: discovery candidates are built for shopping-mall product registration.
    observed = candidates(Operation.GET_SHOPPING_MALL_PRODUCT_INFO, today)

    # Then: each bounded span uses the official YYYYMMDD query shape only.
    assert observed == (
        (
            ("type", "json"),
            ("pageNo", "1"),
            ("numOfRows", "1"),
            ("inqryDiv", "1"),
            ("inqryBgnDate", "20260715"),
            ("inqryEndDate", "20260715"),
        ),
        (
            ("type", "json"),
            ("pageNo", "1"),
            ("numOfRows", "1"),
            ("inqryDiv", "1"),
            ("inqryBgnDate", "20260615"),
            ("inqryEndDate", "20260715"),
        ),
        (
            ("type", "json"),
            ("pageNo", "1"),
            ("numOfRows", "1"),
            ("inqryDiv", "1"),
            ("inqryBgnDate", "20250716"),
            ("inqryEndDate", "20260715"),
        ),
    )
