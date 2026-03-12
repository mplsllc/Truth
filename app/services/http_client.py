"""Rate-limited async HTTP client wrapping httpx."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger()

# Browser-mimicking User-Agent string (Chrome on Windows)
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


class RateLimitedClient:
    """Async HTTP client with per-domain rate limiting and concurrency cap.

    Args:
        max_concurrent: Maximum number of concurrent requests across all domains.
        per_domain_delay: Minimum seconds between requests to the same domain.
        timeout: Request timeout in seconds.
        proxy: Optional HTTP proxy URL.
    """

    def __init__(
        self,
        max_concurrent: int = 15,
        per_domain_delay: float = 2.0,
        timeout: float = 30.0,
        proxy: str | None = None,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._per_domain_delay = per_domain_delay
        self._domain_last_request: dict[str, float] = {}
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._timeout = timeout
        self._proxy = proxy
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> RateLimitedClient:
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": BROWSER_USER_AGENT},
            proxy=self._proxy,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        return urlparse(url).netloc.lower()

    def _get_domain_lock(self, domain: str) -> asyncio.Lock:
        """Get or create a lock for a domain."""
        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()
        return self._domain_locks[domain]

    async def _enforce_domain_delay(self, domain: str) -> None:
        """Wait if necessary to respect per-domain delay."""
        lock = self._get_domain_lock(domain)
        async with lock:
            now = time.monotonic()
            last = self._domain_last_request.get(domain, 0.0)
            elapsed = now - last
            if elapsed < self._per_domain_delay:
                wait_time = self._per_domain_delay - elapsed
                await asyncio.sleep(wait_time)
            self._domain_last_request[domain] = time.monotonic()

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Perform a rate-limited GET request.

        Args:
            url: The URL to fetch.
            **kwargs: Additional keyword arguments passed to httpx.get.

        Returns:
            httpx.Response object.
        """
        if self._client is None:
            raise RuntimeError(
                "Client not initialized. Use 'async with' context manager."
            )

        domain = self._get_domain(url)

        async with self._semaphore:
            await self._enforce_domain_delay(domain)
            return await self._client.get(url, **kwargs)


def get_http_client(
    max_concurrent: int = 15,
    per_domain_delay: float = 2.0,
    timeout: float = 30.0,
    proxy: str | None = None,
) -> RateLimitedClient:
    """Factory function to create a RateLimitedClient."""
    return RateLimitedClient(
        max_concurrent=max_concurrent,
        per_domain_delay=per_domain_delay,
        timeout=timeout,
        proxy=proxy,
    )
