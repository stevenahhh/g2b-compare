from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, ClassVar, Final, Literal, Self, final

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

from g2b_compare.ranking.features import PAIR_FEATURE_CACHE_MAXSIZE

if TYPE_CHECKING:
    from g2b_compare.services.comparator_models import ComparatorView, ProductRecord
    from g2b_compare.services.release_models import ReleasePin
    from g2b_compare.services.search_models import (
        CategoryRef,
        SearchReader,
        SearchResponse,
    )

type PerfProductId = Annotated[
    str,
    StringConstraints(pattern=r"^PERF-002-\d{3}$"),
]
COMPARATOR_CONTRACT: Final = "comparator-contract"
RESULT_COUNT: Final = "result-count"
CACHE_HIT_COUNT: Final = "cache-hit-count"
THREADS: Final = (
    ("PYTHONHASHSEED", "0"),
    ("OMP_NUM_THREADS", "1"),
    ("MKL_NUM_THREADS", "1"),
    ("OPENBLAS_NUM_THREADS", "1"),
)
CACHE_POLICY: Final = (
    ("comparator-result-cache-hit-lane", True),
    ("comparator-result-cache-search-lane", False),
    ("pair-feature-memoization", "exact-pure-lru"),
    ("pair-feature-memoization-maxsize", PAIR_FEATURE_CACHE_MAXSIZE),
)


class ComparatorContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    anchor_id: PerfProductId
    rank: int
    status: Literal["ok"]
    candidate_id: PerfProductId


class ResultContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    product_id: PerfProductId
    comparators: tuple[
        ComparatorContract,
        ComparatorContract,
        ComparatorContract,
    ]

    @model_validator(mode="after")
    def require_exact_comparators(self) -> Self:
        ranks = tuple(slot.rank for slot in self.comparators)
        anchors = {slot.anchor_id for slot in self.comparators}
        candidates = {slot.candidate_id for slot in self.comparators}
        if (
            ranks != (1, 2, 3)
            or anchors != {self.product_id}
            or self.product_id in candidates
            or len(candidates) != 3
        ):
            raise PydanticCustomError(
                COMPARATOR_CONTRACT,
                COMPARATOR_CONTRACT,
            )
        return self


class SearchContract(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok"]
    total_results: Literal[60]
    page_size: Literal[50]
    cache_hits: int
    results: tuple[ResultContract, ...]

    @model_validator(mode="after")
    def require_exact_page(self) -> Self:
        product_ids = {result.product_id for result in self.results}
        if len(self.results) != 50 or len(product_ids) != 50:
            raise PydanticCustomError(RESULT_COUNT, RESULT_COUNT)
        if self.cache_hits not in {0, 50}:
            raise PydanticCustomError(CACHE_HIT_COUNT, CACHE_HIT_COUNT)
        return self


@final
class ObservedReader:
    __slots__ = ("_cache_hits", "_reader")

    def __init__(self, reader: SearchReader) -> None:
        self._reader = reader
        self._cache_hits = 0

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    def pin_active_release(self) -> ReleasePin:
        return self._reader.pin_active_release()

    def is_stale(self, pin: ReleasePin) -> bool:
        return self._reader.is_stale(pin)

    def categories(self, pin: ReleasePin) -> tuple[CategoryRef, ...]:
        return self._reader.categories(pin)

    def exact_products(
        self,
        pin: ReleasePin,
        product_name: str,
    ) -> tuple[ProductRecord, ...]:
        return self._reader.exact_products(pin, product_name)

    def cached_comparators(
        self,
        pin: ReleasePin,
        anchor_id: str,
    ) -> tuple[ComparatorView, ...] | None:
        slots = self._reader.cached_comparators(pin, anchor_id)
        if slots is not None:
            self._cache_hits += 1
        return slots


def contract_from_response(
    response: SearchResponse,
    cache_hits: int,
) -> SearchContract:
    return SearchContract.model_validate(
        {
            "status": response.status,
            "total_results": response.total_results,
            "page_size": response.page_size,
            "cache_hits": cache_hits,
            "results": [
                {
                    "product_id": result.product.rankable.product_id,
                    "comparators": [
                        {
                            "anchor_id": slot.anchor_id,
                            "rank": slot.rank,
                            "status": slot.status,
                            "candidate_id": (
                                ""
                                if slot.candidate is None
                                else slot.candidate.rankable.product_id
                            ),
                        }
                        for slot in result.comparators
                    ],
                }
                for result in response.results
            ],
        }
    )
