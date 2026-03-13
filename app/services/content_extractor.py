"""Content extraction service using trafilatura with Playwright fallback.

Extracts full article text, metadata, and detects wire stories and
opinion/editorial content. Never raises exceptions -- all failures
return ExtractedContent with an error field.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime

import structlog
import trafilatura
from playwright.async_api import async_playwright

from app.services.http_client import BROWSER_USER_AGENT, RateLimitedClient

logger = structlog.get_logger(__name__)

# Concurrency cap for Playwright browser instances (per Pitfall 1 in RESEARCH.md)
_playwright_semaphore = asyncio.Semaphore(3)

# Minimum text length to consider extraction successful
MIN_CONTENT_LENGTH = 200

# Wire service detection patterns
_AP_TEXT_PATTERNS = [
    re.compile(r"^\s*\(AP\)\s*[—–-]", re.MULTILINE),
    re.compile(r"Associated Press", re.IGNORECASE),
]
_REUTERS_TEXT_PATTERNS = [
    re.compile(r"^\s*\(Reuters\)\s*[—–-]", re.MULTILINE),
]
_AP_URL_PATTERN = re.compile(r"apnews\.com", re.IGNORECASE)
_REUTERS_URL_PATTERN = re.compile(r"reuters\.com", re.IGNORECASE)

# Opinion URL path patterns
_OPINION_URL_PATTERNS = re.compile(
    r"/(?:opinion|editorial|commentary|op-ed|perspective)/",
    re.IGNORECASE,
)

# Opinion HTML meta patterns
_OPINION_META_PATTERN = re.compile(
    r'(?:article:section|og:type)["\s]*content=["\']?\s*opinion',
    re.IGNORECASE,
)


@dataclass
class ExtractedContent:
    """Result of content extraction from a URL."""

    text: str | None = None
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    image_url: str | None = None
    language: str | None = None
    is_opinion: bool = False
    is_wire_story: bool = False
    wire_source: str | None = None
    error: str | None = None
    method: str = "trafilatura"


def _clean_extracted_text(text: str) -> str:
    """Remove navigation/sidebar junk that trafilatura sometimes includes.

    Detects blocks of short lines that look like headline lists (e.g.
    'Top Stories\\n6 dead after...\\n30 minutes ago...') and truncates
    the article before them.
    """
    lines = text.split("\n")
    # Look for a sequence of 5+ consecutive short lines (< 100 chars)
    # that contain time markers like "ago" or date patterns — this signals
    # a headline listing, not article content.
    for i in range(len(lines) - 5):
        short_run = 0
        time_markers = 0
        for j in range(i, min(i + 10, len(lines))):
            line = lines[j].strip()
            if len(line) < 100:
                short_run += 1
                if re.search(r"\d+\s*(minutes?|hours?|days?)\s*ago", line, re.IGNORECASE):
                    time_markers += 1
            else:
                break
        if short_run >= 5 and time_markers >= 2:
            # Truncate before this listing block
            cleaned = "\n".join(lines[:i]).strip()
            if len(cleaned) >= MIN_CONTENT_LENGTH:
                return cleaned
    return text


def detect_wire_story(text: str, url: str) -> tuple[bool, str | None]:
    """Detect if content is a wire service story (AP, Reuters).

    Checks text patterns like "(AP) --" prefix, "Associated Press" byline,
    "(Reuters) --" prefix, and URL patterns for apnews.com / reuters.com.

    Returns:
        Tuple of (is_wire_story, source_name).
    """
    # Check AP text patterns
    for pattern in _AP_TEXT_PATTERNS:
        if pattern.search(text):
            return True, "AP"

    # Check Reuters text patterns
    for pattern in _REUTERS_TEXT_PATTERNS:
        if pattern.search(text):
            return True, "Reuters"

    # Check URL patterns
    if _AP_URL_PATTERN.search(url):
        return True, "AP"
    if _REUTERS_URL_PATTERN.search(url):
        return True, "Reuters"

    return False, None


def detect_opinion(url: str, html: str | None) -> bool:
    """Detect if content is an opinion or editorial piece.

    Checks URL path for opinion-related segments and HTML meta tags
    for opinion indicators.

    Args:
        url: The article URL.
        html: Raw HTML content (may be None).

    Returns:
        True if opinion signals are found.
    """
    # Check URL path
    if _OPINION_URL_PATTERNS.search(url):
        return True

    # Check HTML metadata
    if html and _OPINION_META_PATTERN.search(html):
        return True

    return False


def _parse_trafilatura_result(
    result_json: str | None,
    raw_html: str | None,
    url: str,
    method: str = "trafilatura",
) -> ExtractedContent | None:
    """Parse trafilatura JSON output into ExtractedContent.

    Returns None if the result is empty or text is too short.
    """
    if not result_json:
        return None

    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return None

    text = data.get("text", "")
    if not text or len(text) < MIN_CONTENT_LENGTH:
        return None
    text = _clean_extracted_text(text)

    # Parse publication date if present
    published_at = None
    date_str = data.get("date")
    if date_str:
        try:
            published_at = datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            pass

    # Detect wire story and opinion
    is_wire, wire_source = detect_wire_story(text, url)
    is_opinion = detect_opinion(url, raw_html)

    return ExtractedContent(
        text=text,
        title=data.get("title"),
        author=data.get("author"),
        published_at=published_at,
        image_url=data.get("image"),
        language=data.get("language"),
        is_opinion=is_opinion,
        is_wire_story=is_wire,
        wire_source=wire_source,
        error=None,
        method=method,
    )


async def _extract_with_playwright(url: str) -> ExtractedContent | None:
    """Attempt extraction using Playwright headless browser.

    Launches Chromium, navigates to URL with networkidle wait,
    extracts page HTML, then runs trafilatura on the rendered content.
    Concurrency is capped at 3 via asyncio.Semaphore.

    Returns None if extraction fails. Never raises exceptions.
    """
    async with _playwright_semaphore:
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(user_agent=BROWSER_USER_AGENT)
                    page = await context.new_page()
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    html = await page.content()
                    await context.close()
                finally:
                    await browser.close()

            # Run trafilatura on the rendered HTML
            result_json = trafilatura.extract(
                html,
                include_comments=False,
                include_images=True,
                output_format="json",
                with_metadata=True,
            )

            return _parse_trafilatura_result(result_json, html, url, method="playwright")

        except Exception as exc:
            logger.warning(
                "playwright_extraction_failed",
                url=url,
                error=str(exc),
            )
            return None


async def extract_content(
    url: str,
    http_client: RateLimitedClient,
) -> ExtractedContent:
    """Extract full article content from a URL.

    Uses a two-stage extraction strategy:
    1. Fetch HTML via http_client and extract with trafilatura (fast, lightweight).
    2. If trafilatura fails or returns insufficient content (<200 chars),
       fall back to Playwright headless browser.

    All failures return ExtractedContent with an error field -- this function
    never raises exceptions.

    Args:
        url: The article URL to extract content from.
        http_client: Rate-limited HTTP client for fetching.

    Returns:
        ExtractedContent with extracted text and metadata, or error info.
    """
    raw_html: str | None = None

    # Attempt 1: trafilatura on HTTP-fetched HTML
    try:
        response = await http_client.get(url)
        raw_html = response.text

        result_json = trafilatura.extract(
            raw_html,
            include_comments=False,
            include_images=True,
            output_format="json",
            with_metadata=True,
        )

        content = _parse_trafilatura_result(result_json, raw_html, url)
        if content is not None:
            logger.info(
                "content_extracted",
                url=url,
                method="trafilatura",
                text_length=len(content.text) if content.text else 0,
            )
            return content

    except Exception as exc:
        logger.warning(
            "trafilatura_extraction_failed",
            url=url,
            error=str(exc),
        )

    # Attempt 2: Playwright fallback
    logger.info("falling_back_to_playwright", url=url)
    content = await _extract_with_playwright(url)
    if content is not None:
        logger.info(
            "content_extracted",
            url=url,
            method="playwright",
            text_length=len(content.text) if content.text else 0,
        )
        return content

    # Both methods failed
    logger.error("extraction_failed", url=url)
    return ExtractedContent(
        error="extraction_failed",
        is_opinion=detect_opinion(url, raw_html),
    )
