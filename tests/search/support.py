from __future__ import annotations

from g2b_compare.search.models import IndexProduct


def product(
    product_id: str,
    *,
    category: tuple[str, str] = ("4410", "441015"),
    name: str = "영상감시장치",
    option: str = "attr:해상도=800만화소 | spec:실외형",
    active: bool = True,
) -> IndexProduct:
    return IndexProduct(
        product_id=product_id,
        category_key=category,
        product_name_raw=name,
        product_name_key=name,
        option_text=option,
        active=active,
    )


def corpus() -> tuple[IndexProduct, ...]:
    return (
        product("P-03", option=""),
        product("P-01", option="800만화소 실외형"),
        product("P-02", option="8MP 실내형"),
        product("P-04", category=("4410", "441016"), option="800 만 화소"),
        product("P-05", name="감시 카메라", option="model-x 방수"),
        product("P-06", active=False, option="비활성 문서"),
    )
