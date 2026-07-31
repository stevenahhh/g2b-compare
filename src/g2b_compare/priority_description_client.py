"""Playwright session bootstrap and direct G2B description transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    Route,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)

from .priority_description_crawl import (
    DETAIL_ENDPOINT,
    FetchedDescriptionResponse,
    description_request_body,
    description_request_headers,
)

if TYPE_CHECKING:
    from types import TracebackType

    from .priority_description import ProductDetailTarget


@final
class ProductDescriptionBootstrapError(Exception):
    """The public G2B browser session could not be established."""


@final
class ProductDescriptionClientStateError(Exception):
    """The browser client was used outside its active context."""


@final
class G2bProductDescriptionClient:
    """One ephemeral public browser session with concurrent API requests."""

    def __init__(self, bootstrap_target: ProductDetailTarget) -> None:
        """Prepare a client that bootstraps through one collected page URL."""
        self.bootstrap_target = bootstrap_target
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> Self:
        """Start Chromium and establish the public SSO relay cookies."""
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch()
            self._context = await self._browser.new_context(locale="ko-KR")
            page = await self._context.new_page()
            _ = await page.route("**/*", _route_without_media)
            try:
                expected_response = page.expect_response(
                    lambda response: response.url == DETAIL_ENDPOINT,
                    timeout=60_000,
                )
                async with expected_response as response_info:
                    _ = await page.goto(
                        self.bootstrap_target.source_url,
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                _ = await response_info.value
            finally:
                await page.close()
        except (PlaywrightError, TimeoutError) as error:
            await self._close()
            reason = "public G2B description bootstrap failed"
            raise ProductDescriptionBootstrapError(reason) from error
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close every ephemeral browser resource without persisting cookies."""
        _ = (exc_type, exc_value, traceback)
        await self._close()

    async def fetch(
        self,
        target: ProductDetailTarget,
    ) -> FetchedDescriptionResponse:
        """Fetch one exact JSON response through the authenticated context."""
        if self._context is None:
            raise ProductDescriptionClientStateError
        response = await self._context.request.post(
            DETAIL_ENDPOINT,
            data=description_request_body(target),
            headers=description_request_headers(target),
            timeout=30_000,
        )
        return FetchedDescriptionResponse(
            http_status=response.status,
            content_type=response.headers.get("content-type", ""),
            body=await response.body(),
        )

    async def _close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


async def _route_without_media(route: Route) -> None:
    if route.request.resource_type in {"font", "image", "media"}:
        await route.abort()
    else:
        await route.continue_()
