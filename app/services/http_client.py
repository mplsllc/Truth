"""Minimal HTTP client stub for content extractor dependency.

This is a placeholder created by Plan 01-03. Plan 01-02 will provide
the full RateLimitedClient implementation with per-domain rate limiting.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class HttpResponse:
    """Simplified HTTP response wrapper."""

    status_code: int
    text: str
    url: str


class RateLimitedClient:
    """Minimal rate-limited HTTP client stub.

    Plan 01-02 provides the full implementation with per-domain
    rate limiting and concurrency control. This stub provides the
    interface that content_extractor.py depends on.
    """

    def __init__(self, proxy: str | None = None):
        self._client = httpx.AsyncClient(
            headers={"User-Agent": BROWSER_UA},
            follow_redirects=True,
            timeout=30.0,
            proxy=proxy,
        )

    async def get(self, url: str) -> HttpResponse:
        """Fetch a URL and return simplified response."""
        resp = await self._client.get(url)
        return HttpResponse(
            status_code=resp.status_code,
            text=resp.text,
            url=str(resp.url),
        )

    async def close(self):
        """Close the underlying client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
