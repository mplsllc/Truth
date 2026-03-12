# Requirements: Truth

**Defined:** 2026-03-12
**Core Value:** Every story displayed has been fact-checked by an LLM, with a transparent composite score so readers can make informed judgments about what they're reading.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Ingestion

- [ ] **INGEST-01**: System continuously polls 50+ curated RSS feeds for new articles
- [ ] **INGEST-02**: System extracts article metadata (title, image, publication date, author, source, summary) from each feed item
- [ ] **INGEST-03**: System extracts full article content from URLs when RSS provides only summaries
- [ ] **INGEST-04**: System deduplicates stories covering the same event using near-match detection
- [ ] **INGEST-05**: System handles malformed RSS feeds gracefully without crashing the polling loop

### Fact-Checking

- [ ] **FACT-01**: System extracts verifiable claims from each article using local Ollama LLM
- [ ] **FACT-02**: System fact-checks extracted claims against cross-referenced sources covering the same event
- [ ] **FACT-03**: System generates an accuracy score for each article based on claim verification results
- [ ] **FACT-04**: System stores and displays the reasoning chain for each fact-check (which claims were checked, what sources confirmed/denied them)
- [ ] **FACT-05**: System processes articles through the fact-check pipeline asynchronously with backpressure handling

### Scoring

- [ ] **SCORE-01**: System assigns source reliability ratings using external data (MBFC or similar)
- [ ] **SCORE-02**: System calculates a composite score from four axes: accuracy, source reliability, freshness, coverage breadth
- [ ] **SCORE-03**: System tracks source reliability over time based on accumulated fact-check results
- [ ] **SCORE-04**: System displays sub-scores alongside the composite score (not just a single number)

### Presentation

- [ ] **PRES-01**: User can browse stories in a magazine-style card layout with hero images, headlines, source badges, and timestamps
- [ ] **PRES-02**: User can filter stories by category/topic (Politics, Tech, Sports, etc.)
- [ ] **PRES-03**: User can see credibility badges and composite scores prominently on each story card
- [ ] **PRES-04**: User can click into a story to see the full fact-check breakdown and reasoning
- [ ] **PRES-05**: User can search for specific stories by keyword
- [ ] **PRES-06**: User can browse stories by recency (today, this week, etc.)
- [ ] **PRES-07**: Each story card links to the original source article

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Ingestion

- **INGEST-06**: System integrates Google News RSS as supplementary source
- **INGEST-07**: System performs full semantic story clustering (beyond near-match dedup)

### Advanced Fact-Checking

- **FACT-06**: System verifies claims against external databases (Wikipedia API, government data)
- **FACT-07**: System detects "developing story" status and flags stories as not yet fully verified

### Advanced Presentation

- **PRES-08**: System provides topic trend detection and tracking
- **PRES-09**: System offers an API for third-party consumption of credibility scores
- **PRES-10**: System supports PWA installation for mobile

## Out of Scope

| Feature | Reason |
|---------|--------|
| User accounts / authentication | Public read-only site; auth adds scope with no v1 value |
| Comments / discussion | Moderation burden; contradicts fact-focused mission |
| Political bias scoring | Subjective and politically toxic; focus on factual accuracy |
| Paywall bypass / full article hosting | Copyright infringement risk |
| Cloud LLM APIs | Must run locally via Ollama; no external API costs |
| Mobile app | Responsive web sufficient; separate codebase not justified |
| Push notifications | Breaking news is least fact-checked; contradicts core value |
| User-submitted fact-check requests | Different product; opens to abuse |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INGEST-01 | Phase 1 | In Progress (01-01: models + seed data) |
| INGEST-02 | Phase 1 | Pending |
| INGEST-03 | Phase 1 | Pending |
| INGEST-04 | Phase 1 | Pending |
| INGEST-05 | Phase 1 | In Progress (01-01: Feed model with error tracking) |
| FACT-01 | Phase 2 | Pending |
| FACT-02 | Phase 2 | Pending |
| FACT-03 | Phase 2 | Pending |
| FACT-04 | Phase 2 | Pending |
| FACT-05 | Phase 2 | Pending |
| SCORE-01 | Phase 3 | Pending |
| SCORE-02 | Phase 3 | Pending |
| SCORE-03 | Phase 3 | Pending |
| SCORE-04 | Phase 3 | Pending |
| PRES-01 | Phase 3 | Pending |
| PRES-02 | Phase 4 | Pending |
| PRES-03 | Phase 3 | Pending |
| PRES-04 | Phase 3 | Pending |
| PRES-05 | Phase 4 | Pending |
| PRES-06 | Phase 4 | Pending |
| PRES-07 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 21
- Unmapped: 0

---
*Requirements defined: 2026-03-12*
*Last updated: 2026-03-12 after roadmap creation*
