# CLAUDE.md — AI News Aggregator

This file provides guidance for AI assistants working in this codebase.

---

## Project Overview

A multi-stage LLM pipeline that ingests AI news from RSS feeds and YouTube, generates structured insights, publishes blog posts, and delivers an email digest. Designed to run daily via GitHub Actions on a Neon Postgres + Groq + AWS SES stack.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11–3.12 |
| Package manager | `uv` (NOT pip/poetry) |
| Database | Neon Postgres (pgvector) via SQLAlchemy |
| LLM | Groq API (`llama-3.3-70b-versatile`) |
| Embeddings | `all-MiniLM-L6-v2` (sentence-transformers, 384-dim) |
| Agent framework | LangGraph `create_react_agent` (ReAct) |
| Email | AWS SES via boto3 |
| CI/CD | GitHub Actions |

---

## Repository Structure

```
ai-news-aggregator/
├── main.py                        # CLI entry point — runs pipeline stages
├── pyproject.toml                 # Dependencies (uv)
├── uv.lock                        # Locked dependency versions
├── Dockerfile                     # Container image (python:3.11-slim + uv)
├── docker-compose.yml             # Single-service orchestration
├── .env.example                   # Required environment variables template
├── .github/workflows/
│   ├── ci.yml                     # Import validation on push/PR to main
│   └── daily.yml                  # Full pipeline cron (6 AM UTC)
├── app/
│   ├── config.py                  # RSS feeds, YouTube channels, lookback window
│   ├── db/
│   │   ├── connection.py          # SQLAlchemy engine + session context manager
│   │   ├── schema.py              # Table definitions (SQLAlchemy ORM)
│   │   ├── models.py              # Pydantic models (Article, ArticleImage)
│   │   └── repository.py         # ArticleRepository (insert/query)
│   ├── ingestion/
│   │   ├── run.py                 # Entry: scrape RSS + YouTube → DB
│   │   ├── rss_scraper.py         # feedparser-based RSS scraper
│   │   ├── youtube_scraper.py     # youtube-transcript-api scraper
│   │   ├── base.py                # BaseScraper interface
│   │   └── deduplicator.py        # URL-based deduplication
│   ├── embeddings/
│   │   ├── embed_service.py       # Entry: embed unembedded articles
│   │   └── vector_store.py        # pgvector upsert + similarity search
│   ├── llm/
│   │   ├── groq_client.py         # Groq wrapper (JSON mode, retry/backoff)
│   │   ├── summarizer.py          # Stage 1: article → structured summary
│   │   ├── theme_grouper.py       # Stage 2: summaries → theme clusters
│   │   └── synthesizer.py         # Stage 3: themes → insights (non-agentic)
│   ├── agent/
│   │   ├── agent_loop.py          # Stage 3 (agentic): LangGraph ReAct loop
│   │   └── mcp_server.py          # FastMCP server exposing RAG tools
│   ├── publishing/
│   │   └── blog_generator.py      # Stage 4: insights → Markdown blog + Mermaid
│   ├── eval/
│   │   └── evaluator.py           # Stage 4: schema/coherence/novelty checks
│   └── notifications/
│       └── email_sender.py        # Stage 5: AWS SES email digest
├── scripts/
│   └── test_setup.py              # Integration check (DB + Groq)
└── tests/
    └── test_setup.py              # Setup verification (not unit tests)
```

---

## Pipeline Stages

Run stages with: `uv run python main.py <stage>`

| Stage | Module entry point | Function | Description |
|---|---|---|---|
| `ingest` | `app/ingestion/run.py` | `run()` | Scrape RSS + YouTube, deduplicate, store |
| `embed` | `app/embeddings/embed_service.py` | `run()` | Generate 384-dim vectors for new articles |
| `summarize` | `app/llm/summarizer.py` | `run()` | Stage 1: structured article summaries (Groq JSON) |
| `group` | `app/llm/theme_grouper.py` | `run()` | Stage 2: cluster articles into semantic themes |
| `synthesize` | `app/llm/synthesizer.py` | `run()` | Stage 3: insights per theme (direct LLM) |
| `agent` | `app/agent/agent_loop.py` | `run()` | Stage 3 (agentic): ReAct agent with RAG tools |
| `blog` | `app/publishing/blog_generator.py` | `run()` | Stage 4: Markdown blog posts with Mermaid diagrams |
| `eval` | `app/eval/evaluator.py` | `run()` | Stage 4: schema + coherence + novelty validation |
| `email` | `app/notifications/email_sender.py` | `run()` | Stage 5: AWS SES digest (dry-run if no credentials) |

**Convention:** Every pipeline module must expose a `run()` function (no other name). `main.py` and the CI workflow both import `run` from each module — using `main()` or `run_batch()` will break the pipeline and CI.

---

## Database Schema

All tables live in Neon Postgres with pgvector enabled.

