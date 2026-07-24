"""Build deterministic category and pagination links from submitted GET fields."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from .types import ViewValue

_FORM = TypeAdapter(dict[str, str])


def category_choices(
    raw_form: ViewValue,
    choices: tuple[str, ...],
    results_path: str = "/",
) -> list[dict[str, str]]:
    """Preserve submitted fields while adding one selected category."""
    form = _string_form(raw_form)
    selected_upper = form.get("category_code", "")
    rows: list[dict[str, str]] = []
    for choice in choices:
        parts = choice.split("/", maxsplit=1)
        upper, detail = (
            (parts[0], parts[1]) if len(parts) > 1 else (selected_upper, parts[0])
        )
        query = {key: value for key, value in form.items() if key != "page"}
        query["category_code"] = upper
        query["detail_category_code"] = detail
        rows.append({"label": choice, "href": f"{results_path}?{urlencode(query)}"})
    return rows


def add_pagination(
    view: dict[str, ViewValue],
    params: list[tuple[str, str]],
    results_path: str = "/",
    *,
    page_size: int = 50,
    has_next: bool | None = None,
) -> None:
    """Expose bounded page links while preserving every submitted field."""
    total = view.get("total")
    page = view.get("page")
    if not isinstance(page, int):
        return
    view["previous_url"] = (
        _page_url(params, page - 1, results_path) if page > 1 else None
    )
    if has_next is None:
        if not isinstance(total, int):
            return
        has_next = page * page_size < total
    view["next_url"] = _page_url(params, page + 1, results_path) if has_next else None


def _page_url(params: list[tuple[str, str]], page: int, results_path: str) -> str:
    preserved = [(key, value) for key, value in params if key != "page"]
    return f"{results_path}?{urlencode([*preserved, ('page', str(page))])}"


def _string_form(raw_form: ViewValue) -> dict[str, str]:
    try:
        return _FORM.validate_python(raw_form)
    except ValidationError:
        return {}
