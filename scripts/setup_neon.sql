-- Neon Postgres schema for AI Trend Intelligence Engine (optional)
-- Prefer: uv run python -m app.db.schema (schema is defined in app/db/schema.py)
-- Or run this file: psql $DATABASE_URL -f scripts/setup_neon.sql

-- Enable pgvector for future RAG/embedding storage
CREATE EXTENSION IF NOT EXISTS vector;

-- Articles table: raw ingested content from RSS, YouTube, etc.
CREATE TABLE IF NOT EXISTS articles (
    id          BIGSERIAL PRIMARY KEY,
    url         TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    summary     TEXT,
    raw_content TEXT NOT NULL DEFAULT '',
    published_at TIMESTAMPTZ,
    image       TEXT,
    images      JSONB,
    source_type TEXT NOT NULL,
    source_url  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_articles_source_type ON articles (source_type);
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_created_at ON articles (created_at DESC);

COMMENT ON TABLE articles IS 'Ingested articles/videos from RSS, YouTube, Hacker News, etc.';
