from g2b_compare.web.links import (
    SHOP_HOME,
    ProductLink,
    product_link,
    stable_product_link,
)


def test_stable_link_requires_persisted_preflight() -> None:
    manifest = {
        "stable_contract_item_management_number": "ABC_123",
        "share_link_preflight": {
            "no_redirect": True,
            "final_host": "shop.g2b.go.kr",
            "status": 200,
        },
    }
    assert stable_product_link(manifest) == (
        "https://shop.g2b.go.kr/link/GMSF001_01/?ctrtItemMngNo=ABC_123"
    )
    assert stable_product_link({"key": "ABC_123"}) is None
    assert SHOP_HOME == "https://shop.g2b.go.kr/"


def test_product_link_uses_a_safe_live_contract_item_key() -> None:
    assert product_link({}, "P-1", contract_item_key="0023H041400_6") == ProductLink(
        "https://shop.g2b.go.kr/link/GMSF001_01/?ctrtItemMngNo=0023H041400_6",
        None,
    )
