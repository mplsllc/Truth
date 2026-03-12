# Truth

## What This Is

A public-facing news aggregator that pulls stories from RSS feeds, Google News, and other sources, runs them through a local LLM (Ollama) to fact-check claims against both cross-referenced sources and known factual databases, then ranks and displays stories with a composite credibility score. Think Google News meets a fact-checker — a magazine-style news site where every story carries a trust rating.

## Core Value

Every story displayed has been fact-checked by an LLM, with a transparent composite score so readers can make informed judgments about what they're reading.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Aggregate news stories from RSS feeds, Google News, and other web sources
- [ ] Continuously poll and fetch new stories (every few minutes)
- [ ] Deduplicate stories covering the same event across sources
- [ ] Run each story through a local Ollama LLM for fact-checking
- [ ] Cross-reference claims across multiple sources reporting the same story
- [ ] Verify claims against known databases (Wikipedia, government data, etc.)
- [ ] Generate a composite score (accuracy, source reliability, freshness, coverage breadth)
- [ ] Display stories in a magazine-style card layout with images and categories
- [ ] Show fact-check scores and badges prominently on each story
- [ ] Public-facing site — no auth required to browse

### Out of Scope

- User accounts / authentication — public read-only site for v1
- User comments or social features — not a discussion platform
- Mobile app — web-first, responsive design sufficient
- Cloud LLM APIs — local Ollama only, no external API costs
- Original content creation — aggregation and analysis only

## Context

- Running on a local server with Ollama already available (or to be set up)
- Python backend (FastAPI or Django) for good LLM integration
- News magazine visual style — card layout with images, categories, visual richness
- Continuous ingestion means the system needs to handle background processing
- Fact-checking is the differentiator — the LLM pipeline is the core of the product

## Constraints

- **Infrastructure**: Must run on local server — no cloud LLM dependencies
- **LLM Runtime**: Ollama for local model inference
- **Backend**: Python (FastAPI or Django)
- **Processing**: Continuous feed polling requires robust background task handling
- **Performance**: Fact-checking via local LLM will have throughput limits — need to handle backpressure

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Local LLM via Ollama | Full control, no API costs, privacy | — Pending |
| Python backend | Best LLM ecosystem integration | — Pending |
| Composite scoring (accuracy + reliability + freshness + breadth) | Single score is too reductive | — Pending |
| Public site, no auth | Maximize reach, simplify v1 | — Pending |
| Continuous polling | Users expect fresh news | — Pending |

---
*Last updated: 2026-03-12 after initialization*
