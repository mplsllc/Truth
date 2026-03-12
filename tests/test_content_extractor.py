"""Tests for content extraction service.

Tests cover trafilatura primary extraction, Playwright fallback,
wire service detection, opinion/editorial detection, and error handling.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.content_extractor import (
    ExtractedContent,
    detect_opinion,
    detect_wire_story,
    extract_content,
)
from app.services.http_client import HttpResponse, RateLimitedClient

# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

ARTICLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Scientists Discover New Species in Amazon Rainforest</title>
    <meta property="og:type" content="article" />
    <meta property="article:author" content="Jane Smith" />
    <meta property="article:published_time" content="2026-03-12T10:00:00Z" />
    <meta property="og:image" content="https://example.com/images/species.jpg" />
</head>
<body>
    <nav><a href="/">Home</a><a href="/science">Science</a></nav>
    <article>
        <h1>Scientists Discover New Species in Amazon Rainforest</h1>
        <p class="byline">By Jane Smith</p>
        <p>A team of researchers from the University of São Paulo has discovered
        a previously unknown species of tree frog in the Amazon rainforest. The
        discovery was made during a three-month expedition to a remote area of
        the Brazilian state of Amazonas.</p>
        <p>The new species, tentatively named Hyloscirtus amazonia, was found
        living in the canopy of tall trees at elevations between 500 and 800
        meters. The frog is distinctive for its bright blue coloring and unusual
        call pattern, which researchers describe as resembling a series of
        rapid clicks followed by a sustained whistle.</p>
        <p>"This discovery highlights how much biodiversity remains to be
        catalogued in the Amazon," said lead researcher Dr. Maria Santos.
        "We estimate that thousands of species in this region have yet to
        be formally described by science."</p>
        <p>The research team collected several specimens and tissue samples
        for genetic analysis, which confirmed the frog represents a new
        species within the Hyloscirtus genus. The findings have been submitted
        for publication in the journal Nature Ecology and Evolution.</p>
    </article>
    <footer>
        <p>Copyright 2026 Science Daily</p>
        <nav><a href="/about">About</a><a href="/contact">Contact</a></nav>
    </footer>
</body>
</html>
"""

BOILERPLATE_HEAVY_HTML = """
<!DOCTYPE html>
<html>
<head><title>Important News Story</title></head>
<body>
    <header>
        <nav>
            <a href="/">Home</a><a href="/news">News</a>
            <a href="/sports">Sports</a><a href="/weather">Weather</a>
        </nav>
        <div class="ad-banner">ADVERTISEMENT: Buy Product X!</div>
    </header>
    <aside class="sidebar">
        <h3>Trending Stories</h3>
        <ul><li>Story 1</li><li>Story 2</li><li>Story 3</li></ul>
        <div class="ad">Another ad here</div>
    </aside>
    <article>
        <h1>Important News Story</h1>
        <p>The city council voted unanimously to approve the new budget plan
        for the fiscal year 2027. The plan includes increased funding for
        public schools, infrastructure improvements, and a new community
        center in the downtown area.</p>
        <p>Council members debated the plan for several hours before reaching
        a consensus. The budget allocates $50 million for school renovations,
        $30 million for road repairs, and $15 million for the community
        center project.</p>
        <p>Mayor Johnson praised the council's decision, calling it a
        historic investment in the city's future. Opposition groups had
        argued for lower spending, but the council determined that the
        investments were necessary.</p>
    </article>
    <footer>
        <div class="newsletter">Sign up for our newsletter!</div>
        <p>Copyright 2026 Local News Inc.</p>
        <nav><a href="/privacy">Privacy</a><a href="/terms">Terms</a></nav>
    </footer>
</body>
</html>
"""

JS_HEAVY_HTML = """
<!DOCTYPE html>
<html>
<head><title>JS App</title></head>
<body>
    <div id="root"></div>
    <script>document.getElementById('root').innerHTML = 'Loading...';</script>
</body>
</html>
"""

AP_WIRE_HTML = """
<!DOCTYPE html>
<html>
<head><title>AP News: Major Event</title></head>
<body>
<article>
    <h1>Major Event Unfolds in Washington</h1>
    <p>(AP) — A major policy shift was announced today by government
    officials in Washington. The new regulations will affect millions
    of Americans and are expected to take effect within the next 90 days.</p>
    <p>Officials said the changes were necessary to address growing
    concerns about economic stability. The announcement came after
    weeks of behind-the-scenes negotiations between lawmakers.</p>
    <p>Critics of the policy say it does not go far enough, while
    supporters argue it strikes the right balance between reform
    and stability.</p>
</article>
</body>
</html>
"""

REUTERS_WIRE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Reuters: Market Update</title></head>
<body>
<article>
    <h1>Global Markets Rally on Trade Deal</h1>
    <p>(Reuters) — Global stock markets rallied sharply on Tuesday after
    the announcement of a new trade agreement between major economies.
    The deal is expected to reduce tariffs on hundreds of products.</p>
    <p>Markets in Asia and Europe posted gains of 2-3 percent, with
    technology stocks leading the advance. Analysts said the deal
    removed a significant source of uncertainty for investors.</p>
