---
phase: 01-foundation-and-ingestion
plan: 01
subsystem: infra, database
tags: [docker, postgresql, pgvector, fastapi, sqlalchemy, alembic, structlog, asyncpg]

# Dependency graph
requires: []
provides:
  - Docker Compose stack with PostgreSQL+pgvector, Ollama, Redis, FastAPI
  - Feed, Article, StoryCluster database models with async session factory
  - Alembic async migration with initial schema including HNSW index
  - 58 curated RSS seed feeds across 8 categories and 3 trust tiers
  - FastAPI app shell with /health endpoint, structlog JSON logging, CORS
  - Test infrastructure with SQLite async and 17 passing tests
affects: [01-02, 01-03, 01-04, 02-01, 03-01]

# Tech tracking
tech-stack:
  added: [fastapi, sqlalchemy, asyncpg, pgvector, alembic, structlog, pydantic-settings, uvicorn]
  patterns: [async-sessionmaker, mapped_column with Mapped types, lifespan context manager, multi-stage Dockerfile]

key-files:
  created:
    - docker-compose.yml
    - Dockerfile
    - requirements.txt
    - pyproject.toml
    - alembic.ini
    - alembic/env.py
    - alembic/versions/001_initial_schema.py
    - app/config.py
    - app/main.py
    - app/db/base.py
    - app/db/session.py
    - app/models/enums.py
    - app/models/feed.py
    - app/models/article.py
    - app/models/cluster.py
    - seed/feeds.json
    - tests/conftest.py
    - tests/test_models.py
  modified:
    - .gitignore

key-decisions:
  - "Python-side datetime defaults alongside server_default=func.now() for SQLite test compatibility"
  - "Vector(384) column type for all-MiniLM-L6-v2 embeddings with HNSW index"
  - "SQLite with aiosqlite for unit tests, swapping Vector columns to Text type at test time"
  - "58 curated RSS feeds covering wire services, major outlets, regional, tech, science, business, sports, entertainment, and opinion"

patterns-established:
  - "SQLAlchemy 2.0 mapped_column style with Mapped[type] annotations throughout"
  - "Async session factory via async_sessionmaker with get_db() generator"
  - "Pydantic BaseSettings with env_file .env and get_settings() function wrapper"
  - "structlog JSON logging configured in FastAPI lifespan"
  - "pgvector HNSW index on embedding columns for cosine similarity"

requirements-completed: [INGEST-01, INGEST-05]

# Metrics
duration: 10min
completed: 2026-03-12
---

# Phase 1 Plan 01: Project Skeleton Summary

**Docker Compose with 4 services (pgvector, Ollama, Redis, FastAPI), SQLAlchemy 2.0 async models (Feed/Article/StoryCluster) with pgvector HNSW embeddings, 58 curated RSS feeds, and structlog JSON logging**

## Performance

- **Duration:** 10 min
- **Started:** 2026-03-12T20:38:08Z
- **Completed:** 2026-03-12T20:48:15Z
- **Tasks:** 3
- **Files modified:** 21

## Accomplishments
- Docker Compose stack defining PostgreSQL+pgvector, Ollama, Redis, and FastAPI with healthchecks and restart policies
- Three database models (Feed, Article, StoryCluster) with correct foreign key relationships, enums, and pgvector Vector(384) embedding column with HNSW index
- Alembic async migration environment with initial schema creating all tables and pgvector extension
- 58 curated RSS feeds in seed file spanning wire services, major US/international outlets, regional papers, tech, science, business, sports, entertainment, and opinion sources
- FastAPI app shell with lifespan-managed seed loader, structlog JSON logging, CORS middleware, and /health endpoint
- Test infrastructure with SQLite async backend and 17 passing tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Docker Compose, Dockerfile, and project configuration** - `e6ac10f` (feat)
2. **Task 2: Database models, async session, and Alembic migration** - `e7a0167` (feat)
3. **Task 3: FastAPI app shell, seed data loader, and structlog** - `12d891c` (feat)

## Files Created/Modified
- `docker-compose.yml` - 4-service orchestration with healthchecks
- `Dockerfile` - Multi-stage build with Playwright Chromium
- `requirements.txt` - 24 pinned dependencies
- `pyproject.toml` - Project metadata and pytest async config
- `.env.example` - All required environment variables documented
- `.gitignore` - Python, Docker, IDE, and planning patterns
- `alembic.ini` - Async PostgreSQL migration configuration
- `alembic/env.py` - Async migration environment with model import
- `alembic/versions/001_initial_schema.py` - Initial tables, pgvector extension, HNSW index
- `app/config.py` - Pydantic BaseSettings with all app configuration
- `app/main.py` - FastAPI app with lifespan, seed loader, structlog, CORS, health endpoint
- `app/db/base.py` - SQLAlchemy DeclarativeBase
- `app/db/session.py` - Async engine (pool_size=20) and session factory
- `app/models/enums.py` - TrustTier, FeedStatus, ClusterStatus, FactCheckStatus
- `app/models/feed.py` - Feed model with trust tier and health tracking
- `app/models/article.py` - Article model with wire story detection and fact-check status
- `app/models/cluster.py` - StoryCluster model with Vector(384) embedding and HNSW index
- `seed/feeds.json` - 58 curated RSS feeds with trust tiers, categories, regions
- `tests/conftest.py` - Async SQLite fixtures with Vector-to-Text swap
- `tests/test_models.py` - 17 tests for enums, models, relationships, seed data

## Decisions Made
- Used Python-side `default=lambda: datetime.now(timezone.utc)` alongside `server_default=func.now()` for SQLite test compatibility
- Chose 384-dimension Vector for all-MiniLM-L6-v2 embeddings per RESEARCH.md recommendation
- SQLite + aiosqlite for unit tests with runtime Vector-to-Text column swap (avoids needing PostgreSQL for basic model tests)
- Curated 58 feeds (14 high trust, 36 medium trust, 8 low trust) covering 8 categories

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed server_default="now()" incompatible with SQLite**
- **Found during:** Task 3 (test execution)
- **Issue:** `server_default="now()"` as a string literal causes SQLite to store the literal "now()" instead of evaluating it, resulting in `ValueError: Invalid isoformat string: 'now()'` when SQLAlchemy tries to parse the datetime
- **Fix:** Added Python-side `default=lambda: datetime.now(timezone.utc)` and changed `server_default` to `func.now()` on all timestamp columns in Feed, Article, and StoryCluster models
- **Files modified:** `app/models/feed.py`, `app/models/article.py`, `app/models/cluster.py`
- **Verification:** All 17 tests pass
- **Committed in:** `12d891c` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential fix for test compatibility. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviation.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Docker Compose stack ready for `docker compose up` (requires `.env` with DB_PASSWORD and ADMIN_PASSWORD)
- Database models established as foundation for RSS polling (Plan 01-02)
- Seed feeds ready to load on first startup
- Alembic migration ready to run against PostgreSQL
- Test infrastructure in place for future plans

---
*Phase: 01-foundation-and-ingestion*
*Completed: 2026-03-12*
