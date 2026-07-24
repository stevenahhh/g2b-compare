"""Collect bounded live samples for video-surveillance search testing."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import httpx

from g2b_compare.contracts.quota import Operation
from g2b_compare.contracts.wire import HttpxRequester, official_url, parse_page
from g2b_compare.sources.transport import (
    HttpTransport,
    RetryableTransportError,
    TransportRequest,
)

if TYPE_CHECKING:
    from g2b_compare.contracts.redact import JsonScalar, JsonValue
    from g2b_compare.contracts.wire import ObservedPage

PAGE_SIZE: Final = 100
WINDOW_DAYS: Final = 31
DEFAULT_LIMIT: Final = 1_000
DEFAULT_CALL_LIMIT: Final = 10_000
ADDITIONAL_ROLES: Final = frozenset({"선택사양(별도구매)", "동시구매"})
LIMIT_ERROR: Final = "--limit must be between 1 and 1000"
CALL_LIMIT_ERROR: Final = "--call-limit must be between 1 and 10000"
KEY_ERROR: Final = "G2B_SERVICE_KEY is required"


class Arguments(argparse.Namespace):
    """Typed sample collector arguments."""

    product_name: str
    limit: int
    call_limit: int
    output: Path

    def __init__(self) -> None:
        """Initialize defaults before argparse overwrites supplied values."""
        super().__init__()
        self.product_name = "영상감시장치"
        self.limit = DEFAULT_LIMIT
        self.call_limit = DEFAULT_CALL_LIMIT
        self.output = Path(".g2b") / "samples"


def main() -> int:
    """Collect product rows and verified delivery-group option observations."""
    args = _parser().parse_args(namespace=Arguments())
    if not 1 <= args.limit <= DEFAULT_LIMIT:
        raise SystemExit(LIMIT_ERROR)
    if not 1 <= args.call_limit <= DEFAULT_CALL_LIMIT:
        raise SystemExit(CALL_LIMIT_ERROR)
    key = os.environ.get("G2B_SERVICE_KEY", "").strip()
    if not key:
        raise SystemExit(KEY_ERROR)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    calls = 0
    product_path = output / "video-surveillance-products.jsonl"
    with httpx.Client(
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(connect=5, read=30, write=10, pool=10),
    ) as client:
        transport = HttpTransport(HttpxRequester(client), max_attempts=2)
        product_count = _line_count(product_path)
        if (
            product_count < args.limit
            or _contains_replacement_character(product_path)
            or _unique_product_count(product_path) < args.limit
        ):
            products, used = collect_products(
                transport, key, args.product_name, args.limit, args.call_limit
            )
            calls += used
            _write_jsonl(product_path, products)
            product_count = len(products)
        try:
            option_count, used = collect_options(
                transport,
                key,
                args,
                call_limit=args.call_limit - calls,
            )
        except RetryableTransportError as error:
            print(
                json.dumps(
                    {
                        "detail": str(error),
                        "options": _line_count(
                            output
                            / "video-surveillance-option-observations.jsonl"
                        ),
                        "products": product_count,
                        "status": "provider-temporarily-unavailable",
                    },
                    sort_keys=True,
                )
            )
            return 2
        calls += used
    print(
        json.dumps(
            {"calls": calls, "options": option_count, "products": product_count},
            sort_keys=True,
        )
    )
    return 0


def collect_products(
    transport: HttpTransport,
    key: str,
    product_name: str,
    limit: int,
    call_limit: int,
) -> tuple[list[dict[str, JsonScalar]], int]:
    """Collect distinct products by their official product identifier."""
    operation = Operation.GET_MAS_CONTRACT_PRODUCT_INFO
    rows: list[dict[str, JsonScalar]] = []
    seen_product_ids: set[str] = set()
    calls = 0
    page_no = 1
    total = limit
    while len(rows) < min(limit, total) and calls < call_limit:
        page = _fetch(
            transport,
            key,
            operation,
            (
                ("type", "json"),
                ("pageNo", str(page_no)),
                ("numOfRows", str(PAGE_SIZE)),
                ("prdctClsfcNoNm", product_name),
            ),
        )
        calls += 1
        total = page.total_count
        for row in page.rows:
            product_id = str(row.get("prdctIdntNo", "")).strip()
            if not product_id or product_id in seen_product_ids:
                continue
            seen_product_ids.add(product_id)
            rows.append(row)
            if len(rows) >= limit:
                break
        if not page.rows:
            break
        page_no += 1
    return rows, calls


def collect_options(
    transport: HttpTransport,
    key: str,
    args: Arguments,
    *,
    call_limit: int,
) -> tuple[int, int]:
    """Collect actual option-role observations with resumable checkpoints."""
    operation = Operation.GET_DELIVERY_REQUEST_DETAIL
    output = args.output.resolve()
    request_path = output / "video-surveillance-delivery-requests.txt"
    processed_path = output / "video-surveillance-processed-requests.txt"
    option_path = output / "video-surveillance-option-observations.jsonl"
    request_numbers = _read_nonempty_lines(request_path)
    calls = 0
    if not request_numbers:
        request_numbers, calls = _request_numbers(
            transport,
            key,
            args.product_name,
            args.limit,
            call_limit,
        )
        _write_lines(request_path, request_numbers)
    processed = set(_read_nonempty_lines(processed_path))
    observation_count = _line_count(option_path)
    for request_no in request_numbers:
        if observation_count >= args.limit or calls >= call_limit:
            break
        if request_no in processed:
            continue
        group, used = _option_group(
            transport,
            key,
            operation,
            request_no,
            call_limit - calls,
        )
        calls += used
        parent_ids = sorted(
            {
                str(row.get("prdctIdntNo", "")).strip()
                for row in group
                if row.get("optnDivCdNm") == "대표품목"
                and str(row.get("prdctIdntNo", "")).strip()
            }
        )
        observations: list[dict[str, JsonValue]] = []
        for row in group:
            if row.get("optnDivCdNm") not in ADDITIONAL_ROLES:
                continue
            parent_values: list[JsonValue] = []
            parent_values.extend(parent_ids)
            option_value: dict[str, JsonValue] = dict(row)
            observations.append(
                {
                    "delivery_request_no": request_no,
                    "parent_product_ids": parent_values,
                    "option_product": option_value,
                    "provenance": "delivery-group-role-observation",
                }
            )
            if observation_count + len(observations) >= args.limit:
                break
        _append_jsonl(option_path, observations)
        observation_count += len(observations)
        _append_line(processed_path, request_no)
        processed.add(request_no)
    return observation_count, calls


def _request_numbers(
    transport: HttpTransport,
    key: str,
    product_name: str,
    limit: int,
    call_limit: int,
) -> tuple[list[str], int]:
    operation = Operation.GET_DELIVERY_REQUEST_DETAIL
    request_numbers: list[str] = []
    seen_requests: set[str] = set()
    calls = 0
    end = datetime.now(UTC).date()
    earliest = end - timedelta(days=3650)
    while end >= earliest and calls < call_limit and len(request_numbers) < limit:
        start = max(earliest, end - timedelta(days=WINDOW_DAYS - 1))
        page_no = 1
        while calls < call_limit:
            page = _fetch(
                transport,
                key,
                operation,
                (
                    ("type", "json"),
                    ("pageNo", str(page_no)),
                    ("numOfRows", str(PAGE_SIZE)),
                    ("inqryDiv", "1"),
                    ("inqryBgnDate", start.strftime("%Y%m%d")),
                    ("inqryEndDate", end.strftime("%Y%m%d")),
                    ("prdctClsfcNoNm", product_name),
                ),
            )
            calls += 1
            for row in page.rows:
                request_no = str(row.get("dlvrReqNo", "")).strip()
                if request_no and request_no not in seen_requests:
                    seen_requests.add(request_no)
                    request_numbers.append(request_no)
            if page_no * (page.reported_page_size or PAGE_SIZE) >= page.total_count:
                break
            page_no += 1
        end = start - timedelta(days=1)
    return request_numbers, calls


def _option_group(
    transport: HttpTransport,
    key: str,
    operation: Operation,
    request_no: str,
    call_limit: int,
) -> tuple[list[dict[str, JsonScalar]], int]:
    page_no = 1
    calls = 0
    group: list[dict[str, JsonScalar]] = []
    total = PAGE_SIZE
    while (page_no - 1) * PAGE_SIZE < total and calls < call_limit:
        page = _fetch(
            transport,
            key,
            operation,
            (
                ("type", "json"),
                ("pageNo", str(page_no)),
                ("numOfRows", str(PAGE_SIZE)),
                ("inqryDiv", "2"),
                ("dlvrReqNo", request_no),
            ),
        )
        calls += 1
        total = page.total_count
        group.extend(page.rows)
        page_no += 1
    return group, calls


def _fetch(
    transport: HttpTransport,
    key: str,
    operation: Operation,
    params: tuple[tuple[str, str], ...],
) -> ObservedPage:
    response = transport.get(
        TransportRequest(operation, official_url(operation), params),
        service_key=key,
    )
    return parse_page(response.content, operation)


def _write_jsonl(
    path: Path,
    rows: list[dict[str, JsonScalar]] | list[dict[str, JsonValue]],
) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            _ = stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


def _append_jsonl(path: Path, rows: list[dict[str, JsonValue]]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            _ = stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


def _read_nonempty_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def _line_count(path: Path) -> int:
    return len(_read_nonempty_lines(path))


def _contains_replacement_character(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as stream:
        return any("\ufffd" in line for line in stream)


def _unique_product_count(path: Path) -> int:
    product_ids: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = cast("dict[str, JsonValue]", json.loads(line))
            product_id = row.get("prdctIdntNo")
            if isinstance(product_id, str) and product_id:
                product_ids.add(product_id)
    return len(product_ids)


def _write_lines(path: Path, values: list[str]) -> None:
    _ = path.write_text("".join(f"{value}\n" for value in values), encoding="utf-8")


def _append_line(path: Path, value: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        _ = stream.write(f"{value}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--product-name", default="영상감시장치")
    _ = parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    _ = parser.add_argument("--call-limit", type=int, default=DEFAULT_CALL_LIMIT)
    _ = parser.add_argument("--output", type=Path, default=Path(".g2b") / "samples")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
