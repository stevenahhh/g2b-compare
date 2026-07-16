"""Sanitized no-follow share-link preflight boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from g2b_compare.contracts.wire import Requester

SHOP_SHARE_PREFIX: Final = "https://shop.g2b.go.kr/"
REDIRECT_MIN: Final = 300
REDIRECT_MAX: Final = 400

type SharePreflightOutcome = Literal[
    "not-attempted",
    "candidate-rejected",
    "redirect-rejected",
    "unsupported-response",
]


class SharePreflightResult(BaseModel):
    """URL-free result from one bounded no-follow preflight."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    supported: Literal[False] = False
    outcome: SharePreflightOutcome
    status_code: int | None = None


def preflight_share_link(
    requester: Requester,
    candidate_url: str | None,
) -> SharePreflightResult:
    """Reject redirects without retaining their target or candidate URL."""
    if candidate_url is None:
        return SharePreflightResult(outcome="not-attempted")
    if not candidate_url.startswith(SHOP_SHARE_PREFIX):
        return SharePreflightResult(outcome="candidate-rejected")
    response = requester.get(candidate_url, params=(), follow_redirects=False)
    if REDIRECT_MIN <= response.status_code < REDIRECT_MAX:
        return SharePreflightResult(
            outcome="redirect-rejected",
            status_code=response.status_code,
        )
    return SharePreflightResult(
        outcome="unsupported-response",
        status_code=response.status_code,
    )