</article>
</body>
</html>
"""

OPINION_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Why We Need Better Climate Policy</title>
    <meta property="og:type" content="article" />
    <meta property="article:section" content="Opinion" />
</head>
<body>
<article>
    <h1>Opinion: Why We Need Better Climate Policy</h1>
    <p>The current approach to climate change is fundamentally flawed.
    After decades of incremental policy changes, we need bold action
    to address the growing threat of environmental catastrophe.</p>
    <p>I believe that market-based solutions alone will not be sufficient
    to reduce carbon emissions at the pace required by scientific
    consensus. Government intervention is necessary to accelerate
    the transition to renewable energy.</p>
    <p>Critics may argue that aggressive climate policy will harm the
    economy, but the cost of inaction far outweighs the investment
    required for a green transition.</p>
</article>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helper to create mock http_client
# ---------------------------------------------------------------------------


def make_mock_client(html: str, status_code: int = 200) -> RateLimitedClient:
    """Create a mock RateLimitedClient that returns given HTML."""
    client = AsyncMock(spec=RateLimitedClient)
    client.get = AsyncMock(
        return_value=HttpResponse(
            status_code=status_code,
            text=html,
            url="https://example.com/article",
        )
    )
    return client


# ---------------------------------------------------------------------------
# Tests: Trafilatura primary extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_content_returns_clean_text_and_metadata():
    """extract_content with well-formed HTML returns clean text, title, author, date, and image."""
    client = make_mock_client(ARTICLE_HTML)
    result = await extract_content("https://example.com/article", client)

    assert isinstance(result, ExtractedContent)
    assert result.error is None
    assert result.text is not None
    assert len(result.text) > 200
    assert "tree frog" in result.text
    assert result.title is not None
    assert "Species" in result.title or "Amazon" in result.title
    assert result.method == "trafilatura"


@pytest.mark.asyncio
async def test_extract_content_strips_boilerplate():
    """extract_content strips boilerplate (navigation, ads, footer) from extracted text."""
    client = make_mock_client(BOILERPLATE_HEAVY_HTML)
    result = await extract_content("https://example.com/article", client)

    assert result.text is not None
    # Should contain article content
    assert "city council" in result.text.lower() or "budget" in result.text.lower()
    # Should NOT contain nav/ad/footer boilerplate
    assert "ADVERTISEMENT" not in result.text
    assert "Sign up for our newsletter" not in result.text
    assert "Privacy" not in result.text or "Terms" not in result.text


@pytest.mark.asyncio
async def test_extract_content_returns_text_longer_than_200_chars():
    """extract_content returns extracted text longer than 200 chars for real article HTML."""
    client = make_mock_client(ARTICLE_HTML)
    result = await extract_content("https://example.com/article", client)

    assert result.text is not None
    assert len(result.text) > 200


# ---------------------------------------------------------------------------
# Tests: Playwright fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_content_falls_back_to_playwright_when_trafilatura_returns_short_text():
    """extract_content falls back to Playwright when trafilatura returns None or text < 200 chars."""
    # JS-heavy page with no real content for trafilatura
    client = make_mock_client(JS_HEAVY_HTML)

    # Mock Playwright to return the full article HTML after JS rendering
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value=ARTICLE_HTML)
    mock_page.goto = AsyncMock()
    mock_page.close = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_chromium = AsyncMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw = AsyncMock()
    mock_pw.chromium = mock_chromium

    mock_pw_ctx = AsyncMock()
    mock_pw_ctx.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_pw_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.services.content_extractor.async_playwright",
        return_value=mock_pw_ctx,
    ):
        result = await extract_content("https://example.com/js-app", client)

    assert result.method == "playwright"
    assert result.text is not None
    assert len(result.text) > 200


@pytest.mark.asyncio
async def test_extract_content_falls_back_to_playwright_when_trafilatura_fails():
    """extract_content falls back to Playwright when trafilatura extraction fails entirely."""
    # Return HTML that trafilatura can't extract from
    empty_html = "<html><body></body></html>"
    client = make_mock_client(empty_html)

    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value=ARTICLE_HTML)
    mock_page.goto = AsyncMock()
    mock_page.close = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_chromium = AsyncMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw = AsyncMock()
    mock_pw.chromium = mock_chromium

    mock_pw_ctx = AsyncMock()
    mock_pw_ctx.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_pw_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.services.content_extractor.async_playwright",
        return_value=mock_pw_ctx,
    ):
        result = await extract_content("https://example.com/empty", client)

    assert result.method == "playwright"
    assert result.text is not None


@pytest.mark.asyncio
async def test_extract_content_playwright_timeout_returns_error():
    """extract_content with Playwright timeout returns error result (does not raise)."""
    # trafilatura will fail on empty HTML, triggering Playwright fallback
    empty_html = "<html><body></body></html>"
    client = make_mock_client(empty_html)

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(side_effect=TimeoutError("Navigation timeout"))
    mock_page.close = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_chromium = AsyncMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw = AsyncMock()
    mock_pw.chromium = mock_chromium

    mock_pw_ctx = AsyncMock()
    mock_pw_ctx.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_pw_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.services.content_extractor.async_playwright",
        return_value=mock_pw_ctx,
    ):
        result = await extract_content("https://example.com/timeout", client)

    # Should return error, not raise
    assert isinstance(result, ExtractedContent)
    assert result.error is not None
    assert result.text is None


@pytest.mark.asyncio
async def test_extract_content_both_methods_fail_returns_error():
    """extract_content returns ExtractedContent with error field when both methods fail."""
    empty_html = "<html><body></body></html>"
    client = make_mock_client(empty_html)

    # Playwright also returns empty content
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value=empty_html)
    mock_page.goto = AsyncMock()
    mock_page.close = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_chromium = AsyncMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw = AsyncMock()
    mock_pw.chromium = mock_chromium

    mock_pw_ctx = AsyncMock()
    mock_pw_ctx.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_pw_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.services.content_extractor.async_playwright",
        return_value=mock_pw_ctx,
    ):
        result = await extract_content("https://example.com/broken", client)

    assert isinstance(result, ExtractedContent)
    assert result.error is not None
    assert result.text is None


# ---------------------------------------------------------------------------
# Tests: Wire service detection
# ---------------------------------------------------------------------------


def test_detect_wire_story_ap_prefix():
    """detect_wire_story identifies AP wire stories from (AP) prefix."""
    text = "(AP) — A major policy shift was announced today."
    is_wire, source = detect_wire_story(text, "https://example.com/article")
    assert is_wire is True
    assert source == "AP"


def test_detect_wire_story_reuters_prefix():
    """detect_wire_story identifies Reuters wire stories from (Reuters) prefix."""
    text = "(Reuters) — Global markets rallied sharply on Tuesday."
    is_wire, source = detect_wire_story(text, "https://example.com/article")
    assert is_wire is True
    assert source == "Reuters"


def test_detect_wire_story_associated_press_byline():
    """detect_wire_story identifies AP stories from 'Associated Press' byline."""
    text = "By The Associated Press\n\nThe president signed the bill today."
    is_wire, source = detect_wire_story(text, "https://example.com/article")
    assert is_wire is True
    assert source == "AP"


def test_detect_wire_story_apnews_url():
    """detect_wire_story identifies AP from apnews.com URL."""
    text = "Some article text without wire markers."
    is_wire, source = detect_wire_story(text, "https://apnews.com/article/some-story")
    assert is_wire is True
    assert source == "AP"


def test_detect_wire_story_reuters_url():
    """detect_wire_story identifies Reuters from reuters.com URL."""
    text = "Some article text without wire markers."
    is_wire, source = detect_wire_story(text, "https://www.reuters.com/world/some-story")
    assert is_wire is True
    assert source == "Reuters"


def test_detect_wire_story_not_wire():
    """detect_wire_story returns False for non-wire content."""
    text = "The local school board voted to approve the new curriculum."
    is_wire, source = detect_wire_story(text, "https://localnews.com/article")
    assert is_wire is False
    assert source is None


# ---------------------------------------------------------------------------
# Tests: Opinion/editorial detection
# ---------------------------------------------------------------------------


def test_detect_opinion_from_url_path():
    """detect_opinion detects opinion from URL path patterns."""
    assert detect_opinion("https://example.com/opinion/climate-change", None) is True
    assert detect_opinion("https://example.com/editorial/budget-plan", None) is True
    assert detect_opinion("https://example.com/commentary/politics", None) is True
    assert detect_opinion("https://example.com/op-ed/tax-reform", None) is True
    assert detect_opinion("https://example.com/perspective/economy", None) is True


def test_detect_opinion_from_html_metadata():
    """detect_opinion detects opinion from HTML meta tags."""
    assert detect_opinion("https://example.com/article", OPINION_HTML) is True


def test_detect_opinion_returns_false_for_news():
    """detect_opinion returns False for regular news content."""
    assert detect_opinion("https://example.com/news/event", ARTICLE_HTML) is False
    assert detect_opinion("https://example.com/article/story", None) is False


# ---------------------------------------------------------------------------
# Tests: Integration - wire and opinion in extract_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_content_detects_wire_story():
    """extract_content detects wire service origin from content patterns."""
    client = make_mock_client(AP_WIRE_HTML)
    result = await extract_content("https://example.com/article", client)

    assert result.is_wire_story is True
    assert result.wire_source == "AP"


@pytest.mark.asyncio
async def test_extract_content_detects_opinion():
    """extract_content detects opinion/editorial pieces from HTML metadata or URL patterns."""
    client = make_mock_client(OPINION_HTML)
    result = await extract_content(
        "https://example.com/opinion/climate-change", client
    )

    assert result.is_opinion is True
