---
phase: 01-foundation-and-ingestion
plan: 02
subsystem: ingestion, services
tags: [feedparser, httpx, apscheduler, asyncio, rss, rate-limiting, sentence-transformers]

# Dependency graph
requires:
  - phase: 01-01
    provides: Feed/Article/StoryCluster models, async session factory, Docker stack
provides:
  - Rate-limited async HTTP client with per-domain delay and concurrency cap
  - RSS feed polling orchestrator with per-feed error isolation and metadata extraction
  - APScheduler integration with interval trigger, overlap prevention, and lifespan wiring
  - URL normalization and SHA-256 deduplication for article URLs
  - GET /api/status endpoint for system health monitoring
  - sentence-transformers model loading at startup
affects: [01-03, 01-04, 02-01]

# Tech tracking
tech-stack:
  added: [feedparser, httpx, apscheduler, sentence-transformers]
  patterns: [per-domain rate limiting with asyncio.Lock, asyncio.gather with return_exceptions for error isolation, APScheduler max_instances=1 coalesce=True]

key-files:
  created:
    - app/services/__init__.py
    - app/services/http_client.py
    - app/services/feed_poller.py
    - app/api/__init__.py
    - app/api/deps.py
    - app/tasks/__init__.py
    - app/tasks/scheduler.py
    - tests/test_feed_poller.py
  modified:
    - app/main.py

key-decisions:
  - "Per-domain rate limiting uses asyncio.Lock per domain to serialize requests and enforce delay"
  - "URL normalization strips UTM/tracking params, fragments, trailing slashes before SHA-256 hashing"
  - "Scheduler uses next_run_time=now to trigger immediate first poll on startup"
  - "Embedding model load wrapped in try/except so app starts even if model download fails"

patterns-established:
  - "RateLimitedClient context manager for HTTP lifecycle management"
  - "ArticleCandidate dataclass as transfer object between polling and storage layers"
  - "asyncio.gather with return_exceptions=True for per-feed error isolation"
  - "Feed health tracking: status/error_count/last_error updated after every poll attempt"

requirements-completed: [INGEST-01, INGEST-02, INGEST-05]

# Metrics
duration: 5min
completed: 2026-03-12
---

# Phase 1 Plan 02: RSS Feed Polling Summary

**Rate-limited RSS poller with feedparser metadata extraction, per-feed error isolation, APScheduler 5-minute interval with overlap prevention, and /api/status endpoint**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-12T20:51:50Z
- **Completed:** 2026-03-12T20:56:22Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Rate-limited HTTP client (RateLimitedClient) with per-domain delay tracking, asyncio.Semaphore concurrency cap (15), browser-mimicking User-Agent, and optional proxy support
- RSS feed polling service extracting metadata (title, URL, summary, author, published_at, image_url) from feedparser entries with URL normalization and SHA-256 hash deduplication
- Per-feed error isolation via asyncio.gather(return_exceptions=True) with feed health tracking (status, error_count, last_error, last_polled_at)
- APScheduler AsyncIOScheduler with 5-minute interval, max_instances=1, coalesce=True preventing overlap
- sentence-transformers all-MiniLM-L6-v2 model loaded once at startup via lifespan
- GET /api/status endpoint reporting feed count, article count, scheduler state, and last poll time
- 13 new tests (48 total) all passing

## Task Commits

Each task was committed atomically:

1. **Task 1: Rate-limited HTTP client and RSS feed polling service** - `66513cc` (test) + `b606673` (feat)
2. **Task 2: APScheduler integration and lifespan wiring** - `f2aeb89` (feat)

## Files Created/Modified
- `app/services/__init__.py` - Package init
- `app/services/http_client.py` - RateLimitedClient with per-domain delay, concurrency cap, browser UA
- `app/services/feed_poller.py` - poll_single_feed, poll_all_feeds, ArticleCandidate, normalize_url
- `app/api/__init__.py` - Package init
- `app/api/deps.py` - FastAPI dependency functions (get_db, get_app_settings)
- `app/tasks/__init__.py` - Package init
- `app/tasks/scheduler.py` - create_scheduler with feed polling job, _run_feed_poll cycle
- `app/main.py` - Updated lifespan with scheduler start/stop, embed model loading, /api/status endpoint
- `tests/test_feed_poller.py` - 13 tests covering polling, metadata, health, rate limiting, URL normalization

## Decisions Made
- Per-domain rate limiting uses asyncio.Lock per domain to serialize requests and enforce the 2-second delay
- URL normalization strips UTM/tracking params, fragments, and trailing slashes before hashing
- Scheduler triggers immediate first poll on startup (next_run_time=now)
- Embedding model load is wrapped in try/except so the app can start even if the model is unavailable

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Feed polling infrastructure complete, ready for content extraction (Plan 01-03)
- Articles saved with metadata but without full content (content extraction is Plan 03)
- Embedding model loaded and available on app.state for deduplication (Plan 01-04)
- Status endpoint available for monitoring

## Self-Check: PASSED

All 8 created files verified on disk. All 3 commits (66513cc, b606673, f2aeb89) verified in git log.

---
*Phase: 01-foundation-and-ingestion*
*Completed: 2026-03-12*
