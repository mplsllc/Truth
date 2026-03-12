# Roadmap: Truth

## Overview

Truth delivers a fact-checked news aggregator in four phases following a strict dependency chain: ingest articles first, then fact-check them via local LLM, then score and display results, then layer on navigation and discovery features. Each phase delivers a verifiable capability that unblocks the next. The core differentiator -- LLM-powered credibility scoring -- ships in Phase 3, with everything before it building the pipeline that makes scoring possible.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation and Ingestion** - Project skeleton, database, Docker services, RSS polling, article extraction, and deduplication
- [ ] **Phase 2: Fact-Check Pipeline** - Ollama LLM integration for claim extraction, cross-reference verification, and async processing
- [ ] **Phase 3: Scoring and Core Display** - Composite credibility scoring, magazine-style UI with badges, fact-check detail views
- [ ] **Phase 4: Navigation and Discovery** - Category filtering, keyword search, and temporal browsing

## Phase Details

### Phase 1: Foundation and Ingestion
**Goal**: The system continuously ingests, extracts, and deduplicates news articles from RSS feeds into a working database
**Depends on**: Nothing (first phase)
**Requirements**: INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05
**Success Criteria** (what must be TRUE):
  1. New articles appear in the database within minutes of being published to configured RSS feeds
  2. Each stored article has complete metadata (title, image, date, author, source) and full article text, not just RSS summaries
  3. Duplicate stories covering the same event are detected and clustered rather than stored as separate entries
  4. A single broken or malformed RSS feed does not stop ingestion from all other feeds
  5. Docker Compose brings up the full environment (PostgreSQL, Ollama, FastAPI) with one command
**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md -- Project skeleton, Docker infrastructure, database models, seed data
- [ ] 01-02-PLAN.md -- RSS feed polling, metadata extraction, APScheduler integration
- [ ] 01-03-PLAN.md -- Full article content extraction (trafilatura + Playwright fallback)
- [ ] 01-04-PLAN.md -- Semantic deduplication, story clustering, end-to-end pipeline wiring

### Phase 2: Fact-Check Pipeline
**Goal**: Every ingested article is automatically fact-checked by a local LLM, with verifiable claims extracted and checked against cross-referenced sources
**Depends on**: Phase 1
**Requirements**: FACT-01, FACT-02, FACT-03, FACT-04, FACT-05
**Success Criteria** (what must be TRUE):
  1. Each article has its verifiable claims extracted and stored as structured data (not raw LLM output)
  2. Claims are verified against text from other articles covering the same event (RAG pattern), not LLM recall
  3. Each article receives an accuracy score based on how many claims were corroborated, contradicted, or unverifiable
  4. The full reasoning chain is stored for each fact-check (which claims, which sources, what verdict)
  5. Articles display immediately with a "pending" badge while awaiting fact-check, and the pipeline handles backpressure without unbounded queue growth
**Plans**: TBD

Plans:
- [ ] 02-01: TBD
- [ ] 02-02: TBD

### Phase 3: Scoring and Core Display
**Goal**: Users can browse a magazine-style news site where every story carries a transparent, multi-axis credibility score
**Depends on**: Phase 2
**Requirements**: SCORE-01, SCORE-02, SCORE-03, SCORE-04, PRES-01, PRES-03, PRES-04, PRES-07
**Success Criteria** (what must be TRUE):
  1. Each story card shows a credibility badge with the composite score and categorical label (e.g., "Well-Sourced", "Partially Verified") without requiring a click
  2. Users see sub-scores (accuracy, source reliability, freshness, coverage breadth) alongside the composite -- not just a single opaque number
  3. Clicking into a story reveals the full fact-check breakdown: which claims were checked, what sources confirmed or denied them, and the resulting verdicts
  4. The homepage displays stories in a magazine-style card layout with hero images, headlines, source badges, timestamps, and links to original articles
  5. Source reliability ratings are bootstrapped from external data (MBFC or similar) and refined over time based on accumulated fact-check results
**Plans**: TBD

Plans:
- [ ] 03-01: TBD
- [ ] 03-02: TBD

### Phase 4: Navigation and Discovery
**Goal**: Users can find specific stories through category filtering, keyword search, and temporal browsing
**Depends on**: Phase 3
**Requirements**: PRES-02, PRES-05, PRES-06
**Success Criteria** (what must be TRUE):
  1. Users can filter the story feed by category or topic (Politics, Tech, Sports, etc.)
  2. Users can search for stories by keyword and get relevant results
  3. Users can browse stories by time period (today, this week, etc.)
**Plans**: TBD

Plans:
- [ ] 04-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation and Ingestion | 1/4 | Executing | - |
| 2. Fact-Check Pipeline | 0/? | Not started | - |
| 3. Scoring and Core Display | 0/? | Not started | - |
| 4. Navigation and Discovery | 0/? | Not started | - |
