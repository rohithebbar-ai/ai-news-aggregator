# AI Trend Intelligence Engine

An intelligent news aggregation and analysis system that scrapes AI-related content from multiple sources (YouTube channels, RSS feeds), processes them through a RAG-enhanced multi-stage LLM pipeline, and publishes structured intelligence briefings with automated email delivery.

## Overview

This project aggregates and analyzes AI news from multiple sources:

- **RSS Feeds:** Monitors AI-focused blogs and research outlets
- **YouTube Channels:** Scrapes videos and extracts transcripts from configured channels
- **Processing:** Summarizes content, groups themes, and synthesizes cross-source insights using LLM
- **RAG:** Retrieves relevant past articles and insights via vector search for temporal trend tracking
- **Agentic Synthesis:** LLM autonomously selects MCP tools to query history, generate diagrams, and send alerts
- **Evaluation:** Validates every LLM output with schema checks, coherence scoring, and novelty detection
- **Delivery:** Publishes structured blog posts and sends email digests via AWS SES

## Architecture

```mermaid
flowchart TB
    subgraph EC2["AWS EC2 - Dockerized"]
        CRON["Cron Jobs"] --> INGEST["Ingestion\nRSS + YouTube"]
        INGEST --> EMBED["Embedding\nall-MiniLM-L6-v2"]
        EMBED --> AGENT["Agentic Synthesis\nMCP Tools + LLM Pipeline"]
        AGENT --> PUBLISH["Publishing\nBlog + Email"]
    end

    INGEST --> NEON["Neon Postgres + pgvector"]
    AGENT --> NEON
    AGENT --> GROQ["Groq API\nLLaMA / Mixtral"]
    PUBLISH --> SES["AWS SES"]
    NEON --> VERCEL["Vercel Frontend"]
    GH["GitHub Actions"] --> EC2
```

## How It Works

### Pipeline Flow

**Ingestion** (`app/ingestion/`)

Runs all registered scrapers, fetches articles and videos from configured sources, deduplicates by URL, and saves raw content to database.

**Embedding** (`app/embeddings/`)

Generates 384-dimensional vector embeddings using all-MiniLM-L6-v2 (runs locally on CPU). Stores embeddings in pgvector for RAG retrieval.

**Agentic Synthesis** (`app/agent/`)

LLM receives the current batch and uses MCP tools to retrieve past articles and insights via semantic search. Groups themes, detects trend acceleration, identifies contradictions, and decides which tools to invoke based on what it discovers.

**LLM Pipeline** (`app/llm/`)

- Stage 1: Structured article summarization (JSON output)
- Stage 2: Theme grouping with cross-article relationships
- Stage 3: Insight synthesis with historical context from RAG
- Stage 4: Mermaid diagram generation
- Stage 5: Forward outlook with confidence levels

**Evaluation** (`app/llm/evaluator.py`)

Schema validation on every LLM output. LLM-as-judge scores theme coherence. Novelty detection via cosine similarity against past insights. All metrics logged to `eval_logs` table.

**Publishing** (`app/publishing/`)

Generates structured blog post, stores in Neon, and sends email digest via AWS SES. The agent decides whether to send email based on signal significance.

### Daily Pipeline

The `run_daily_pipeline()` function orchestrates all steps:

1. Runs ingestion scrapers
2. Embeds new articles
3. Triggers agentic synthesis loop
4. Evaluates outputs
5. Publishes blog post
6. Sends email digest (if agent decides significance is high)

## Project Structure

```
ai-trend-engine/
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI entry point
│   ├── config.py              # Configuration (RSS feeds, YouTube channels)
│   ├── daily_runner.py        # Main pipeline orchestrator
│   ├── ingestion/             # Content scrapers
│   │   ├── base.py            # Base scraper class
│   │   ├── rss_scraper.py     # RSS feed scraper
│   │   ├── youtube_scraper.py # YouTube transcript scraper
│   │   └── deduplicator.py    # URL-based deduplication
│   ├── embeddings/            # Vector embedding layer
│   │   ├── embed_service.py   # MiniLM embedding model
│   │   └── vector_store.py    # pgvector query interface
│   ├── llm/                   # LLM pipeline stages
│   │   ├── groq_client.py     # Groq API wrapper
│   │   ├── summarizer.py      # Stage 1: Summarization
│   │   ├── theme_grouper.py   # Stage 2: Theme clustering
│   │   ├── synthesizer.py     # Stage 3: Insight synthesis
│   │   └── evaluator.py       # Output quality evaluation
│   ├── agent/                 # Agentic orchestration
│   │   ├── agent_loop.py      # ReAct-style agent loop
│   │   └── mcp_server.py      # MCP tool definitions
│   ├── publishing/            # Output generation
│   │   ├── blog_generator.py  # Blog post assembly
│   │   ├── email_sender.py    # SES email dispatch
│   │   └── mermaid_generator.py
│   ├── db/                    # Database layer
│   │   ├── connection.py      # Neon connection management
│   │   ├── models.py          # Pydantic models
│   │   └── repository.py      # Data access layer
│   └── profiles/              # User configuration
│       └── user_profile.py
├── tests/
├── scripts/
│   ├── test_setup.py          # Setup verification
│   └── setup_neon.sql         # Database schema
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── uv.lock
```

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Neon account ([neon.tech](https://neon.tech) - free tier)
- Groq API key ([console.groq.com](https://console.groq.com) - free tier)
- Docker

### Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/ai-trend-engine.git
cd ai-trend-engine
```

Install dependencies:

```bash
uv sync
```

Configure environment variables (copy `.env.example` to `.env`):

```env
DATABASE_URL=postgresql://user:pass@ep-xxx.region.aws.neon.tech/db?sslmode=require
GROQ_API_KEY=gsk_your_key_here
```

Initialize database:

```bash
psql $DATABASE_URL -f scripts/setup_neon.sql
```

Verify setup:

```bash
uv run python scripts/test_setup.py
```

Configure RSS feeds and YouTube channels in `app/config.py`.

### Running

Full pipeline:

```bash
uv run python -m app.daily_runner
```

Individual steps:

```bash
# Ingestion
uv run python -m app.ingestion.rss_scraper
uv run python -m app.ingestion.youtube_scraper

# LLM Pipeline
uv run python -m app.llm.summarizer
uv run python -m app.llm.theme_grouper
uv run python -m app.llm.synthesizer

# Agentic Synthesis
uv run python -m app.agent.agent_loop

# Publishing
uv run python -m app.publishing.blog_generator
uv run python -m app.publishing.email_sender
```

FastAPI server:

```bash
uv run uvicorn app.main:app --reload
```

### Docker

Build and run:

```bash
docker compose build
docker compose up -d
```

### Deployment

The project is configured for deployment on AWS EC2:

- **Compute:** EC2 t3.micro instance running Docker
- **Database:** Neon Postgres with pgvector (external, free tier)
- **CI/CD:** GitHub Actions deploys on push to main via SSH
- **Scheduling:** Cron jobs for daily ingestion and bi-daily synthesis

## Technology Stack

- **Python 3.12+** - Core language
- **FastAPI** - API layer
- **Groq API** - LLM inference (LLaMA/Mixtral)
- **sentence-transformers** - Local embedding model (all-MiniLM-L6-v2)
- **Neon Postgres** - Database with pgvector extension
- **Pydantic** - Data validation
- **feedparser** - RSS parsing
- **youtube-transcript-api** - Video transcripts
- **AWS SES** - Email delivery
- **Docker** - Containerization
- **GitHub Actions** - CI/CD
- **uv** - Package management

## License

MIT