| Table | Key columns | Notes |
|---|---|---|
| `articles` | `id` (UUID), `url` (UNIQUE), `title`, `raw_content`, `source_type`, `published_at` | Deduplication on `url` |
| `article_embeddings` | `article_id` (FK), `embedding` (pgvector 384-dim) | HNSW index for cosine similarity |
| `article_summaries` | `article_id` (FK), `summary_json` (JSONB) | Stage 1 output |
| `themes` | `batch_id`, `theme_json` (JSONB) | Stage 2 output |
| `insights` | `batch_id`, `insight_json` (JSONB) | Stage 3 output |
| `blog_posts` | `batch_id`, `slug`, `markdown`, `meta` (JSONB) | Stage 4 output |
| `eval_logs` | `batch_id`, `stage`, `eval_type`, `score`, `latency_ms` | Quality metrics |
| `email_logs` | `batch_id`, `status`, `model_used`, `details_json` | Delivery history |

Initialize tables: `uv run python -m app.db.schema`

---

## Environment Variables

Copy `.env.example` to `.env` and populate:

```env
# Required
DATABASE_URL=postgresql://user:password@ep-xxx.neon.tech/neondb?sslmode=require
GROQ_API_KEY=gsk_xxx

# Required for email (optional — falls back to dry-run)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
EMAIL_FROM=noreply@example.com
EMAIL_TO=subscriber@example.com
```

GitHub Actions secrets must mirror these names exactly.

---

## Development Setup

```bash
# Install dependencies
uv sync

# Verify setup (tests DB + Groq connectivity)
uv run python scripts/test_setup.py

# Initialize database tables
uv run python -m app.db.schema

# Run a single stage
uv run python main.py ingest
```

### Docker

```bash
docker compose build
docker compose up -d
docker compose exec engine uv run python main.py ingest
```

---

## Code Conventions

### Naming
- `snake_case` for functions and variables
- `CamelCase` for classes and Pydantic models
- SQLAlchemy table classes suffixed with `Table` (e.g., `ArticleTable`, `InsightTable`)
- Private helpers prefixed with `_` (e.g., `_get_client`, `_prepare_text`)

### Function naming in pipeline modules
- **Every** pipeline module must define a top-level `run()` function — never `main()` or `run_batch()` or any other name. This is required by both `main.py` and the CI workflow.

### LLM output
- All Groq calls use `response_format={"type": "json_object"}` — never parse free-text
- System prompts always define the exact JSON schema expected
- Parse with `json.loads()` and handle `json.JSONDecodeError`

### Error handling
- Module-level imports must not fail even when env vars are missing (connect/auth only on first use)
- API clients are lazy-initialized inside functions, not at module scope
- Retry with exponential backoff on Groq `RateLimitError` (see `groq_client.py`)

### Type hints
- Full type annotations on all functions (Python 3.11+ union syntax `X | Y`)
- Pydantic for data validation at system boundaries
- SQLAlchemy mapped columns use explicit type hints

### Logging
- Each module: `logger = logging.getLogger(__name__)`
- `logging.basicConfig(level=logging.INFO)` only in `__main__` blocks and entry-point modules
- Log token counts, latencies, and key decisions

---

## CI/CD

### CI workflow (`.github/workflows/ci.yml`)
- Triggers on push/PR to `main`
- Runs `uv sync` then validates all pipeline module imports
- Requires GitHub secrets: `DATABASE_URL`, `GROQ_API_KEY`

### Daily pipeline (`.github/workflows/daily.yml`)
- Cron: `0 6 * * *` (6 AM UTC); also triggerable manually
- Runs all pipeline stages sequentially
- Email stage has `continue-on-error: true`
- Additional secrets needed: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `EMAIL_FROM`, `EMAIL_TO`

### Common CI failure causes
1. **Import error** — A pipeline module doesn't expose `run()` (see naming convention above)
2. **Missing secret** — `DATABASE_URL` or `GROQ_API_KEY` not set in GitHub repository secrets
3. **Dependency conflict** — `torch` is pinned to `>=2.2.0,<2.3.0`; `numpy` to `<2.0.0` for compatibility

---

## Key Design Decisions

- **Groq via OpenAI-compatible endpoint** — `langchain-openai` is used with `base_url="https://api.groq.com/openai/v1"` to avoid `langchain-groq` version conflicts
- **All state persisted** — No in-memory caching; all pipeline output goes to Neon Postgres, enabling resumable runs
- **Agentic vs non-agentic synthesis** — Use `agent` stage for richer RAG-augmented insights; use `synthesize` for speed
- **Evaluation built-in** — `eval` stage runs schema validation, LLM-as-judge coherence scoring, and cosine novelty detection before any content is published
- **Email is optional** — Pipeline succeeds even without AWS credentials (dry-run mode)

---

## Adding a New Pipeline Stage

1. Create `app/<module>/your_stage.py` with a top-level `run()` function
2. Add a new `elif stage == "<name>":` block in `main.py`
3. Add the import to the CI validation step in `.github/workflows/ci.yml`
4. Add a new step to `.github/workflows/daily.yml`
5. If writing to DB, add a new table class to `app/db/schema.py` and call `Base.metadata.create_all(engine)` to migrate

---

## Adding a New Content Source

1. Create `app/ingestion/<source>_scraper.py` inheriting from `BaseScraper` (`app/ingestion/base.py`)
2. Implement `scrape() -> list[Article]`
3. Import and call it in `app/ingestion/run.py` alongside `RSSScraper` and `YouTubeScraper`
4. Add source URLs/IDs to `app/config.py`
