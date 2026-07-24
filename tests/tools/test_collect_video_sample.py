from pathlib import Path
from typing import cast

import pytest

from g2b_compare.contracts.quota import Operation
from g2b_compare.sources.transport import HttpTransport
from tools import collect_video_sample


def test_option_collection_resumes_after_provider_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = ["request-1", "request-2"]

    def request_numbers(
        transport: HttpTransport,
        key: str,
        product_name: str,
        limit: int,
        call_limit: int,
    ) -> tuple[list[str], int]:
        del transport, key, product_name, limit, call_limit
        return requests, 1

    failed = False

    def first_attempt(
        transport: HttpTransport,
        key: str,
        operation: Operation,
        request_no: str,
        call_limit: int,
    ) -> tuple[list[dict[str, str]], int]:
        nonlocal failed
        del transport, key, operation, call_limit
        if request_no == "request-2":
            failed = True
            raise RuntimeError
        return _delivery_group(request_no), 1

    monkeypatch.setattr(collect_video_sample, "_request_numbers", request_numbers)
    monkeypatch.setattr(collect_video_sample, "_option_group", first_attempt)
    args = collect_video_sample.Arguments()
    args.output = tmp_path

    with pytest.raises(RuntimeError):
        _ = collect_video_sample.collect_options(
            cast("HttpTransport", object()), "key", args, call_limit=10000
        )

    assert failed
    option_path = tmp_path / "video-surveillance-option-observations.jsonl"
    processed_path = tmp_path / "video-surveillance-processed-requests.txt"
    assert len(option_path.read_text(encoding="utf-8").splitlines()) == 1
    assert processed_path.read_text(encoding="utf-8").splitlines() == ["request-1"]

    def resumed_attempt(
        transport: HttpTransport,
        key: str,
        operation: Operation,
        request_no: str,
        call_limit: int,
    ) -> tuple[list[dict[str, str]], int]:
        del transport, key, operation, call_limit
        assert request_no == "request-2"
        return _delivery_group(request_no), 1

    monkeypatch.setattr(collect_video_sample, "_option_group", resumed_attempt)
    count, calls = collect_video_sample.collect_options(
        cast("HttpTransport", object()), "key", args, call_limit=10000
    )

    assert count == 2
    assert calls == 1
    assert processed_path.read_text(encoding="utf-8").splitlines() == requests


def _delivery_group(request_no: str) -> list[dict[str, str]]:
    return [
        {
            "dlvrReqNo": request_no,
            "optnDivCdNm": "대표품목",
            "prdctIdntNo": f"{request_no}-parent",
        },
        {
            "dlvrReqNo": request_no,
            "optnDivCdNm": "선택사양(별도구매)",
            "prdctIdntNo": f"{request_no}-option",
        },
    ]
