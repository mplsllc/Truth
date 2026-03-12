---
phase: 01-foundation-and-ingestion
plan: 04
subsystem: ingestion, deduplication
tags: [sentence-transformers, pgvector, cosine-similarity, deduplication, clustering, pipeline, apscheduler]

# Dependency graph
requires:
  - phase: 01-02
    provides: Feed poller with ArticleCandidate, RateLimitedClient, APScheduler
  - phase: 01-03
    provides: Content extractor with trafilatura + Playwright fallback
provides:
  - Two-phase deduplication (URL hash + pgvector cosine similarity at 0.83 threshold)
  - Story clustering with opinion/news separation and trust-tier-based primary selection
  - End-to-end ingestion pipeline (poll -> extract -> dedup -> cluster -> store)
  - Scheduler integration running full pipeline every 5 minutes
affects: [02-01, 03-01]

# Tech tracking
tech-stack:
  added: []
  patterns: [two-phase dedup (URL hash + semantic embedding), fallback cosine similarity for SQLite tests, savepoint transaction isolation for tests]

key-files:
  created:
    - app/services/deduplicator.py
    - app/services/pipeline.py
    - tests/test_deduplicator.py
    - tests/test_pipeline.py
  modified:
    - app/models/cluster.py
    - app/tasks/scheduler.py
    - app/main.py
    - tests/conftest.py

key-decisions:
  - "Added is_opinion field to StoryCluster model for opinion/news cluster separation"
  - "Deduplicator accepts similarity_threshold parameter to avoid Settings dependency in tests"
  - "SQLite fallback similarity search computes cosine similarity in Python when pgvector unavailable"
  - "Pipeline commits handled by run_ingestion_cycle; scheduler creates fresh session per cycle"
  - "Test isolation improved with savepoint-based transaction wrapping via join_transaction_mode"

patterns-established:
  - "Two-phase dedup: URL hash O(1) check then embedding cosine similarity"
  - "Pipeline orchestrator pattern: sequential processing with graceful degradation"
  - "Trust tier ranking: HIGH=3 > MEDIUM=2 > LOW=1 for primary article promotion"
  - "Savepoint transaction isolation in tests with join_transaction_mode=create_savepoint"

requirements-completed: [INGEST-04, INGEST-01, INGEST-03]

# Metrics
duration: 10min
completed: 2026-03-12
---

# Phase 1 Plan 04: Deduplication and Pipeline Summary

**Two-phase deduplication (URL hash + 0.83 cosine similarity via pgvector) with opinion/news separation, trust-tier primary promotion, and full end-to-end pipeline wiring (poll -> extract -> dedup -> cluster -> store)**

## Performance

- **Duration:** 10 min
- **Started:** 2026-03-12T20:59:28Z
- **Completed:** 2026-03-12T21:09:25Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Two-phase deduplication service: URL hash catches exact duplicates in O(1), pgvector cosine similarity clusters same-event articles at 0.83 threshold
- Opinion pieces clustered separately from news coverage via is_opinion flag on StoryCluster
- Primary article in each cluster promoted by trust tier (HIGH > MEDIUM > LOW)
- Full end-to-end ingestion pipeline: poll feeds -> extract content -> deduplicate -> cluster -> store
- Content extraction failures degrade gracefully (article saved with RSS summary as content)
- Scheduler runs full pipeline every 5 minutes with fresh session per cycle
- 20 new tests (68 total) all passing with improved savepoint-based test isolation

## Task Commits

Each task was committed atomically (TDD for Task 1):

1. **Task 1 (RED): Failing deduplication tests** - `315dd3c` (test)
2. **Task 1 (GREEN): Two-phase deduplication implementation** - `ac9508b` (feat)
3. **Task 2: Pipeline wiring and scheduler integration** - `d44e90f` (feat)

## Files Created/Modified
- `app/services/deduplicator.py` - Two-phase dedup with URL hash + semantic similarity, trust tier promotion
- `app/services/pipeline.py` - End-to-end pipeline orchestrator (process_article, run_ingestion_cycle)
- `app/tasks/scheduler.py` - Updated to run full pipeline instead of poll-only
- `app/models/cluster.py` - Added is_opinion field for opinion/news separation
- `app/main.py` - Pass embed_model to scheduler
- `tests/test_deduplicator.py` - 13 tests covering URL dedup, semantic matching, trust tiers, opinion separation
- `tests/test_pipeline.py` - 7 tests covering pipeline processing, stats, graceful degradation
- `tests/conftest.py` - Improved test isolation with savepoint transactions

## Decisions Made
- Added `is_opinion` boolean to StoryCluster to enable opinion/news cluster separation (Rule 2: missing critical functionality for correctness)
- Made `similarity_threshold` a parameter on `deduplicate_article` and pipeline functions to avoid Settings dependency in tests (cleaner API, better testability)
- Implemented Python-side cosine similarity fallback for SQLite test environment (pgvector not available)
- Improved test isolation using `join_transaction_mode="create_savepoint"` so committed data within tests is properly rolled back

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added is_opinion field to StoryCluster model**
- **Found during:** Task 1 (deduplicator implementation)
- **Issue:** Plan specifies opinion/news cluster separation but StoryCluster had no is_opinion field
- **Fix:** Added `is_opinion: Mapped[bool]` to StoryCluster model with default False
- **Files modified:** app/models/cluster.py
- **Verification:** Opinion separation tests pass
- **Committed in:** ac9508b

**2. [Rule 3 - Blocking] Improved test isolation with savepoint transactions**
- **Found during:** Task 2 (running all tests together)
- **Issue:** Pipeline tests called session.commit() which persisted data across test boundaries in the session-scoped SQLite database, causing subsequent dedup tests to find stale clusters
- **Fix:** Updated conftest.py to use connection-level transactions with `join_transaction_mode="create_savepoint"` and mocked commit in pipeline tests
- **Files modified:** tests/conftest.py, tests/test_pipeline.py
- **Verification:** All 68 tests pass in any order
- **Committed in:** d44e90f

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 blocking)
**Impact on plan:** Both fixes essential for correctness and test reliability. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Full ingestion pipeline operational: poll -> extract -> dedup -> cluster -> store
- Articles stored with full metadata, content, wire/opinion flags, and cluster assignment
- Ready for Phase 2: Fact-Check Pipeline (articles can be queued for LLM processing)
- Story clusters provide the grouping needed for cross-reference verification in Phase 2

---
*Phase: 01-foundation-and-ingestion*
*Completed: 2026-03-12*
